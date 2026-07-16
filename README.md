# AI 투자 판단 섀도우 트랙

국내주식(코스피+코스닥) 대상, AI 블라인드 포트폴리오 판단을 매주 로그로 쌓고
내 실제 보유·지수와 3파전으로 비교하는 개인용 섀도우 트랙. 기획 원본은 `shadow-track-build-brief.md`.

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

## 텔레그램 명령어
- `/performance` — 3파전(내 보유/AI 블라인드/지수) 최신 수익률
- `/latest` — 이번 주 AI 블라인드 판단 전체
- `/history` — 최근 수익률 추이
- `/why 종목명` — 특정 종목의 최근 판단 이유
- `/holdings` — 내 실제 보유 스냅샷

## 배포 (AWS EC2)
`running-coach-bot`이 떠 있는 기존 EC2(t2.micro, ubuntu)에 두 번째 systemd 서비스로 공존한다.
주간 사이클은 별도 크론이 아니라 **봇 프로세스 안의 JobQueue**로 실행되고, 완료되면 결과 요약을 채팅으로 push한다 — running-coach-bot의 `jq.run_daily(weekly_report, ...)` 패턴과 동일. 단, **판단과 체결을 시점을 분리**해 look-ahead 편향을 없앴다.
- `decision_job` (화요일 07:00 KST, 장 시작 전) — `run_weekly.run_decision()` 실행, 판단만 로그
  - 판단 기준일은 실행 시각의 "latest"가 아니라 `data_collector.get_last_completed_trading_day()`로 **직전 완료된 거래일**을 명시적으로 고정한다 (코스피 지수에 실제 데이터가 있는 날만 거래일로 취급 — 공휴일이 며칠 겹쳐도 자동으로 건너뜀). `data_collector.assert_before_market_open()`이 09:00 KST 이후 실행을 아예 막아서, 라이브 스냅샷이 그 거래일 종가와 정확히 일치한다는 가정을 보장한다.
- `execution_job` (화요일 09:05 KST, 장 시작 후) — `run_weekly.run_execution()` 실행, 실제 당일 시가 기준으로 체결/벤치마크 확정
  - `config.EXECUTION_SLIPPAGE_PCT` (0.3%, 진입·청산 양쪽에 불리한 방향으로), `config.BROKER_FEE_PCT` (0.015%, 매수/매도 각각), `config.TRANSACTION_TAX_PCT` (0.20%, 매도 시만 — 2026년 기준 코스피 0.05%+농특세 0.15%, 코스닥 0.20%로 두 시장 모두 동일해 단일값 사용)
  - 매주 완전 리밸런싱을 가정하므로 위 비용을 매주 왕복(진입+청산) 전부에 적용한다
  - 내 보유(①)·AI(②)·지수(③) 세 트랙 모두 `benchmark._get_open_price()` 하나로 통일해 같은 화요일 시가 기준에서 출발한다. 그 날짜 데이터가 없으면(장 시작 전 오호출 등) 조용히 넘어가지 않고 바로 에러를 낸다.
  - **`run_weekly.run()`(CLI 수동 실행)은 판단만 하고 체결/벤치마크는 절대 자동으로 이어서 하지 않는다** — look-ahead 편향 방지를 위해 판단·체결 사이 시간 간격이 반드시 있어야 하므로, 실수로 성과 기록이 오염되는 걸 막기 위한 안전장치다. 체결은 장 시작 후 `run_execution()`을 별도로 호출할 것.

(`JobQueue.run_daily`의 `days`는 0=일요일 ~ 6=토요일 순서라 화요일은 `2`다 — Python 표준 `weekday()`와 달라서 처음에 잘못 넣었던 부분)

- 서버 경로: `/home/ubuntu/ai-shadow-track` (이 GitHub 레포를 `git clone`한 것, 자체 `venv/`)
- systemd: `/etc/systemd/system/shadowtrack.service` (`runcoach.service`와 동일 구조 — `User=ubuntu`, `EnvironmentFile=.env`, `Restart=always`)
- `.github/workflows/deploy.yml` — `main`에 push되면 EC2로 SSH 접속해 `git pull` + `pip install` + `systemctl restart shadowtrack` (repo secrets: `EC2_HOST`, `EC2_SSH_KEY`)

**중요**: `data/shadow_track.db`에는 실제 보유 종목/수량/평가금액이 담겨 있어서 `.gitignore`로 git에서 완전히 제외했다 — 레포는 public이지만 db는 EC2 서버 로컬에만 존재한다. 로컬에서 다시 받아보려면 서버에서 `scp`로 가져올 것.

## 구조
- `src/config.py` — 스크리너 임계값/모델명 등 전역 설정
- `src/db.py` — SQLite 스키마 (holdings/decisions/snapshots/universe_snapshot/screener_output)
- `src/seed_holdings.py` — 실제 보유 시딩 (블라인드, LLM 프롬프트에 미투입)
- `src/data_collector.py` — 코스피+코스닥 유니버스/지수 스냅샷
- `src/screener.py` — 위생필터 → 중복제거 → 모멘텀랭킹 → 상관관계 클러스터 다양화
- `src/news_collector.py` — shortlist·시장 전반 뉴스만 수집
- `src/llm_judge.py` — 블라인드 LLM 판단
- `src/benchmark.py` — 3파전 수익률 스냅샷
- `src/run_weekly.py` — 위 전체를 묶는 주간 오케스트레이터
- `src/telegram_bot.py` — 결과 질의응답 봇

세부 설계 결정과 배경은 `context-notes.md`, 남은 작업은 `checklist.md` 참조.
