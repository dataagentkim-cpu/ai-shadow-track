# 트랙별 위험조정 지표(Sharpe/Sortino/MDD/적중률/회전율/베타/알파/클러스터 집중도) 계산 및 기록
import pandas as pd

import config
from db import get_connection

_RISK_FREE_WEEKLY = 0.0  # 무위험수익률 0 가정 (V1 단순화)
_ANNUALIZATION_FACTOR = 52 ** 0.5


def _weekly_returns(conn, track_id: str) -> pd.Series:
    """트랙의 주간(비누적) 수익률 시계열 — portfolio_value의 전주 대비 변화율."""
    rows = conn.execute(
        "SELECT snapshot_date, portfolio_value FROM snapshots WHERE track_id = ? ORDER BY snapshot_date",
        (track_id,),
    ).fetchall()
    values = pd.Series(
        [r["portfolio_value"] for r in rows],
        index=pd.to_datetime([r["snapshot_date"] for r in rows]),
    )
    return values.pct_change().dropna()


def _sharpe(weekly_returns: pd.Series) -> float | None:
    if len(weekly_returns) < 2 or weekly_returns.std() == 0:
        return None
    excess = weekly_returns - _RISK_FREE_WEEKLY
    return float(excess.mean() / weekly_returns.std() * _ANNUALIZATION_FACTOR)


def _sortino(weekly_returns: pd.Series) -> float | None:
    downside = weekly_returns[weekly_returns < 0]
    if len(weekly_returns) < 2 or len(downside) == 0 or downside.std() == 0:
        return None
    excess = weekly_returns.mean() - _RISK_FREE_WEEKLY
    return float(excess / downside.std() * _ANNUALIZATION_FACTOR)


def _mdd(weekly_returns: pd.Series) -> float | None:
    if weekly_returns.empty:
        return None
    cum = (1 + weekly_returns).cumprod()
    drawdown = cum / cum.cummax() - 1
    return float(drawdown.min())


def _hit_rate(weekly_returns: pd.Series) -> float | None:
    if weekly_returns.empty:
        return None
    return float((weekly_returns > 0).mean())


def _turnover(conn, track_id: str, week_id: str) -> float | None:
    """이번 주 목표비중이 지난주 대비 실제로 얼마나 바뀌었는지 (원사이드 델타 합의 절반)."""
    curr = conn.execute(
        "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
        (track_id, week_id),
    ).fetchall()
    curr_weights = {r["stock_code"]: r["target_weight"] / 100 for r in curr}

    prev_week_row = conn.execute(
        "SELECT week_id FROM decisions WHERE track_id = ? AND week_id < ? ORDER BY week_id DESC LIMIT 1",
        (track_id, week_id),
    ).fetchone()
    if prev_week_row is None:
        return sum(curr_weights.values())  # 첫 주는 전량 신규 편입 = 100% 턴오버

    prev = conn.execute(
        "SELECT stock_code, target_weight FROM decisions WHERE track_id = ? AND week_id = ?",
        (track_id, prev_week_row["week_id"]),
    ).fetchall()
    prev_weights = {r["stock_code"]: r["target_weight"] / 100 for r in prev}

    codes = set(prev_weights) | set(curr_weights)
    return sum(abs(curr_weights.get(c, 0.0) - prev_weights.get(c, 0.0)) for c in codes) / 2


def _beta_alpha(track_returns: pd.Series, market_returns: pd.Series) -> tuple[float | None, float | None]:
    """②/④가 ③(지수) 대비 얼마나 위험을 더 졌는지(베타)와, 그걸 제외한 초과성과(알파)."""
    aligned = pd.concat([track_returns, market_returns], axis=1, join="inner").dropna()
    if len(aligned) < 3 or aligned.iloc[:, 1].var() == 0:
        return None, None
    cov = aligned.cov().iloc[0, 1]
    var_market = aligned.iloc[:, 1].var()
    beta = cov / var_market
    alpha = aligned.iloc[:, 0].mean() - beta * aligned.iloc[:, 1].mean()
    return float(beta), float(alpha)


def _top_cluster_weight(conn, track_id: str, week_id: str) -> float | None:
    """이번 주 목표비중에서 상관관계 클러스터 하나에 몰린 최대 비중(%). KRX 등록 업종 정보가
    부정확해(context-notes.md 참조) 실제 섹터 대신 스크리너의 상관관계 클러스터로 대체한다."""
    rows = conn.execute(
        """SELECT d.stock_code, d.target_weight, s.cluster_id
           FROM decisions d LEFT JOIN screener_output s
             ON d.stock_code = s.stock_code AND d.week_id = s.week_id
           WHERE d.track_id = ? AND d.week_id = ?""",
        (track_id, week_id),
    ).fetchall()
    if not rows:
        return None
    by_cluster: dict = {}
    for r in rows:
        key = r["cluster_id"] if r["cluster_id"] is not None else f"unclustered_{r['stock_code']}"
        by_cluster[key] = by_cluster.get(key, 0.0) + r["target_weight"]
    return max(by_cluster.values()) / 100  # target_weight가 0~100 스케일이라 다른 지표(0~1)와 맞춤


def compute_and_log(week_id: str, date: str):
    conn = get_connection()
    market_returns = _weekly_returns(conn, config.TRACK_INDEX)
    rebalanced_tracks = (config.TRACK_AI_BLIND, config.TRACK_EQUAL_WEIGHT)

    for track_id in (config.TRACK_MY_HOLDINGS, config.TRACK_AI_BLIND, config.TRACK_INDEX, config.TRACK_EQUAL_WEIGHT):
        weekly_returns = _weekly_returns(conn, track_id)
        weekly_return = float(weekly_returns.iloc[-1]) if len(weekly_returns) else None
        ann_vol = float(weekly_returns.std() * _ANNUALIZATION_FACTOR) if len(weekly_returns) >= 2 else None

        beta = alpha = turnover = top_cluster = None
        if track_id in rebalanced_tracks:
            beta, alpha = _beta_alpha(weekly_returns, market_returns)
            turnover = _turnover(conn, track_id, week_id)
            top_cluster = _top_cluster_weight(conn, track_id, week_id)

        conn.execute(
            """INSERT INTO risk_metrics
               (track_id, week_id, snapshot_date, weekly_return, ann_volatility, sharpe, sortino, mdd,
                hit_rate, turnover, beta, alpha, top_cluster_weight_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                track_id, week_id, date, weekly_return, ann_vol,
                _sharpe(weekly_returns), _sortino(weekly_returns), _mdd(weekly_returns),
                _hit_rate(weekly_returns), turnover, beta, alpha, top_cluster,
            ),
        )
    conn.commit()
    conn.close()
