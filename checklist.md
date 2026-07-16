# 체크리스트

## P0 - 코어 파이프라인
- [x] venv/의존성 세팅 (python@3.14 pyexpat 링크 문제 해결)
- [x] DB 스키마 (holdings/decisions/snapshots/universe_snapshot/screener_output)
- [x] 실제 보유 홀딩 시딩 (seed_holdings.py, 오늘 시세 기준 재평가)
- [x] 유니버스 스냅샷 수집 (data_collector.py, FinanceDataReader)
- [x] 정량 스크리너 (screener.py: 위생필터 → 보통주/우선주 중복제거 → 모멘텀랭킹 → 상관관계 클러스터 다양화)
- [x] 뉴스 수집기 (news_collector.py, 네이버 뉴스 API) - NAVER_CLIENT_ID/SECRET 발급 완료, 실제 검색 결과로 검증 완료
- [x] LLM 블라인드 판단 (llm_judge.py, claude-sonnet-5) - 기존 다른 프로젝트(.env)에 있던 ANTHROPIC_API_KEY 재사용해 실제 호출 검증 완료
- [x] 3파전 벤치마크 스냅샷 (benchmark.py) - 실제 데이터로 검증 완료
- [x] 주간 오케스트레이터 (run_weekly.py)

## 텔레그램 Q&A + 상시 구동
- [x] telegram_bot.py (/performance /latest /history /why /holdings) - 실제 서버에서 동작 확인
- [x] BotFather로 봇 생성, TELEGRAM_BOT_TOKEN/chat_id 발급 및 반영
- [x] 주간 사이클을 GitHub Actions 크론이 아니라 봇 내장 JobQueue(run_daily, 매주 월요일 07:00 KST)로 실행 — running-coach-bot과 동일 패턴
- [x] AWS EC2(t2.micro, 3.35.236.206 — running-coach-bot과 같은 서버에 공존)에 systemd 서비스(`shadowtrack.service`)로 상시 구동 등록

## 자동화 (GitHub Actions)
- [x] `.github/workflows/deploy.yml` — main에 push되면 EC2로 SSH 접속해 git pull + pip install + systemctl restart (CD 전용, 파이프라인 실행은 안 함)
- [x] GitHub public 레포 생성 + push (https://github.com/dataagentkim-cpu/ai-shadow-track)
- [x] repo secrets 등록 (EC2_HOST, EC2_SSH_KEY) + 서버 passwordless sudo 확인
- [x] 개인 보유 데이터가 담긴 `data/shadow_track.db`는 git에서 완전히 제외 (레포는 public, db는 서버 로컬에만 존재)

## 미해결/알려진 제약 (사후 검토 필요)
- [ ] 밸류에이션(PER/PBR) 데이터 소스 부재 - pykrx가 KRX 로그인 요구로 막혀 모멘텀+유동성만으로 랭킹 중
- [ ] 지주-자회사 중복 제거는 미구현 (보통주/우선주 쌍만 제거)
- [ ] P1 사후검증 리포트, 대시보드는 이번 빌드 범위 밖
- [ ] t2.micro를 러닝코치 봇과 공유 중 (RAM 951MB) — 두 봇 다 가벼운 편이라 문제 없었지만, 주간 사이클(스크리너 히스토리 조회 150건) 실행 중 메모리 사용량은 아직 서버에서 실측 안 함
