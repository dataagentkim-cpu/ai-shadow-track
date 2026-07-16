# DART(전자공시시스템) OpenAPI 래퍼 - 종목별 현금배당수익률 조회 (총수익 계산용)
import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from functools import lru_cache

import requests

import config

_DART_BASE = "https://opendart.fss.or.kr/api"


@lru_cache(maxsize=1)
def _corp_code_map() -> dict:
    """종목코드 -> DART corp_code 매핑. 전체 상장사 목록이라 프로세스당 1회만 받는다."""
    resp = requests.get(f"{_DART_BASE}/corpCode.xml", params={"crtfc_key": config.DART_API_KEY}, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("CORPCODE.xml") as f:
            root = ET.parse(f).getroot()

    mapping = {}
    for item in root.findall("list"):
        stock_code = item.findtext("stock_code", "").strip()
        if stock_code:
            mapping[stock_code] = item.findtext("corp_code", "").strip()
    return mapping


def _safe_fiscal_year(as_of: str | None = None) -> str:
    """판단 시점에 이미 공시가 끝났을 게 확실한 사업연도를 보수적으로 고른다 (PIT 안전).
    사업보고서 법정 제출기한이 결산 후 90일(3월 말)이라, 4월 이전엔 전전년도까지 내려간다."""
    as_of_dt = datetime.strptime(as_of, "%Y-%m-%d") if as_of else datetime.now()
    year_back = 1 if as_of_dt.month >= 4 else 2
    return str(as_of_dt.year - year_back)


@lru_cache(maxsize=4096)
def get_dividend_yield_pct(stock_code: str, as_of: str | None = None) -> float:
    """종목의 현금배당수익률(%, 보통주 기준)을 DART 사업보고서 공시에서 가져온다.
    공시가 없거나 조회 실패 시 0.0 (무배당으로 취급). 같은 (종목, 기준일)은 프로세스
    내에서 재조회하지 않도록 캐싱 — 한 주기 안에서 같은 종목이 여러 트랙에 걸쳐 있어도
    DART를 한 번만 호출한다."""
    corp_code = _corp_code_map().get(stock_code)
    if not corp_code:
        return 0.0

    try:
        resp = requests.get(
            f"{_DART_BASE}/alotMatter.json",
            params={
                "crtfc_key": config.DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": _safe_fiscal_year(as_of),
                "reprt_code": "11011",  # 사업보고서
            },
            timeout=15,
        )
        data = resp.json()
    except Exception:
        return 0.0

    if data.get("status") != "000":
        return 0.0

    for item in data.get("list", []):
        if item.get("se") == "현금배당수익률(%)" and item.get("stock_knd") == "보통주":
            try:
                return float(item["thstrm"].replace(",", ""))
            except (ValueError, KeyError, AttributeError):
                return 0.0
    return 0.0


if __name__ == "__main__":
    print("삼성전자 배당수익률:", get_dividend_yield_pct("005930"), "%")
