# 3파전(내 보유 / AI 블라인드 / 지수) 주간 수익률 스냅샷 계산
import FinanceDataReader as fdr

import config
from db import get_connection


def _anchor_value(conn) -> float:
    """모든 트랙이 오늘 스냅샷 기준 동일 원금(내 보유 평가금액)에서 출발한다."""
    row = conn.execute("SELECT SUM(snapshot_value) AS total FROM holdings").fetchone()
    return float(row["total"])


def _price_change(code: str, from_date: str, to_date: str) -> float:
    hist = fdr.DataReader(code, from_date, to_date)
    if len(hist) < 2:
        return 0.0
    return float(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)


def _entry_exit_return(code: str, from_date: str, to_date: str) -> float:
    """AI 트랙 전용: 판단(월요일 종가+뉴스)과 체결(화요일 시가)을 분리해 look-ahead 편향을 제거.
    매주 완전 리밸런싱을 가정하므로 진입(매수)에는 슬리피지+수수료, 청산(=다음 스냅샷 시점에 전량
    매도하고 새로 담는다고 가정한 매도)에는 수수료+거래세를 반영한다."""
    hist = fdr.DataReader(code, from_date, to_date)
    if len(hist) < 2:
        return 0.0
    entry_price = float(hist["Open"].iloc[0]) * (1 + config.EXECUTION_SLIPPAGE_PCT + config.BROKER_FEE_PCT)
    exit_price = float(hist["Open"].iloc[-1]) * (1 - config.BROKER_FEE_PCT - config.TRANSACTION_TAX_PCT)
    return exit_price / entry_price - 1


def _index_change(from_date: str, to_date: str) -> float:
    kospi = _price_change("KS11", from_date, to_date)
    kosdaq = _price_change("KQ11", from_date, to_date)
    return 0.5 * kospi + 0.5 * kosdaq  # 코스피/코스닥 동일가중 블렌드 (브리프상 명시 안 됨, V1 가정)


def snapshot_my_holdings(week_id: str, date: str) -> dict:
    conn = get_connection()
    anchor = _anchor_value(conn)
    holdings = conn.execute("SELECT stock_code, quantity FROM holdings").fetchall()

    listing = fdr.StockListing("KRX").set_index("Code")["Close"]
    value = sum(int(listing.loc[h["stock_code"]]) * h["quantity"] for h in holdings)

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
