# 주간 사이클 오케스트레이터: 스냅샷 -> 스크리너 -> 뉴스 -> LLM 블라인드 판단 -> 로그 -> 3파전 벤치마크
from datetime import datetime

import benchmark
import config
from data_collector import get_index_levels, get_universe_snapshot
from db import get_connection, init_db
from llm_judge import judge
from news_collector import collect_market_news, collect_shortlist_news
from screener import build_shortlist


def _week_id(date: str) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


def _log_universe_snapshot(conn, week_id: str, date: str, universe_count: int):
    idx = get_index_levels(date)
    conn.execute(
        """INSERT INTO universe_snapshot (week_id, snapshot_date, kospi_index, kosdaq_index, total_universe_count)
           VALUES (?, ?, ?, ?, ?)""",
        (week_id, date, idx["kospi_index"], idx["kosdaq_index"], universe_count),
    )


def _log_screener_output(conn, screener_output_df):
    for _, r in screener_output_df.iterrows():
        conn.execute(
            """INSERT INTO screener_output
               (week_id, stock_code, stock_name, market_cap, trading_value, momentum_score, cluster_id, rank, included_in_shortlist, exclude_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["week_id"], r["Code"], r["Name"], int(r["Marcap"]), int(r["Amount"]),
                float(r["momentum_score"]), int(r["cluster_id"]) if r["cluster_id"] is not None else None,
                int(r["rank"]), int(bool(r["included_in_shortlist"])), r["exclude_reason"],
            ),
        )


def _log_ai_decisions(conn, week_id: str, date: str, decisions: list[dict]):
    for d in decisions:
        conn.execute(
            """INSERT INTO decisions
               (track_id, week_id, decision_date, stock_code, stock_name, action, target_weight, rationale, conviction)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config.TRACK_AI_BLIND, week_id, date, d["stock_code"], d["stock_name"],
                d["action"], d["target_weight"], d["rationale"], d["conviction"],
            ),
        )


def run_decision(date: str | None = None):
    """판단 단계: 장 시작 전(금요일 종가+주말 뉴스 기준)에 실행. 아직 체결/벤치마크는 안 한다."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    week_id = _week_id(date)
    print(f"[run_decision] {date} ({week_id}) 판단 시작")

    init_db()
    conn = get_connection()

    print("[1/4] 유니버스 스냅샷 수집")
    universe = get_universe_snapshot()
    _log_universe_snapshot(conn, week_id, date, len(universe))
    conn.commit()

    print("[2/4] 정량 스크리너 실행")
    shortlist_df, screener_output_df = build_shortlist(universe, week_id)
    _log_screener_output(conn, screener_output_df)
    conn.commit()
    print(f"  shortlist {len(shortlist_df)}개 확정")

    print("[3/4] shortlist 뉴스 + 시장 전반 뉴스 수집")
    stock_names = shortlist_df["Name"].tolist()
    news_by_stock = collect_shortlist_news(stock_names)
    market_news = collect_market_news()

    print("[4/4] LLM 블라인드 판단")
    shortlist_records = shortlist_df[["Code", "Name", "momentum_score"]].rename(
        columns={"Code": "stock_code", "Name": "stock_name"}
    ).to_dict("records")
    decisions = judge(shortlist_records, news_by_stock, market_news)
    _log_ai_decisions(conn, week_id, date, decisions)
    conn.commit()
    conn.close()
    print(f"  {len(decisions)}개 종목 판단 완료")

    print("[run_decision] 완료")
    return {"week_id": week_id, "date": date, "decisions": decisions}


def run_execution(date: str | None = None):
    """체결 단계: 장 시작 이후(실제 당일 시가가 나온 뒤) 실행. 3파전 벤치마크를 확정한다."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    week_id = _week_id(date)
    print(f"[run_execution] {date} ({week_id}) 체결/벤치마크 시작")

    results = benchmark.snapshot_all(week_id, date)
    for r in results:
        print(f"  {r['track_id']}: {r['value']:,.0f}원 ({r['return_pct']:+.2%})")

    print("[run_execution] 완료")
    return {"week_id": week_id, "date": date, "benchmark": results}


def run(date: str | None = None):
    """판단+체결을 한번에 (수동 테스트/일회성 실행용). 실서비스에서는 run_decision과
    run_execution을 장 시작 전/후로 나눠서 따로 스케줄한다 (telegram_bot.py 참조)."""
    decision = run_decision(date)
    execution = run_execution(date)
    return {**decision, **execution}


if __name__ == "__main__":
    run()
