# 정량 스크리너: 위생필터 -> 중복제거 -> 모멘텀 랭킹 -> 상관관계 클러스터 다양화 -> shortlist
import pandas as pd

import config
from data_collector import get_price_history


def _hygiene_filter(universe: pd.DataFrame) -> pd.DataFrame:
    df = universe.copy()
    for kw in config.EXCLUDE_DEPT_KEYWORDS:
        df = df[~df["Dept"].str.contains(kw, na=False)]
    df = df[df["Marcap"] >= config.MIN_MARKET_CAP]
    df = df[df["Amount"] >= config.MIN_TRADING_VALUE]
    return df


def _dedupe_common_preferred(df: pd.DataFrame) -> pd.DataFrame:
    """보통주/우선주 쌍: 코드 앞 5자리가 같은 종목군에서 시가총액이 가장 큰(보통주) 것만 남긴다."""
    df = df.copy()
    df["_code_prefix"] = df["Code"].str[:5]
    df = df.sort_values("Marcap", ascending=False)
    return df.drop_duplicates(subset="_code_prefix", keep="first").drop(columns="_code_prefix")


def build_shortlist(
    universe: pd.DataFrame, week_id: str, decision_date: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns: (shortlist_df, screener_output_df) - 후자는 후보군 전체 기록용.
    decision_date를 명시하면 모멘텀 이력 조회가 실행 시각이 아니라 그 날짜 기준으로 고정된다."""
    hygiene_ok = _hygiene_filter(universe)
    deduped = _dedupe_common_preferred(hygiene_ok)

    # 1차 컷: 유동성(거래대금) 기준으로 FIRST_PASS_TOP_N 까지만 실제 이력 조회 대상으로 축소
    liquidity_ranked = deduped.sort_values("Amount", ascending=False).head(config.FIRST_PASS_TOP_N).copy()

    price_series = {}
    for code in liquidity_ranked["Code"]:
        try:
            hist = get_price_history(code, config.CORR_LOOKBACK_DAYS, today=decision_date)
            if len(hist) >= config.CORR_LOOKBACK_DAYS * 0.6:
                price_series[code] = hist
        except Exception:
            continue

    momentum_score = {
        code: float(series.iloc[-1] / series.iloc[0] - 1) for code, series in price_series.items()
    }
    liquidity_ranked["momentum_score"] = liquidity_ranked["Code"].map(momentum_score)
    ranked = liquidity_ranked.dropna(subset=["momentum_score"]).copy()

    # 모멘텀 + 거래대금 순위를 절반씩 반영한 종합 점수
    ranked["_mom_rank"] = ranked["momentum_score"].rank(ascending=False)
    ranked["_liq_rank"] = ranked["Amount"].rank(ascending=False)
    ranked["combined_rank"] = ranked["_mom_rank"] + ranked["_liq_rank"]
    ranked = ranked.sort_values("combined_rank")

    # 상관관계 행렬 (수익률 기준)
    return_df = pd.DataFrame({code: s.pct_change().dropna().values for code, s in price_series.items() if code in ranked["Code"].values})

    cluster_id_map = {}
    cluster_counts = {}
    next_cluster_id = 0
    selected_codes = []

    for code in ranked["Code"]:
        if code not in return_df.columns:
            cluster_id_map[code] = None
            continue
        assigned_cluster = None
        for sel_code in selected_codes:
            if sel_code not in return_df.columns:
                continue
            corr = return_df[code].corr(return_df[sel_code])
            if corr is not None and corr >= config.CORR_THRESHOLD:
                assigned_cluster = cluster_id_map[sel_code]
                break
        if assigned_cluster is None:
            assigned_cluster = next_cluster_id
            next_cluster_id += 1
        cluster_id_map[code] = assigned_cluster
        cluster_counts.setdefault(assigned_cluster, 0)
        selected_codes.append(code)

    ranked["cluster_id"] = ranked["Code"].map(cluster_id_map)

    included_codes = []
    cluster_used = {}
    for _, row in ranked.iterrows():
        cid = row["cluster_id"]
        used = cluster_used.get(cid, 0)
        if used < config.MAX_PER_CLUSTER and len(included_codes) < config.SHORTLIST_SIZE:
            included_codes.append(row["Code"])
            cluster_used[cid] = used + 1

    ranked["rank"] = range(1, len(ranked) + 1)
    ranked["included_in_shortlist"] = ranked["Code"].isin(included_codes)
    ranked["exclude_reason"] = ranked.apply(
        lambda r: None if r["included_in_shortlist"] else (
            "cluster_cap" if r["cluster_id"] is not None else "shortlist_size_cut"
        ),
        axis=1,
    )
    ranked["week_id"] = week_id

    shortlist = ranked[ranked["included_in_shortlist"]].copy()
    return shortlist, ranked


if __name__ == "__main__":
    from data_collector import get_universe_snapshot

    universe = get_universe_snapshot()
    shortlist, screener_output = build_shortlist(universe, week_id="test")
    print(f"유니버스 {len(universe)} -> shortlist {len(shortlist)}개")
    print(shortlist[["Code", "Name", "momentum_score", "cluster_id"]].to_string())
