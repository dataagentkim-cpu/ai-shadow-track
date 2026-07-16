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
# 주 단위 판단 변화가 무작위가 아니라 렌즈·시장에서 나오도록 낮게 고정 (SPEC.md "LLM 판단 규칙")
LLM_TEMPERATURE = 0.25

# --- 뉴스 ---
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NEWS_PER_STOCK = 5

# --- 배당 (DART) ---
DART_API_KEY = os.getenv("DART_API_KEY")
DIVIDEND_TAX_PCT = 0.154  # 배당소득세 15.4% (지방소득세 포함), 현금배당 모델링 시 세후로 반영
# 지수(코스피/코스닥) 총수익 근사치: 개별 종목처럼 DART 공시로 정확히 계산할 수 없어(지수
# 자체의 배당재투자 데이터 소스가 없음) 통상 언급되는 평균 배당수익률을 고정값으로 근사한다.
KOSPI_DIVIDEND_YIELD_APPROX_PCT = 2.0
KOSDAQ_DIVIDEND_YIELD_APPROX_PCT = 1.0

# --- 트랙 ID ---
TRACK_MY_HOLDINGS = "my_holdings"
TRACK_AI_BLIND = "ai_blind"  # 구버전 단일 AI 트랙 - SPEC.md 4렌즈 확장 이후로는 신규 기록 안 함 (과거 로그만 남음)
TRACK_INDEX = "index"
TRACK_EQUAL_WEIGHT = "equal_weight"  # ④ 그 주 shortlist를 LLM 판단 없이 동일가중 보유 (LLM 기여도 격리용)

# ②a~②d: SPEC.md "투자 렌즈 정의" 4렌즈 병렬. 각자 독립 시스템 프롬프트 + 독립 stateful 포트.
TRACK_VALUE = "value_ai"
TRACK_MOMENTUM = "momentum_ai"
TRACK_QUALITY = "quality_ai"
TRACK_FREE = "free_ai"
LENS_TRACKS = [TRACK_VALUE, TRACK_MOMENTUM, TRACK_QUALITY, TRACK_FREE]
LENS_BY_TRACK = {TRACK_VALUE: "value", TRACK_MOMENTUM: "momentum", TRACK_QUALITY: "quality", TRACK_FREE: "free"}

# --- 체결(실행) ---
# AI 트랙은 매주 완전 리밸런싱을 가정하므로, 판단(직전 완료 거래일 종가+뉴스)과 체결(다음
# 거래일 시가) 시점을 분리해 look-ahead 편향을 없앤다. 슬리피지는 진입/청산 양쪽에 불리한
# 방향으로 적용한다 (0.2~0.5% 범위의 중간값).
EXECUTION_SLIPPAGE_PCT = 0.003
# 매매수수료 (매수/매도 각각 부과, 온라인 증권사 기준 근사치)
BROKER_FEE_PCT = 0.00015
# 증권거래세 (2026년 기준, 매도 시 1회만 부과): 코스피 0.05%+농특세 0.15%=0.20%, 코스닥 0.20% —
# 두 시장 모두 결과적으로 0.20%로 동일해 종목별 시장 구분 없이 단일값으로 사용
TRANSACTION_TAX_PCT = 0.0020
