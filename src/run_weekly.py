# 주간 사이클 오케스트레이터: 스냅샷 -> 스크리너 -> 뉴스 -> LLM 블라인드 판단 -> 로그 -> 3파전 벤치마크
from datetime import datetime

import benchmark
import config
import risk_metrics
from data_collector import (
    assert_before_market_open,
    get_index_levels,
    get_last_completed_trading_day,
    get_universe_snapshot,
)
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


def _get_previous_ai_portfolio(conn) -> list[dict]:
    """AI 자신의 지난주 목표 포트폴리오만 가져온다 (track_id=ai_blind 고정).
    holdings 테이블(내 실제 보유, track_id=my_holdings)은 여기서 절대 조회하지 않는다 — 블라인드 유지."""
    latest = conn.execute(
        "SELECT week_id FROM decisions WHERE track_id = ? ORDER BY decision_date DESC LIMIT 1",
        (config.TRACK_AI_BLIND,),
    ).fetchone()
    if latest is None:
        return []
    rows = conn.execute(
        "SELECT stock_code, stock_name, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
        (config.TRACK_AI_BLIND, latest["week_id"]),
    ).fetchall()
    return [dict(r) for r in rows]


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


def _log_equal_weight_decisions(conn, week_id: str, date: str, shortlist_df):
    """④: 그 주 shortlist를 LLM 판단 없이 동일가중으로 담는 baseline 트랙 로그."""
    n = len(shortlist_df)
    if n == 0:
        return
    weight = 100.0 / n
    for _, r in shortlist_df.iterrows():
        conn.execute(
            """INSERT INTO decisions
               (track_id, week_id, decision_date, stock_code, stock_name, action, target_weight, rationale, conviction)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config.TRACK_EQUAL_WEIGHT, week_id, date, r["Code"], r["Name"],
                "유지", weight, "동일가중 baseline (LLM 판단 없이 스크리너 shortlist 전체를 균등 보유)", "중",
            ),
        )


def run_decision(date: str | None = None):
    """판단 단계: 장 시작 전에 실행하며, 실행 시각의 'latest'가 아니라 직전 완료된 거래일
    종가로 날짜를 명시 고정한다 (공휴일이 껴도 거래일 캘린더 기준으로 자동으로 건너뜀).
    아직 체결/벤치마크는 하지 않는다."""
    assert_before_market_open()
    decision_date = get_last_completed_trading_day(date)
    week_id = _week_id(decision_date)
    print(f"[run_decision] 판단 기준일={decision_date} ({week_id}) 판단 시작")

    init_db()
    conn = get_connection()

    print("[1/4] 유니버스 스냅샷 수집")
    universe = get_universe_snapshot()
    _log_universe_snapshot(conn, week_id, decision_date, len(universe))
    conn.commit()

    print("[2/4] 정량 스크리너 실행")
    shortlist_df, screener_output_df = build_shortlist(universe, week_id, decision_date)
    _log_screener_output(conn, screener_output_df)
    _log_equal_weight_decisions(conn, week_id, decision_date, shortlist_df)
    conn.commit()
    print(f"  shortlist {len(shortlist_df)}개 확정")

    print("[3/4] shortlist 뉴스 + 시장 전반 뉴스 수집 (판단 시각 이후 게시분은 PIT 필터로 배제)")
    stock_names = shortlist_df["Name"].tolist()
    news_by_stock = collect_shortlist_news(stock_names, decision_date)
    market_news = collect_market_news(decision_date)

    print("[4/4] LLM 판단 (AI 자신의 지난주 포트폴리오 참고, 내 실제 보유는 여전히 미포함)")
    previous_portfolio = _get_previous_ai_portfolio(conn)
    shortlist_records = shortlist_df[["Code", "Name", "momentum_score"]].rename(
        columns={"Code": "stock_code", "Name": "stock_name"}
    ).to_dict("records")
    decisions = judge(shortlist_records, news_by_stock, market_news, previous_portfolio)
    _log_ai_decisions(conn, week_id, decision_date, decisions)
    conn.commit()
    conn.close()
    print(f"  {len(decisions)}개 종목 판단 완료")

    print("[run_decision] 완료")
    return {"week_id": week_id, "date": decision_date, "decisions": decisions}


def run_execution(date: str | None = None):
    """체결 단계: 장 시작 이후(실제 당일 시가가 나온 뒤) 실행. 3파전 벤치마크를 확정한다."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    week_id = _week_id(date)
    print(f"[run_execution] {date} ({week_id}) 체결/벤치마크 시작")

    results = benchmark.snapshot_all(week_id, date)
    for r in results:
        print(f"  {r['track_id']}: {r['value']:,.0f}원 ({r['return_pct']:+.2%})")

    print("[run_execution] 위험조정 지표 계산")
    risk_metrics.compute_and_log(week_id, date)

    print("[run_execution] 완료")
    return {"week_id": week_id, "date": date, "benchmark": results}


def run(date: str | None = None):
    """CLI 수동 실행 진입점. 판단만 실행한다 — look-ahead 편향 방지를 위해 판단과 체결은
    반드시 시간 간격을 두고 분리해야 하므로, 이 함수는 체결/벤치마크를 절대 자동으로
    이어서 실행하지 않는다 (성과 기록 오염 방지). 체결은 장 시작 후 run_execution()을
    별도로 호출할 것 — 실서비스에서는 telegram_bot.py의 decision_job/execution_job이
    각각 다른 시각에 이 둘을 스케줄한다."""
    print("[run] 판단만 실행합니다. 체결/벤치마크는 장 시작 후 run_execution()을 따로 호출하세요.")
    return run_decision(date)


if __name__ == "__main__":
    run()
