# 스크리너/LLM 판단/경로 등 프로젝트 전역 설정값
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "shadow_track.db"

# --- 1차 정량 필터 ---
MIN_MARKET_CAP = 50_000_000_000      # 시가총액 하한 500억원
MIN_TRADING_VALUE = 500_000_000      # 최근 거래대금 하한 5억원
EXCLUDE_DEPT_KEYWORDS = ["관리종목", "SPAC", "투자주의환기종목"]  # FDR Dept 컬럼 기준 위생 제외
FIRST_PASS_TOP_N = 150               # 모멘텀/밸류 랭킹 상위 N개까지만 2~3단계로 넘김

# --- 클러스터 다양화 (상관관계 기반) ---
# KRX 업종 등록 정보(Industry 컬럼)가 실제 업종과 어긋나는 경우가 많아(예: 삼성전자가
# "통신 및 방송 장비 제조업"으로 등록) 업종 코드 대신 최근 수익률 상관관계로 클러스터링한다.
CORR_LOOKBACK_DAYS = 90
CORR_THRESHOLD = 0.75
MAX_PER_CLUSTER = 3                  # 상관 클러스터당 최대 편입 종목 수

# --- shortlist / LLM ---
SHORTLIST_SIZE = 40
TARGET_STOCK_MIN = 8
TARGET_STOCK_MAX = 12
LLM_MODEL = "claude-sonnet-5"

# --- 뉴스 ---
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NEWS_PER_STOCK = 5

# --- 트랙 ID ---
TRACK_MY_HOLDINGS = "my_holdings"
TRACK_AI_BLIND = "ai_blind"
TRACK_INDEX = "index"
