# 4파전(내 보유 / AI 블라인드 / 지수 / 동일가중 baseline) 주간 총수익 스냅샷 계산
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import config
import dart_client
from db import get_connection


def _anchor_value(conn) -> float:
    """모든 트랙이 오늘 스냅샷 기준 동일 원금(내 보유 평가금액)에서 출발한다."""
    row = conn.execute("SELECT SUM(snapshot_value) AS total FROM holdings").fetchone()
    return float(row["total"])


def _get_open_price(code: str, date: str) -> float:
    """date의 실제 시가를 명시적으로 가져온다. 그 날짜 데이터가 아직 없으면(장 시작 전에
    잘못 호출된 경우 등) 조용히 넘어가지 않고 바로 에러를 낸다."""
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    hist = fdr.DataReader(code, start, date)
    if hist.empty:
        raise RuntimeError(f"{code}: {date} 시가 데이터를 가져오지 못함")
    last_date = hist.index[-1].strftime("%Y-%m-%d")
    if last_date != date:
        raise RuntimeError(
            f"{code}: {date} 시가가 아직 없음 (마지막 확인된 거래일 {last_date}) — 장 시작 전에 실행됐을 가능성"
        )
    return float(hist["Open"].iloc[-1])


def _get_open_price_safe(code: str, date: str) -> tuple[float, bool]:
    """실제 시가를 가져오되, 거래정지/상장폐지로 그 날짜 데이터가 없으면 마지막으로 확인된
    가격으로 동결 청산 처리한다. 반환값: (가격, 상장폐지로_추정되는지)."""
    try:
        return _get_open_price(code, date), False
    except RuntimeError:
        start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
        hist = fdr.DataReader(code, start, date)
        if hist.empty:
            raise RuntimeError(f"{code}: 최근 60일간 거래 데이터가 전혀 없음 (완전 상장폐지 가능성 — 수동 확인 필요)")
        return float(hist["Open"].iloc[-1]), True


def _dividend_accrual(code: str, from_date: str, to_date: str) -> float:
    """보유 기간(from_date~to_date) 동안의 세후 배당수익률을 주 단위로 안분한 근사치.
    DART 사업보고서의 연간 현금배당수익률을 52주로 나눠 보유 기간만큼 곱하고, 배당소득세
    15.4%를 뗀다. 실제 배당은 연 1회 특정일에 지급되지만, 개별 지급일 데이터까지는 없어
    보유기간에 걸쳐 매끄럽게 발생한다고 근사한다 (실제와 시점 오차 있음, context-notes.md 참조)."""
    weeks = max((datetime.strptime(to_date, "%Y-%m-%d") - datetime.strptime(from_date, "%Y-%m-%d")).days / 7, 0)
    annual_yield = dart_client.get_dividend_yield_pct(code, to_date) / 100
    return annual_yield / 52 * weeks * (1 - config.DIVIDEND_TAX_PCT)


def _raw_return(code: str, from_date: str, to_date: str) -> float:
    """비용 없는 순수 '총수익'(가격변동+세후 배당 안분). 실제로 거래(비중 변경)가 없었던
    보유 구간에 쓴다 — 유지되는 포지션은 거래비용이 없어야 하므로 가격+배당만 반영."""
    entry_open, _ = _get_open_price_safe(code, from_date)
    exit_open, delisted = _get_open_price_safe(code, to_date)
    if delisted:
        print(f"[benchmark] 경고: {code} 최근 거래 데이터 없음 — 마지막 시가로 동결 청산 처리")
    price_return = exit_open / entry_open - 1
    return price_return + _dividend_accrual(code, from_date, to_date)


def _rebalance_cost_pct(prev_weights: dict, curr_weights: dict) -> float:
    """지난주 대비 이번 주 목표비중의 실제 변화(델타)에만 거래비용을 부과한다.
    유지되는 부분(델타 0)은 비용이 없다. 델타가 양수(비중 확대/신규 편입)면 매수 쪽 비용
    (슬리피지+수수료), 음수(비중 축소/전량 매도)면 매도 쪽 비용(슬리피지+수수료+거래세)을 뗀다."""
    codes = set(prev_weights) | set(curr_weights)
    cost = 0.0
    for code in codes:
        delta = curr_weights.get(code, 0.0) - prev_weights.get(code, 0.0)
        if delta > 0:
            cost += delta * (config.EXECUTION_SLIPPAGE_PCT + config.BROKER_FEE_PCT)
        elif delta < 0:
            cost += abs(delta) * (config.EXECUTION_SLIPPAGE_PCT + config.BROKER_FEE_PCT + config.TRANSACTION_TAX_PCT)
    return cost


def _index_change(from_date: str, to_date: str) -> float:
    """코스피/코스닥 총수익(가격+배당) 변화. 개별 종목처럼 DART로 정확히 계산할 지수 자체의
    배당재투자 데이터 소스가 없어, 통상 언급되는 평균 배당수익률을 고정 근사치로 더한다."""
    weeks = max((datetime.strptime(to_date, "%Y-%m-%d") - datetime.strptime(from_date, "%Y-%m-%d")).days / 7, 0)
    after_tax = 1 - config.DIVIDEND_TAX_PCT

    kospi_price = _get_open_price("KS11", to_date) / _get_open_price("KS11", from_date) - 1
    kospi_div = config.KOSPI_DIVIDEND_YIELD_APPROX_PCT / 100 / 52 * weeks * after_tax
    kosdaq_price = _get_open_price("KQ11", to_date) / _get_open_price("KQ11", from_date) - 1
    kosdaq_div = config.KOSDAQ_DIVIDEND_YIELD_APPROX_PCT / 100 / 52 * weeks * after_tax

    kospi = kospi_price + kospi_div
    kosdaq = kosdaq_price + kosdaq_div
    return 0.5 * kospi + 0.5 * kosdaq  # 코스피/코스닥 동일가중 블렌드 (브리프상 명시 안 됨, V1 가정)


def snapshot_my_holdings(week_id: str, date: str) -> dict:
    """내 실제 보유(고정 수량, 리밸런싱 없음)의 총수익 스냅샷. 배당을 포함해야 해서 첫 주 이후로는
    절대값 재계산이 아니라 직전 스냅샷에서 총수익률을 체인으로 이어간다."""
    conn = get_connection()
    anchor = _anchor_value(conn)
    holdings = conn.execute("SELECT stock_code, quantity FROM holdings").fetchall()

    prev = conn.execute(
        "SELECT * FROM snapshots WHERE track_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (config.TRACK_MY_HOLDINGS,),
    ).fetchone()

    if prev is None:
        value = anchor
    else:
        prev_prices = {h["stock_code"]: _get_open_price(h["stock_code"], prev["snapshot_date"]) for h in holdings}
        prev_total = sum(prev_prices[h["stock_code"]] * h["quantity"] for h in holdings)
        weighted_return = sum(
            (prev_prices[h["stock_code"]] * h["quantity"] / prev_total)
            * _raw_return(h["stock_code"], prev["snapshot_date"], date)
            for h in holdings
        )
        value = prev["portfolio_value"] * (1 + weighted_return)

    return_pct = value / anchor - 1
    conn.execute(
        "INSERT INTO snapshots (track_id, week_id, snapshot_date, portfolio_value, return_pct) VALUES (?, ?, ?, ?, ?)",
        (config.TRACK_MY_HOLDINGS, week_id, date, value, return_pct),
    )
    conn.commit()
    conn.close()
    return {"track_id": config.TRACK_MY_HOLDINGS, "value": value, "return_pct": return_pct}


def _snapshot_rebalanced_track(track_id: str, week_id: str, date: str) -> dict:
    """지난주 목표비중을 이어받아 보유수익(가격+배당)을 반영한 뒤, 이번 주 새 목표비중과의
    델타에만 리밸런싱 비용을 부과하는 공통 로직. AI 트랙(②)과 동일가중 baseline(④)이 이 함수를
    그대로 공유해서 둘의 체결/비용 규칙이 항상 동일하게 유지된다 (②−④ 스프레드가 순수하게
    "LLM 판단의 기여도"만 반영하도록)."""
    conn = get_connection()
    anchor = _anchor_value(conn)

    prev = conn.execute(
        "SELECT * FROM snapshots WHERE track_id = ? ORDER BY snapshot_date DESC LIMIT 1", (track_id,)
    ).fetchone()

    if prev is None:
        value = anchor
    else:
        prev_decisions = conn.execute(
            "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
            (track_id, prev["week_id"]),
        ).fetchall()
        prev_weights = {d["stock_code"]: d["target_weight"] / 100 for d in prev_decisions}

        curr_decisions = conn.execute(
            "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
            (track_id, week_id),
        ).fetchall()
        if not curr_decisions:
            raise RuntimeError(f"{week_id}에 대한 '{track_id}' 판단이 없음 — decision 단계가 먼저 실행됐는지 확인 필요")
        curr_weights = {d["stock_code"]: d["target_weight"] / 100 for d in curr_decisions}

        holding_return = sum(
            w * _raw_return(code, prev["snapshot_date"], date) for code, w in prev_weights.items()
        )
        value_before_rebalance = prev["portfolio_value"] * (1 + holding_return)

        cost_pct = _rebalance_cost_pct(prev_weights, curr_weights)
        value = value_before_rebalance * (1 - cost_pct)

    return_pct = value / anchor - 1
    conn.execute(
        "INSERT INTO snapshots (track_id, week_id, snapshot_date, portfolio_value, return_pct) VALUES (?, ?, ?, ?, ?)",
        (track_id, week_id, date, value, return_pct),
    )
    conn.commit()
    conn.close()
    return {"track_id": track_id, "value": value, "return_pct": return_pct}


def snapshot_equal_weight_track(week_id: str, date: str) -> dict:
    """④: 그 주 스크리너 shortlist를 LLM 판단 없이 동일가중으로 보유 — ②(LLM)가 이걸 못 이기면
    LLM이 값을 못 하는 것이라는 판단을 위한 baseline."""
    return _snapshot_rebalanced_track(config.TRACK_EQUAL_WEIGHT, week_id, date)


def snapshot_index_track(week_id: str, date: str) -> dict:
    conn = get_connection()
    anchor = _anchor_value(conn)

    prev = conn.execute(
        "SELECT * FROM snapshots WHERE track_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (config.TRACK_INDEX,),
    ).fetchone()

    if prev is None:
        value = anchor
    else:
        value = prev["portfolio_value"] * (1 + _index_change(prev["snapshot_date"], date))

    return_pct = value / anchor - 1
    conn.execute(
        "INSERT INTO snapshots (track_id, week_id, snapshot_date, portfolio_value, return_pct) VALUES (?, ?, ?, ?, ?)",
        (config.TRACK_INDEX, week_id, date, value, return_pct),
    )
    conn.commit()
    conn.close()
    return {"track_id": config.TRACK_INDEX, "value": value, "return_pct": return_pct}


def snapshot_all(week_id: str, date: str) -> list[dict]:
    results = [snapshot_my_holdings(week_id, date)]
    for track_id in config.LENS_TRACKS:
        results.append(_snapshot_rebalanced_track(track_id, week_id, date))
    results.append(snapshot_index_track(week_id, date))
    results.append(snapshot_equal_weight_track(week_id, date))
    return results


def get_alpha_spread(track_id: str = config.TRACK_VALUE, conn=None) -> list[dict]:
    """②x(LLM 렌즈) − ④(동일가중 baseline) 주간/누적 수익률 스프레드. 별도 테이블에 저장하지 않고
    snapshots에서 매번 계산한다 — 두 트랙 값만으로 완전히 유도되는 값이라 중복 저장하지 않음."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    rows = conn.execute(
        """SELECT a.week_id, a.snapshot_date, a.portfolio_value AS lens_value, a.return_pct AS lens_cum,
                  b.portfolio_value AS base_value, b.return_pct AS base_cum
           FROM snapshots a JOIN snapshots b
             ON a.week_id = b.week_id AND a.track_id = ? AND b.track_id = ?
           ORDER BY a.snapshot_date""",
        (track_id, config.TRACK_EQUAL_WEIGHT),
    ).fetchall()
    if own_conn:
        conn.close()

    result = []
    prev_lens_value = prev_base_value = None
    for r in rows:
        weekly_lens = (r["lens_value"] / prev_lens_value - 1) if prev_lens_value else 0.0
        weekly_base = (r["base_value"] / prev_base_value - 1) if prev_base_value else 0.0
        result.append(
            {
                "week_id": r["week_id"],
                "date": r["snapshot_date"],
                "weekly_spread": weekly_lens - weekly_base,
                "cumulative_spread": r["lens_cum"] - r["base_cum"],
            }
        )
        prev_lens_value, prev_base_value = r["lens_value"], r["base_value"]
    return result
