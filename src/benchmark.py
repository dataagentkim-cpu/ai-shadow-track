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


def _entry_exit_return(code: str, from_date: str, to_date: str) -> float:
    """AI 트랙 전용: 판단(직전 완료 거래일 종가+뉴스)과 체결(다음 거래일 시가)을 분리해
    look-ahead 편향을 제거. 매주 완전 리밸런싱을 가정하므로 진입(매수)/청산(=다음 스냅샷
    시점에 전량 매도 후 새로 담는다고 가정)에 각각 불리한 방향으로 슬리피지를 적용하고,
    매매수수료는 양방향, 증권거래세는 매도(청산) 시에만 반영한다."""
    entry_open = _get_open_price(code, from_date)
    exit_open = _get_open_price(code, to_date)
    entry_price = entry_open * (1 + config.EXECUTION_SLIPPAGE_PCT + config.BROKER_FEE_PCT)
    exit_price = exit_open * (1 - config.EXECUTION_SLIPPAGE_PCT - config.BROKER_FEE_PCT - config.TRANSACTION_TAX_PCT)
    return exit_price / entry_price - 1


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
        weighted_return = sum(
            (d["target_weight"] / 100) * _entry_exit_return(d["stock_code"], prev["snapshot_date"], date)
            for d in prev_decisions
        )
        value = prev["portfolio_value"] * (1 + weighted_return)

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
