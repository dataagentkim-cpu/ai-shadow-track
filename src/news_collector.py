# 네이버 뉴스 검색 API로 shortlist 종목 + 시장 전반 뉴스만 수집 (전체 종목 뉴스는 수집하지 않음)
import re
import time

import requests

import config

_API_URL = "https://openapi.naver.com/v1/search/news.json"
_REQUEST_INTERVAL_SEC = 0.2  # 연속 호출 시 네이버 순간 rate limit(429) 방지


def _strip_html(text: str) -> str:
    return re.sub(r"<.*?>", "", text)


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


def collect_shortlist_news(stock_names: list[str]) -> dict[str, list[dict]]:
    news_by_stock = {}
    for name in stock_names:
        try:
            news_by_stock[name] = search_news(name, display=config.NEWS_PER_STOCK)
        except Exception as e:
            news_by_stock[name] = []
            print(f"[news] {name} 수집 실패: {e}")
        time.sleep(_REQUEST_INTERVAL_SEC)
    return news_by_stock


def collect_market_news() -> list[dict]:
    return search_news("코스피 코스닥 증시", display=10)


if __name__ == "__main__":
    print(collect_market_news()[:2])
