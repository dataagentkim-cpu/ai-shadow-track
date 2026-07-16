# 코스피+코스닥 전 종목 및 지수의 주간 스냅샷을 FinanceDataReader로 수집
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd


def get_universe_snapshot() -> pd.DataFrame:
    """코스피+코스닥 전 종목 스냅샷 (가격/거래량/시총/업종 등록정보 포함)"""
    listing = fdr.StockListing("KRX")
    listing = listing[listing["MarketId"].isin(["STK", "KSQ"])].copy()

    desc = fdr.StockListing("KRX-DESC")[["Code", "Sector", "Industry"]]
    df = listing.merge(desc, on="Code", how="left")
    return df


def get_index_levels(today: str | None = None) -> dict:
    today = today or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    kospi = fdr.DataReader("KS11", start, today)
    kosdaq = fdr.DataReader("KQ11", start, today)
    return {
        "kospi_index": float(kospi["Close"].iloc[-1]),
        "kosdaq_index": float(kosdaq["Close"].iloc[-1]),
    }


def get_price_history(code: str, lookback_days: int, today: str | None = None) -> pd.Series:
    """종목의 최근 lookback_days 거래일 종가 시계열 (상관관계 클러스터링용)"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=int(lookback_days * 1.6))).strftime("%Y-%m-%d")
    hist = fdr.DataReader(code, start, today)
    return hist["Close"].tail(lookback_days)


if __name__ == "__main__":
    df = get_universe_snapshot()
    print(f"유니버스 종목 수: {len(df)}")
    print(get_index_levels())
