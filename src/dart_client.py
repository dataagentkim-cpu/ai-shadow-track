# DART(전자공시시스템) OpenAPI 래퍼 - 종목별 현금배당수익률 + 재무제표(ROE/부채비율/영업이익률/PER/PBR) 조회
import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from functools import lru_cache

import requests

import config

_DART_BASE = "https://opendart.fss.or.kr/api"

# dart-ma-screener 프로젝트의 계정명 매핑 패턴을 그대로 재사용
_REVENUE_NAMES = {"매출액", "수익(매출액)", "영업수익", "매출", "순매출액", "영업수익(매출액)", "I. 매출액"}
_OP_INCOME_NAMES = {"영업이익", "영업이익(손실)", "영업손익"}
_NET_INCOME_NAMES = {"당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)"}
_ASSET_NAMES = {"자산총계"}
_LIAB_NAMES = {"부채총계"}
_EQUITY_NAMES = {"자본총계"}

_FIN_BATCH_SIZE = 80  # DART 다중회사 API 최대 100 - 여유를 두고 80씩 (dart-ma-screener와 동일 관례)


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


def _parse_amount(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _first_match(fs_data: dict, names: set) -> float | None:
    for name in names:
        if name in fs_data:
            return fs_data[name]
    return None


def _fetch_financial_batch(corp_codes: list[str], bsns_year: str) -> dict:
    """corp_code 최대 _FIN_BATCH_SIZE개를 한 번에 조회해 corp_code -> 재무 지표 dict로 반환."""
    try:
        resp = requests.get(
            f"{_DART_BASE}/fnlttMultiAcnt.json",
            params={
                "crtfc_key": config.DART_API_KEY,
                "corp_code": ",".join(corp_codes),
                "bsns_year": bsns_year,
                "reprt_code": "11011",
            },
            timeout=30,
        )
        data = resp.json()
    except Exception:
        return {}

    if data.get("status") != "000":
        return {}

    # corp_code -> fs_div(CFS/OFS) -> {계정명: 금액}
    raw: dict[str, dict[str, dict[str, float]]] = {}
    for item in data.get("list", []):
        amount = _parse_amount(item.get("thstrm_amount"))
        if amount is None:
            continue
        raw.setdefault(item["corp_code"], {}).setdefault(item["fs_div"], {})[item["account_nm"]] = amount

    result = {}
    for corp_code, by_fs in raw.items():
        fs_data = by_fs.get("CFS") or by_fs.get("OFS")  # 연결재무제표 우선, 없으면 별도
        if not fs_data:
            continue
        equity = _first_match(fs_data, _EQUITY_NAMES)
        if not equity:
            continue
        revenue = _first_match(fs_data, _REVENUE_NAMES)
        op_income = _first_match(fs_data, _OP_INCOME_NAMES)
        net_income = _first_match(fs_data, _NET_INCOME_NAMES)
        liabilities = _first_match(fs_data, _LIAB_NAMES)
        result[corp_code] = {
            "revenue": revenue,
            "op_income": op_income,
            "net_income": net_income,
            "assets": _first_match(fs_data, _ASSET_NAMES),
            "liabilities": liabilities,
            "equity": equity,
            "roe": (net_income / equity) if net_income is not None else None,
            "debt_ratio": (liabilities / equity) if liabilities is not None else None,
            "op_margin": (op_income / revenue) if (op_income is not None and revenue) else None,
        }
    return result


def get_financial_metrics(stock_codes: list[str], as_of: str | None = None) -> dict[str, dict]:
    """종목코드 리스트에 대해 배치로 ROE·부채비율·영업이익률 등을 가져온다 (PIT 안전한
    사업연도만 조회). PER/PBR은 여기서 계산하지 않는다 - 그 시점 시가·발행주식수와 결합해야
    하므로 compute_valuation_ratios()에서 별도로 계산한다. 공시가 없는 종목은 결과에서 생략된다."""
    fiscal_year = _safe_fiscal_year(as_of)
    corp_map = _corp_code_map()
    code_to_corp = {code: corp_map[code] for code in stock_codes if code in corp_map}

    by_corp: dict[str, dict] = {}
    corp_codes = list(code_to_corp.values())
    for i in range(0, len(corp_codes), _FIN_BATCH_SIZE):
        by_corp.update(_fetch_financial_batch(corp_codes[i : i + _FIN_BATCH_SIZE], fiscal_year))

    return {code: by_corp[corp] for code, corp in code_to_corp.items() if corp in by_corp}


def compute_valuation_ratios(financials: dict, price: float, shares_outstanding: float) -> dict:
    """재무제표 값(get_financial_metrics 결과 1건) + 그 시점 시가·발행주식수를 결합해 PER/PBR 계산."""
    net_income = financials.get("net_income")
    equity = financials.get("equity")
    eps = (net_income / shares_outstanding) if net_income is not None and shares_outstanding else None
    bps = (equity / shares_outstanding) if equity is not None and shares_outstanding else None
    per = (price / eps) if eps and eps > 0 else None
    pbr = (price / bps) if bps and bps > 0 else None
    return {"eps": eps, "bps": bps, "per": per, "pbr": pbr}


if __name__ == "__main__":
    print("삼성전자 배당수익률:", get_dividend_yield_pct("005930"), "%")
    fin = get_financial_metrics(["005930", "000660"])
    for code, f in fin.items():
        print(code, f)
