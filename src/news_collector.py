# 네이버 뉴스 검색 API로 shortlist 종목 + 시장 전반 뉴스만 수집 (전체 종목 뉴스는 수집하지 않음)
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

import config

_API_URL = "https://openapi.naver.com/v1/search/news.json"
_REQUEST_INTERVAL_SEC = 0.2  # 연속 호출 시 네이버 순간 rate limit(429) 방지


def _strip_html(text: str) -> str:
    return re.sub(r"<.*?>", "", text)


def _decision_cutoff(decision_date: str) -> datetime:
    """판단 시각(직전 거래일 다음날 07:00 KST — decision_job이 실제로 도는 시각) 이후에
    나온 뉴스는 판단 시점엔 아직 존재하지 않았던 정보이므로 배제한다."""
    d = datetime.strptime(decision_date, "%Y-%m-%d")
    return d + timedelta(days=1, hours=7)


def _is_before_cutoff(pub_date_str: str, cutoff: datetime) -> bool:
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        if pub_dt.tzinfo is not None:
            pub_dt = pub_dt.replace(tzinfo=None)
        return pub_dt <= cutoff
    except Exception:
        return False  # 날짜 파싱 실패 시 PIT 안전을 위해 보수적으로 제외


def search_news(query: str, display: int = 5) -> list[dict]:
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        raise RuntimeError(
            "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정. "
            "https://developers.naver.com/apps 에서 애플리케이션 등록 후 .env에 추가하세요."
        )
    headers = {
        "X-Naver-Client-Id": config.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}

    for attempt in range(3):
        resp = requests.get(_API_URL, headers=headers, params=params, timeout=10)
        if resp.status_code == 429:
            time.sleep(1.0 * (attempt + 1))
            continue
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": _strip_html(item["title"]),
                "description": _strip_html(item["description"]),
                "pub_date": item["pubDate"],
            }
            for item in items
        ]
    resp.raise_for_status()


def collect_shortlist_news(stock_names: list[str], decision_date: str | None = None) -> dict[str, list[dict]]:
    cutoff = _decision_cutoff(decision_date) if decision_date else None
    news_by_stock = {}
    for name in stock_names:
        try:
            items = search_news(name, display=config.NEWS_PER_STOCK)
            if cutoff:
                items = [n for n in items if _is_before_cutoff(n["pub_date"], cutoff)]
            news_by_stock[name] = items
        except Exception as e:
            news_by_stock[name] = []
            print(f"[news] {name} 수집 실패: {e}")
        time.sleep(_REQUEST_INTERVAL_SEC)
    return news_by_stock


def collect_market_news(decision_date: str | None = None) -> list[dict]:
    items = search_news("코스피 코스닥 증시", display=10)
    if decision_date:
        cutoff = _decision_cutoff(decision_date)
        items = [n for n in items if _is_before_cutoff(n["pub_date"], cutoff)]
    return items


if __name__ == "__main__":
    print(collect_market_news()[:2])
