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

## 필요한 자격증명 (.env)
- `ANTHROPIC_API_KEY` — 다른 로컬 프로젝트(morning_brief_bot 등)에 있던 기존 키를 재사용해 이미 `.env`에 채워져 있음
- `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` — 발급 완료, `.env`에 반영됨
- `TELEGRAM_BOT_TOKEN` — 텔레그램 BotFather(@BotFather)에게 `/newbot`으로 발급, **아직 미발급**
- `TELEGRAM_ALLOWED_CHAT_ID` — 본인 채팅에서만 봇이 응답하도록 제한 (비우면 전체 허용)

## 텔레그램 명령어
- `/performance` — 3파전(내 보유/AI 블라인드/지수) 최신 수익률
- `/latest` — 이번 주 AI 블라인드 판단 전체
- `/history` — 최근 수익률 추이
- `/why 종목명` — 특정 종목의 최근 판단 이유
- `/holdings` — 내 실제 보유 스냅샷

## 자동화 (GitHub Actions)
`.github/workflows/weekly.yml`이 매주 월요일 07:00 KST에 `run_weekly.py`를 실행하고
결과 DB를 커밋 + 텔레그램으로 완료 알림을 보낸다. 사용 하려면:
1. 이 저장소를 GitHub에 push
2. 저장소 Settings → Secrets에 위 자격증명 4종 + `TELEGRAM_CHAT_ID` 등록

봇 자체(Q&A 폴링)는 상시 프로세스가 필요해 GitHub Actions 대상이 아니다 — 로컬이나 별도 서버에서 `telegram_bot.py`를 계속 띄워둘 것.

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
