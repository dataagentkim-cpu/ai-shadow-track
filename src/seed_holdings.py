# 브리프에 명시된 실제 보유 종목을 오늘 시세로 재평가해 holdings 테이블에 1회 시딩
from datetime import datetime

import FinanceDataReader as fdr

from db import get_connection, init_db

# 종목명 → 보유 수량 (브리프 "벤치마크 ① 실제 보유" 표. 수량은 고정값, 가격은 시딩 시점 시세로 재계산)
MY_HOLDINGS = {
    "삼성전자": 70,
    "한화오션": 132,
    "삼성중공업": 413,
    "이오테크닉스": 25,
    "HD한국조선해양": 8,
    "에이프릴바이오": 100,
    "지투지바이오": 70,
    "JYP Ent.": 36,
    "솔루엠": 100,
}


def seed(today: str | None = None):
    today = today or datetime.now().strftime("%Y-%m-%d")

    listing = fdr.StockListing("KRX")
    name_to_row = {row.Name: row for row in listing.itertuples()}

    rows = []
    for name, qty in MY_HOLDINGS.items():
        if name not in name_to_row:
            raise ValueError(f"종목명을 찾을 수 없음: {name} (FDR 상장목록 기준)")
        row = name_to_row[name]
        price = int(row.Close)
        value = price * qty
        rows.append({"code": row.Code, "name": name, "qty": qty, "price": price, "value": value})

    total_value = sum(r["value"] for r in rows)

    conn = get_connection()
    conn.execute("DELETE FROM holdings")  # 시작 스냅샷은 항상 1개만 유지
    for r in rows:
        weight = r["value"] / total_value
        conn.execute(
            """INSERT INTO holdings
               (stock_code, stock_name, quantity, snapshot_price, snapshot_value, snapshot_weight, snapshot_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r["code"], r["name"], r["qty"], r["price"], r["value"], weight, today),
        )
    conn.commit()
    conn.close()

    print(f"holdings 시딩 완료 ({today}), 총 평가금액: {total_value:,}원")
    for r in sorted(rows, key=lambda x: -x["value"]):
        print(f"  {r['name']}({r['code']}): {r['qty']}주 x {r['price']:,}원 = {r['value']:,}원 ({r['value']/total_value:.1%})")


if __name__ == "__main__":
    init_db()
    seed()
