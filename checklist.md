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
- [x] Look-ahead 편향 제거: 판단(직전 완료 거래일 종가, `get_last_completed_trading_day`로 명시 고정)과 체결(다음 거래일 시가) 시점 분리 + 장전 가드(`assert_before_market_open`)
- [x] `run_weekly.run()`은 판단만 실행, 체결/벤치마크 자동 실행 금지 (성과 기록 오염 방지 안전장치)
- [x] 거래비용 반영: 슬리피지 0.3%(진입·청산 양쪽 불리한 방향), 매매수수료 0.015%(양방향), 증권거래세 0.20%(매도 시, 2026년 기준 코스피/코스닥 공통)
- [x] 내 보유(①)·AI(②)·지수(③) 세 트랙 모두 `benchmark._get_open_price()`로 통일해 같은 거래일 시가 기준에서 출발
- [x] AI 트랙 stateful 전환: 매주 지난주 자기 포트폴리오(track_id=ai_blind만, 내 실제 보유는 여전히 미포함)를 LLM 인풋으로 참고해 확대/유지/축소/매도 판단. 매수가·수익률은 프롬프트에서 배제(앵커링·처분효과 방지), "전량 유지"도 유효한 출력
- [x] 거래비용을 지난주 대비 실제 비중 변화(델타)에만 부과하도록 변경 — 유지되는 포지션은 비용 0 (`benchmark._rebalance_cost_pct`)
- [x] 블라인드 격리 감사 완료: `llm_judge.py`/`run_weekly.py`에 holdings 테이블·TRACK_MY_HOLDINGS 참조 전무, `_get_previous_ai_portfolio()`는 track_id=ai_blind로 하드 필터링

## 텔레그램 Q&A + 상시 구동
- [x] telegram_bot.py (/performance /latest /history /why /holdings) - 실제 서버에서 동작 확인
- [x] BotFather로 봇 생성, TELEGRAM_BOT_TOKEN/chat_id 발급 및 반영
- [x] 주간 사이클을 GitHub Actions 크론이 아니라 봇 내장 JobQueue(decision_job 화 07:00 KST, execution_job 화 09:05 KST)로 실행 — running-coach-bot과 동일 패턴
- [x] AWS EC2(t2.micro, 3.35.236.206 — running-coach-bot과 같은 서버에 공존)에 systemd 서비스(`shadowtrack.service`)로 상시 구동 등록

## 자동화 (GitHub Actions)
- [x] `.github/workflows/deploy.yml` — main에 push되면 EC2로 SSH 접속해 git pull + pip install + systemctl restart (CD 전용, 파이프라인 실행은 안 함)
- [x] GitHub public 레포 생성 + push (https://github.com/dataagentkim-cpu/ai-shadow-track)
- [x] repo secrets 등록 (EC2_HOST, EC2_SSH_KEY) + 서버 passwordless sudo 확인
- [x] 개인 보유 데이터가 담긴 `data/shadow_track.db`는 git에서 완전히 제외 (레포는 public, db는 서버 로컬에만 존재)

## 4파전 + 총수익 + PIT + 위험지표 (A/B/C/D 확장)
- [x] A: ④ 동일가중 baseline 트랙 신설 — 그 주 shortlist를 LLM 판단 없이 균등보유, ②와 완전히 같은 체결/비용 규칙(`benchmark._snapshot_rebalanced_track` 공유) 적용
- [x] `/alpha` 명령어로 ②−④ 주간/누적 스프레드 조회 (별도 테이블 없이 snapshots에서 매번 계산 — 완전히 유도 가능한 값이라 중복 저장 안 함)
- [x] B: 배당 포함 총수익 전환 — 개별 종목은 `dart_client.py`(DART 공시 현금배당수익률), 지수는 근사 상수(코스피 2.0%/코스닥 1.0%), 배당소득세 15.4% 세후 반영
- [x] DART_API_KEY는 dart-ma-screener 프로젝트에 있던 기존 키 재사용
- [x] C: 뉴스 PIT 필터 (`news_collector._decision_cutoff`, 게시일시가 판단시각 이후면 배제), 거래정지/상장폐지 시 마지막 시가로 동결 청산 처리 (`benchmark._get_open_price_safe`)
- [x] D: `risk_metrics.py` — 트랙별 주간/누적 Sharpe·Sortino·MDD·적중률·회전율, ②/④의 ③ 대비 베타·알파, 클러스터 집중도(실제 섹터 데이터 부정확해 상관관계 클러스터로 대체) — `/risk` 명령어로 조회
- [x] 통합 테스트: 실제 시장 데이터로 2주치 전체 사이클(스크리너→shortlist→④균등편입→가짜 판단→벤치마크→위험지표)을 로컬에서 직접 실행해 턴오버/비용/배당 계산을 손으로 검산해 확인
- [x] (부수 발견) screener.py의 상관관계 행렬 구성 버그 수정 — 종목별 거래일 수가 달라 `.values`로 합치면 길이불일치로 크래시하던 것을, 날짜 인덱스를 유지한 `pd.concat`으로 교체

## 미해결/알려진 제약 (사후 검토 필요)
- [ ] 밸류에이션(PER/PBR) 데이터 소스 부재 - pykrx가 KRX 로그인 요구로 막혀 모멘텀+유동성만으로 랭킹 중
- [ ] 지주-자회사 중복 제거는 미구현 (보통주/우선주 쌍만 제거)
- [ ] P1 사후검증 리포트, 대시보드는 이번 빌드 범위 밖
- [ ] t2.micro를 러닝코치 봇과 공유 중 (RAM 951MB) — 두 봇 다 가벼운 편이라 문제 없었지만, 주간 사이클(스크리너 히스토리 조회 150건 + DART 조회 최대 90여건) 실행 중 메모리/시간 사용량은 아직 서버 실전 실행에서 실측 안 함
- [ ] 지수(③) 총수익은 진짜 TR 데이터가 아니라 고정 근사 배당수익률(코스피 2.0%/코스닥 1.0%) — 실제 KRX 총수익지수 데이터 소스 확보 시 교체 필요
- [ ] 개별 종목 배당은 DART 연간 공시 수익률을 52주로 매끄럽게 안분한 근사치 — 실제로는 연 1회 특정일에 지급되므로 지급 시점 전후로 실제와 오차 있음
- [ ] 상장폐지 감지는 "60일간 거래 데이터 없음" 휴리스틱 — 진짜 상장폐지와 장기 거래정지를 구분하지 않음
