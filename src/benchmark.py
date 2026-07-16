# 3파전(내 보유 / AI 블라인드 / 지수) 주간 수익률 스냅샷 계산
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import config
from db import get_connection


def _anchor_value(conn) -> float:
    """모든 트랙이 오늘 스냅샷 기준 동일 원금(내 보유 평가금액)에서 출발한다."""
    row = conn.execute("SELECT SUM(snapshot_value) AS total FROM holdings").fetchone()
    return float(row["total"])


def _get_open_price(code: str, date: str) -> float:
    """date의 실제 시가를 명시적으로 가져온다. 세 트랙(내 보유/AI/지수) 모두 이 함수 하나로
    통일해서 같은 기준(화요일 시가)에서 출발하게 한다. 그 날짜 데이터가 아직 없으면
    (장 시작 전에 잘못 호출된 경우 등) 조용히 넘어가지 않고 바로 에러를 낸다."""
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


def _raw_return(code: str, from_date: str, to_date: str) -> float:
    """비용 없는 순수 시가 대비 시가 수익률. 실제로 거래(비중 변경)가 없었던 보유 구간에 쓴다 —
    유지되는 포지션은 거래비용이 없어야 하므로 순수 가격변동만 반영."""
    entry_open = _get_open_price(code, from_date)
    exit_open = _get_open_price(code, to_date)
    return exit_open / entry_open - 1


def _rebalance_cost_pct(prev_weights: dict, curr_weights: dict) -> float:
    """AI 트랙 전용: 지난주 대비 이번 주 목표비중의 실제 변화(델타)에만 거래비용을 부과한다.
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
    kospi = _get_open_price("KS11", to_date) / _get_open_price("KS11", from_date) - 1
    kosdaq = _get_open_price("KQ11", to_date) / _get_open_price("KQ11", from_date) - 1
    return 0.5 * kospi + 0.5 * kosdaq  # 코스피/코스닥 동일가중 블렌드 (브리프상 명시 안 됨, V1 가정)


def snapshot_my_holdings(week_id: str, date: str) -> dict:
    conn = get_connection()
    anchor = _anchor_value(conn)
    holdings = conn.execute("SELECT stock_code, quantity FROM holdings").fetchall()

    value = sum(_get_open_price(h["stock_code"], date) * h["quantity"] for h in holdings)

    return_pct = value / anchor - 1
    conn.execute(
        "INSERT INTO snapshots (track_id, week_id, snapshot_date, portfolio_value, return_pct) VALUES (?, ?, ?, ?, ?)",
        (config.TRACK_MY_HOLDINGS, week_id, date, value, return_pct),
    )
    conn.commit()
    conn.close()
    return {"track_id": config.TRACK_MY_HOLDINGS, "value": value, "return_pct": return_pct}


def snapshot_ai_track(week_id: str, date: str) -> dict:
    """지난주 보유분은 순수 가격변동만 반영하고(거래 안 했으니 비용 없음), 이번 주 새 목표비중과의
    델타에만 리밸런싱 비용을 부과한다 (stateful — 매주 전량 재구성이 아니라 지난주 포트폴리오를
    이어받아 부분 조정)."""
    conn = get_connection()
    anchor = _anchor_value(conn)

    prev = conn.execute(
        "SELECT * FROM snapshots WHERE track_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (config.TRACK_AI_BLIND,),
    ).fetchone()

    if prev is None:
        value = anchor
    else:
        prev_decisions = conn.execute(
            "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
            (config.TRACK_AI_BLIND, prev["week_id"]),
        ).fetchall()
        prev_weights = {d["stock_code"]: d["target_weight"] / 100 for d in prev_decisions}

        curr_decisions = conn.execute(
            "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
            (config.TRACK_AI_BLIND, week_id),
        ).fetchall()
        if not curr_decisions:
            raise RuntimeError(f"{week_id}에 대한 AI 판단이 없음 — decision_job이 먼저 실행됐는지 확인 필요")
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
        (config.TRACK_AI_BLIND, week_id, date, value, return_pct),
    )
    conn.commit()
    conn.close()
    return {"track_id": config.TRACK_AI_BLIND, "value": value, "return_pct": return_pct}


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
    return [
        snapshot_my_holdings(week_id, date),
        snapshot_ai_track(week_id, date),
        snapshot_index_track(week_id, date),
    ]
