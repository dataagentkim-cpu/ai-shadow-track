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
    conviction TEXT NOT NULL,
    weekly_perspective TEXT
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
    exclude_reason TEXT,
    per REAL,
    pbr REAL,
    roe REAL,
    debt_ratio REAL,
    op_margin REAL
);

CREATE TABLE IF NOT EXISTS risk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    week_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    weekly_return REAL,
    ann_volatility REAL,
    sharpe REAL,
    sortino REAL,
    mdd REAL,
    hit_rate REAL,
    turnover REAL,
    beta REAL,
    alpha REAL,
    top_cluster_weight_pct REAL
);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """CREATE TABLE IF NOT EXISTS는 기존 테이블에 새 컬럼을 추가해주지 않으므로,
    이미 있는 DB에 대해서는 여기서 컬럼 추가를 따로 챙긴다."""
    decisions_cols = [r["name"] for r in conn.execute("PRAGMA table_info(decisions)")]
    if "weekly_perspective" not in decisions_cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN weekly_perspective TEXT")

    screener_cols = [r["name"] for r in conn.execute("PRAGMA table_info(screener_output)")]
    for col in ("per", "pbr", "roe", "debt_ratio", "op_margin"):
        if col not in screener_cols:
            conn.execute(f"ALTER TABLE screener_output ADD COLUMN {col} REAL")


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")
