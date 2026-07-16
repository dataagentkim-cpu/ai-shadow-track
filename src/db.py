# SQLite 스키마 정의 및 연결 헬퍼
import sqlite3

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    snapshot_price INTEGER NOT NULL,
    snapshot_value INTEGER NOT NULL,
    snapshot_weight REAL NOT NULL,
    snapshot_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    week_id TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    action TEXT NOT NULL,
    target_weight REAL NOT NULL,
    rationale TEXT NOT NULL,
    conviction TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    week_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    portfolio_value REAL NOT NULL,
    return_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    kospi_index REAL,
    kosdaq_index REAL,
    total_universe_count INTEGER
);

CREATE TABLE IF NOT EXISTS screener_output (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    market_cap INTEGER,
    trading_value INTEGER,
    momentum_score REAL,
    cluster_id INTEGER,
    rank INTEGER,
    included_in_shortlist INTEGER NOT NULL,
    exclude_reason TEXT
);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")
