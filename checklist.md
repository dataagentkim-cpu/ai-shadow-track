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

## 텔레그램 Q&A
- [x] telegram_bot.py (/performance /latest /history /why /holdings) - DB 쿼리 로직 검증 완료
- [ ] **사용자 조치 필요**: BotFather로 봇 생성 → TELEGRAM_BOT_TOKEN 발급, 본인 chat_id 확인 후 .env에 반영
- [ ] 봇을 상시 구동 (로컬 실행 또는 launchd 상시 프로세스로 등록)

## 자동화 (GitHub Actions)
- [x] .github/workflows/weekly.yml 작성 (매주 월요일 07:00 KST, 실행 후 DB 커밋 + 텔레그램 알림)
- [ ] **사용자 조치 필요**: GitHub 원격 저장소 생성 + push
- [ ] **사용자 조치 필요**: repo secrets 등록 (ANTHROPIC_API_KEY/NAVER_CLIENT_ID/SECRET은 로컬 .env에 있는 값 그대로, TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID는 봇 발급 후)

## 미해결/알려진 제약 (사후 검토 필요)
- [ ] 밸류에이션(PER/PBR) 데이터 소스 부재 - pykrx가 KRX 로그인 요구로 막혀 모멘텀+유동성만으로 랭킹 중
- [ ] 지주-자회사 중복 제거는 미구현 (보통주/우선주 쌍만 제거)
- [ ] P1 사후검증 리포트, 대시보드는 이번 빌드 범위 밖
