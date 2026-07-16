# AI 투자 판단 섀도우 트랙

국내주식(코스피+코스닥) 대상, AI가 매주 자기 자신의 지난주 포트폴리오를 이어받아 확대/유지/축소/매도로
조정하는 stateful 판단을 로그로 쌓고, 내 실제 보유·지수·동일가중 baseline과 **4파전**으로 비교하는
개인용 섀도우 트랙. **기준 설계 문서는 `SPEC.md`** (원본 `shadow-track-build-brief.md`의 확장판 —
코드와 문서가 어긋나면 SPEC.md가 우선, 바꾸려면 먼저 확인받을 것).

**진행 상태**: SPEC.md는 AI 트랙을 ②a가치/②b모멘텀/②c퀄리티/②d자유형 4렌즈 병렬로 정의하지만,
가치·퀄리티 렌즈가 필요로 하는 실제 재무 지표(PER/PBR/ROE/부채비율) 연결을 먼저 마치고 나서 4렌즈로
확장하기로 순서를 바꿨다 (`dart_client.py`의 재무지표 조회는 완료·검증됨, 4렌즈 LLM 판단 확장은 보류 중 —
자세한 건 `context-notes.md` "SPEC.md 도입 + 4렌즈 확장" 항목 참조). 아래 설명은 **현재 배포된 단일 ②
트랙 기준**이다.

**4파전**: ① 내 실제 보유(고정) / ② AI 판단(stateful) / ③ 코스피·코스닥 지수 / ④ 그 주 스크리너
shortlist를 LLM 판단 없이 동일가중 보유하는 baseline. **핵심 질문은 ②가 ④를 이기는가** — 못 이기면
"LLM이 값을 못 하는 것"이고, 스크리너가 후보군을 좁혀준 것 이상의 부가가치를 냈다고 볼 수 없다는 뜻이다.

**AI 판단 방식**: 매주 shortlist·뉴스와 함께 **AI 자신의 지난주 목표 포트폴리오**(매수가·수익률은 비공개)를
참고해 "오늘 이 가격에 새로 산다면 살 것인가"를 기준으로 재평가한다 — 앵커링·처분효과를 막기 위해서다.
"전량 유지(무거래)"도 완전히 정상적인 선택지다. **내 실제 보유(①)는 이 판단 과정에 절대 들어가지 않는다**
(블라인드 유지, `run_weekly._get_previous_ai_portfolio()`가 `track_id='ai_blind'`로 하드 필터링).

**수익률은 배당 포함 총수익 기준**이다 (가격변동 + 세후 배당수익률 안분). 개별 종목은 DART 공시의
현금배당수익률을, 지수(③)는 정확한 총수익지수 데이터가 없어 통상적인 평균 배당수익률 근사치를 쓴다.

## 시작하기

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 아래 "필요한 자격증명" 채우기
```

```bash
cd src
python3 seed_holdings.py   # 최초 1회: 내 실제 보유를 오늘 시세로 시딩
python3 run_weekly.py      # 주간 사이클 1회 실행 (스냅샷→스크리너→뉴스→LLM판단→벤치마크)
python3 telegram_bot.py    # 텔레그램 Q&A 봇 상시 실행 (별도 터미널/프로세스)
```

## 필요한 자격증명 (.env, 발급 완료)
- `ANTHROPIC_API_KEY` — 다른 로컬 프로젝트(morning_brief_bot 등)에 있던 기존 키 재사용
- `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` — developers.naver.com에서 발급
- `TELEGRAM_BOT_TOKEN` — BotFather로 `@AI_Shadow_Track_bot` 생성해 발급
- `TELEGRAM_ALLOWED_CHAT_ID` — 본인 채팅에서만 봇이 응답하도록 제한
- `DART_API_KEY` — 다른 로컬 프로젝트(dart-ma-screener)에 있던 기존 키 재사용, 배당 공시 + 재무제표(ROE/부채비율/영업이익률/PER/PBR) 조회용

## 텔레그램 명령어
- `/performance` — 4파전(내 보유/AI/지수/동일가중) 최신 수익률
- `/latest` — 이번 주 AI 판단 전체
- `/history` — 최근 수익률 추이
- `/why 종목명` — 특정 종목의 최근 판단 이유
- `/holdings` — 내 실제 보유 스냅샷
- `/alpha` — AI(②)가 동일가중 baseline(④)을 이겼는지, 주간·누적 스프레드
- `/risk` — 트랙별 Sharpe/Sortino/MDD/적중률/회전율/베타/알파/클러스터 집중도

## 배포 (AWS EC2)
`running-coach-bot`이 떠 있는 기존 EC2(t2.micro, ubuntu)에 두 번째 systemd 서비스로 공존한다.
주간 사이클은 별도 크론이 아니라 **봇 프로세스 안의 JobQueue**로 실행되고, 완료되면 결과 요약을 채팅으로 push한다 — running-coach-bot의 `jq.run_daily(weekly_report, ...)` 패턴과 동일. 단, **판단과 체결을 시점을 분리**해 look-ahead 편향을 없앴다.
- `decision_job` (화요일 07:00 KST, 장 시작 전) — `run_weekly.run_decision()` 실행, 판단만 로그
  - 판단 기준일은 실행 시각의 "latest"가 아니라 `data_collector.get_last_completed_trading_day()`로 **직전 완료된 거래일**을 명시적으로 고정한다 (코스피 지수에 실제 데이터가 있는 날만 거래일로 취급 — 공휴일이 며칠 겹쳐도 자동으로 건너뜀). `data_collector.assert_before_market_open()`이 09:00 KST 이후 실행을 아예 막아서, 라이브 스냅샷이 그 거래일 종가와 정확히 일치한다는 가정을 보장한다.
- `execution_job` (화요일 09:05 KST, 장 시작 후) — `run_weekly.run_execution()` 실행, 실제 당일 시가 기준으로 체결/벤치마크 확정
  - `config.EXECUTION_SLIPPAGE_PCT` (0.3%, 진입·청산 양쪽에 불리한 방향으로), `config.BROKER_FEE_PCT` (0.015%, 매수/매도 각각), `config.TRANSACTION_TAX_PCT` (0.20%, 매도 시만 — 2026년 기준 코스피 0.05%+농특세 0.15%, 코스닥 0.20%로 두 시장 모두 동일해 단일값 사용)
  - **거래비용은 지난주 대비 실제 비중 변화(델타)에만 부과** — 유지되는 포지션은 비용 0, 새로 편입/확대된 만큼만 매수 비용, 축소/매도된 만큼만 매도 비용(`benchmark._rebalance_cost_pct`). 매주 전량 재구성하던 이전 방식에서 실제 트레이더처럼 부분 리밸런싱하는 방식으로 전환됨
  - 내 보유(①)·AI(②)·지수(③)·동일가중 baseline(④) 네 트랙 모두 `benchmark._get_open_price()` 하나로 통일해 같은 화요일 시가 기준에서 출발한다. 그 날짜 데이터가 없으면(장 시작 전 오호출 등) 조용히 넘어가지 않고 바로 에러를 내고, 보유 중 거래정지/상장폐지가 감지되면 `_get_open_price_safe()`가 마지막 시가로 동결 청산 처리한다.
  - ④는 그 주 스크리너 shortlist 전체를 LLM 판단 없이 동일가중으로 보유하는 baseline — ②(LLM)와 완전히 같은 체결/비용 규칙을 공유해서(`benchmark._snapshot_rebalanced_track`) ②−④ 스프레드가 순수하게 "LLM 판단의 기여도"만 반영하게 했다.
  - **`run_weekly.run()`(CLI 수동 실행)은 판단만 하고 체결/벤치마크는 절대 자동으로 이어서 하지 않는다** — look-ahead 편향 방지를 위해 판단·체결 사이 시간 간격이 반드시 있어야 하므로, 실수로 성과 기록이 오염되는 걸 막기 위한 안전장치다. 체결은 장 시작 후 `run_execution()`을 별도로 호출할 것.

(`JobQueue.run_daily`의 `days`는 0=일요일 ~ 6=토요일 순서라 화요일은 `2`다 — Python 표준 `weekday()`와 달라서 처음에 잘못 넣었던 부분)

- 서버 경로: `/home/ubuntu/ai-shadow-track` (이 GitHub 레포를 `git clone`한 것, 자체 `venv/`)
- systemd: `/etc/systemd/system/shadowtrack.service` (`runcoach.service`와 동일 구조 — `User=ubuntu`, `EnvironmentFile=.env`, `Restart=always`)
- `.github/workflows/deploy.yml` — `main`에 push되면 EC2로 SSH 접속해 `git pull` + `pip install` + `systemctl restart shadowtrack` (repo secrets: `EC2_HOST`, `EC2_SSH_KEY`)

**중요**: `data/shadow_track.db`에는 실제 보유 종목/수량/평가금액이 담겨 있어서 `.gitignore`로 git에서 완전히 제외했다 — 레포는 public이지만 db는 EC2 서버 로컬에만 존재한다. 로컬에서 다시 받아보려면 서버에서 `scp`로 가져올 것.

## PIT(Point-in-Time) 무결성 · 상장폐지 처리
- **뉴스**: `news_collector.py`가 뉴스 게시일시(`pub_date`)를 판단 시각(직전 거래일 다음날 07:00 KST) 기준으로 필터링 — 판단 시점에 아직 존재하지 않았던 기사는 배제.
- **재무 공시**: `dart_client._safe_fiscal_year()`가 사업보고서 법정 제출기한(3월 말)을 감안해 아직 공시 안 됐을 연도는 건너뛴다 — 배당수익률·재무제표(ROE/부채비율/영업이익률/PER/PBR) 조회 둘 다 이 안전장치를 공유한다. 단, 재무제표 값은 현재 `screener_output`에 기록만 될 뿐 LLM 판단 인풋에는 아직 연결 안 됨 (SPEC.md 4렌즈 확장 때 가치·퀄리티 렌즈에 연결 예정).
- **거래정지/상장폐지**: `benchmark._get_open_price_safe()`가 해당 날짜 데이터가 없으면 최근 60일 내 마지막 시가로 동결 청산 처리한다 (60일도 데이터가 없으면 에러).
- **유니버스 생존편향**: 매주 `screener_output` 테이블에 그 주 전체 후보군(포함/제외 사유 포함)을 기록하므로, 종목의 진입·이탈 이력은 이 테이블을 주차별로 비교해 추적할 수 있다 (별도 이력 테이블은 안 만듦 — 이미 있는 데이터로 유도 가능해서).

## 구조
- `src/config.py` — 스크리너 임계값/모델명/거래비용/배당 상수 등 전역 설정
- `src/db.py` — SQLite 스키마 (holdings/decisions/snapshots/universe_snapshot/screener_output/risk_metrics)
- `src/seed_holdings.py` — 실제 보유 시딩 (블라인드, LLM 프롬프트에 미투입)
- `src/data_collector.py` — 코스피+코스닥 유니버스/지수 스냅샷, 직전 완료 거래일 계산
- `src/screener.py` — 위생필터 → 중복제거 → 모멘텀랭킹 → 상관관계 클러스터 다양화
- `src/news_collector.py` — shortlist·시장 전반 뉴스만 수집 (PIT 필터 포함)
- `src/dart_client.py` — DART 공시에서 종목별 현금배당수익률 + 재무제표(ROE/부채비율/영업이익률/PER/PBR) 조회
- `src/llm_judge.py` — stateful 블라인드 LLM 판단
- `src/benchmark.py` — 4파전 총수익 스냅샷 (배당·거래비용·PIT 가격 전부 반영)
- `src/risk_metrics.py` — 트랙별 위험조정 지표 계산
- `src/run_weekly.py` — 위 전체를 묶는 주간 오케스트레이터
- `src/telegram_bot.py` — 결과 질의응답 봇

세부 설계 결정과 배경은 `context-notes.md`, 남은 작업은 `checklist.md` 참조.
