# 코스피+코스닥 전 종목 및 지수의 주간 스냅샷을 FinanceDataReader로 수집
from datetime import datetime, time as dtime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import pytz

KST = pytz.timezone("Asia/Seoul")


def get_last_completed_trading_day(as_of: str | None = None) -> str:
    """as_of(기본 오늘, KST) 이전에 마지막으로 거래가 있었던 날짜(YYYY-MM-DD)를 반환한다.
    당일 데이터는 장중이라도 절대 포함하지 않는다. 코스피 지수(KS11)에 실제로 데이터가 있는
    날만 거래일로 취급하므로 주말/공휴일이 며칠 겹쳐도 자동으로 건너뛴다."""
    as_of = as_of or datetime.now(KST).strftime("%Y-%m-%d")
    as_of_dt = datetime.strptime(as_of, "%Y-%m-%d")
    start = (as_of_dt - timedelta(days=21)).strftime("%Y-%m-%d")
    end_exclusive = (as_of_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    hist = fdr.DataReader("KS11", start, end_exclusive)
    if hist.empty:
        raise RuntimeError(f"{start}~{end_exclusive} 사이 거래일을 찾지 못함 (연휴가 3주 이상 이어졌을 가능성)")
    return hist.index[-1].strftime("%Y-%m-%d")


def assert_before_market_open(now: datetime | None = None):
    """판단 단계는 반드시 장 시작(09:00 KST) 전에 실행해야 한다 — 그래야 실행 시점의 라이브
    스냅샷이 '직전 완료된 거래일 종가'와 정확히 일치한다는 가정이 깨지지 않는다."""
    now = now or datetime.now(KST)
    if now.time() >= dtime(9, 0):
        raise RuntimeError(f"장 시작 이후({now.strftime('%H:%M')} KST)에는 판단 단계를 실행할 수 없음")


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
