# 컨텍스트 노트

빌드 중 내린 결정과 그 이유를 기록. 원본 기획은 `shadow-track-build-brief.md` 참조.

## 환경 이슈
- 이 Mac의 homebrew `python@3.14`가 `pyexpat` ↔ 시스템 `libexpat` 심볼 불일치로 깨져 있어 venv/pip 자체가 안 만들어졌음.
  `brew install expat` 후 `pyexpat.cpython-314-darwin.so`를 `install_name_tool`로 재연결 + 재서명해서 해결.
  (참고: 이 조치는 이 프로젝트의 `.venv` 안 `.so` 파일에만 영향, 다른 프로젝트 `.venv`는 무관하며 시스템 파일도 안 건드림. `brew reinstall python@3.14` 하면 원상복구됨)

## 데이터 소스 변경: pykrx → FinanceDataReader 단일화
- 브리프는 `pykrx`/`FinanceDataReader` 둘 다 언급했으나, 빌드 시점에 pykrx(1.2.8)의 KRX 데이터 API가 로그인 세션을 요구하도록 바뀌어 있었음
  (`data.krx.co.kr` 응답이 "LOGOUT" 텍스트만 반환, 원래 공개였던 전종목시세 API가 막힘).
  KRX_ID/KRX_PW 계정이 없으므로 pykrx는 뺐고, FinanceDataReader 하나로 유니버스 스냅샷/지수/개별종목 이력을 전부 처리.
- 대신 FDR에는 PER/PBR 등 밸류에이션 지표가 없음 → 1차 스크리너는 "모멘텀(90일 수익률) + 유동성(거래대금)"만으로 랭킹.
  밸류에이션 랭킹은 추후 다른 소스(DART 공시, 별도 유료 API 등) 확보 시 추가 가능하도록 `screener.py`의 랭킹 결합부만 손보면 됨.

## 다양화 방식: 업종 캡 → 상관관계 클러스터링으로 승격
- 원래 사용자에게는 "업종당 최대 3개" 심플 캡을 기본값으로 제안했었음.
- 빌드 중 FDR의 `KRX-DESC` Industry 필드를 확인해보니 실제 업종과 안 맞는 경우가 많았음
  (예: 삼성전자가 "통신 및 방송 장비 제조업"으로 등록 — 등기상 산업분류라 현재 사업과 괴리).
  이 데이터로 업종 캡을 걸면 다양화 로직 자체가 의미 없어짐.
- 그래서 브리프의 "업그레이드" 옵션이었던 최근 90일 수익률 상관관계 클러스터링(임계값 0.75, 클러스터당 최대 3개)으로 바로 구현.
  실제 테스트에서 KB금융/하나금융지주/신한지주가 한 클러스터로, SK하이닉스/SK스퀘어/삼성전자가 한 클러스터로 묶이는 등 의도대로 동작함을 확인.

## 벤치마크 설계
- 3개 트랙 모두 오늘(홀딩 평가금액, ~5,693만원)을 공통 원금으로 시작 — 트랙 간 수익률뿐 아니라 금액도 직접 비교 가능하게.
- ③ 지수 트랙은 브리프에 "코스피(+코스닥)"로만 적혀 있어 배합 비율이 명시되지 않음 → V1은 코스피/코스닥 동일가중(50/50) 블렌드로 가정. 나중에 다른 배합을 원하면 `benchmark.py`의 `_index_change` 한 곳만 수정하면 됨.
- ② AI 트랙은 매주 직전 주 목표비중대로 그 주간 수익률을 반영한 뒤, 이번 주 새 판단으로 리밸런싱하는 방식. (2026-07-16 4차 수정으로 "매주 완전 리밸런싱 가정"은 폐기 — 아래 stateful 전환 항목 참조. 유지되는 비중은 그대로 이어가고 실제 변경분에만 비용이 붙는 부분 리밸런싱으로 바뀜)

## 자격증명 검증 완료
- `llm_judge.py`: 다른 로컬 프로젝트(morning_brief_bot 등)의 `.env`에 이미 있던 ANTHROPIC_API_KEY를 그대로 재사용 → 실제 tool-use 호출로 검증 완료 (삼성전자/SK하이닉스 샘플 판단 정상 생성).
- `news_collector.py`: 사용자가 신규 발급한 NAVER_CLIENT_ID/SECRET → 실제 뉴스 검색 API 호출로 검증 완료.
- `telegram_bot.py`: BotFather로 발급한 실제 토큰 + chat_id로 EC2 서버에서 실행 중, 명령어 응답 확인 완료.

## 배포: AWS EC2 (running-coach-bot과 동일 서버에 공존)
- 사용자가 예전에 running_coach 에이전트를 Railway → AWS로 옮긴 적이 있어서, 그 서버 구성을 그대로 참고해서 미러링함.
- 서버: 기존 EC2 t2.micro (`3.35.236.206`, ubuntu 26.04, ubuntu 사용자) — 새 인스턴스를 따로 안 띄우고 이 서버에 두 번째 봇으로 공존시키기로 결정 (aws configure 자격증명 설정 없이도 SSH만으로 바로 배포 가능했고, 리소스도 가벼워서 충분).
- **주간 스케줄링 방식도 그대로 미러링**: `run_weekly.py`를 GitHub Actions cron이나 systemd timer로 도는 게 아니라, `telegram_bot.py` 안에서 python-telegram-bot의 `JobQueue.run_daily`로 실행 (러닝코치 봇의 `bot.py`가 `jq.run_daily(weekly_report, ...)`로 월요일 리포트를 보내는 것과 동일 패턴). 이 방식의 장점 — 봇 프로세스 하나로 상시구동+주간배치가 다 해결되고, 별도 크론 인프라나 GitHub Actions secrets에 의존하지 않음.
  주의: `JobQueue.run_daily`의 `days` 파라미터는 **0=일요일 ~ 6=토요일** 순서다 (Python 표준 `date.weekday()`의 월=0과 다름). 처음에 `days=(0,)`로 넣어서 실제로는 일요일에 도는 버그가 있었음 (러닝코치 봇의 `jq.run_daily(..., days=(0,))`도 같은 라이브러리를 쓰므로 동일한 착오가 있을 가능성이 있음, 확인 안 해봄). 이후 스케줄을 화요일로 옮기면서 최종적으로 `days=(2,)`.

  주의: `python-telegram-bot[job-queue]` extra(APScheduler 포함)를 설치해야 `app.job_queue`가 `None`이 아니게 됨 — 처음에 이걸 놓쳐서 서비스가 한 번 죽었었음 (`AttributeError: 'NoneType' object has no attribute 'run_daily'`).
- systemd 유닛(`shadowtrack.service`)도 `runcoach.service`와 완전히 동일한 구조로 작성 (User=ubuntu, EnvironmentFile=.env, Restart=always).
- **GitHub Actions의 역할이 바뀜**: 원래 계획했던 "주간 파이프라인을 Actions에서 돌리고 db를 커밋"하는 방식은 폐기. 개인 보유 데이터가 담긴 db를 public 레포에 커밋할 수 없어서(아래 항목 참조) 어차피 안 맞았고, JobQueue 방식으로 가면서 완전히 불필요해짐. 지금은 `.github/workflows/deploy.yml`이 main push 시 EC2로 SSH 접속해 git pull + 의존성 재설치 + `systemctl restart shadowtrack`만 하는 순수 CD 파이프라인.

## Look-ahead 편향 수정 + 거래비용 반영 (2026-07-16)
- 1차 수정: AI 트랙이 "판단 시점 가격으로 바로 체결"하는 구조라 실제로는 불가능한 가격에 체결하는 셈이었음(look-ahead). `run_weekly.py`를 `run_decision()`(장 시작 전, 스냅샷→스크리너→뉴스→LLM판단만)과 `run_execution()`(장 시작 후, 실제 시가로 벤치마크만)으로 분리. `telegram_bot.py`도 `decision_job`/`execution_job` 두 개로 나눠서 스케줄.
- 2차 수정(사용자 요청): 처음엔 "금요일 종가 판단 → 월요일 시가 체결"이었으나, "월요일 종가 판단 → 화요일 시가 체결"로 하루 밀림. `decision_job`은 화요일 07:00 KST(장 시작 전, 월요일 종가+뉴스 기준), `execution_job`은 화요일 09:05 KST(장 시작 후, 화요일 실제 시가 기준)로 스케줄 변경. 체결가 자체의 계산 방식(시가+슬리피지)은 그대로 유지, 요일만 이동.
- 거래비용도 추가: `benchmark.py`의 `_entry_exit_return()`에서 진입가 = 시가×(1+슬리피지+매매수수료), 청산가 = 시가×(1-매매수수료-거래세). 매주 완전 리밸런싱을 가정하므로 매주 왕복 비용을 전부 부과. 수수료/거래세는 정확한 종목별 시장 구분 없이 근사치로 설정(`config.BROKER_FEE_PCT`, `config.TRANSACTION_TAX_PCT`) — 정밀한 세율 반영이 목적이 아니라 "리밸런싱이 공짜가 아니다"라는 걸 수익률에 실어주는 게 목적.
- (2026-07-16 3차 수정에서 뒤집힘) 애초엔 "①/③ 트랙은 트레이딩 결정을 안 내리니까 손 안 댐"이었으나, 사용자가 세 트랙 가격 기준 자체를 통일해달라고 해서 아래 3차 수정에서 결국 손을 댐.

## Look-ahead 편향 3차 수정: 날짜 명시 고정 + run() 안전장치 + 정밀 세율 + 전 트랙 시가 통일 (2026-07-16)
사용자가 코드를 직접 읽고 "실행 시각의 latest에 의존하는 것 아니냐"고 정확히 짚어서, 시간에 의존하던 부분들을 전부 명시적으로 고정함.
- **판단 기준일 명시 고정**: `data_collector.get_last_completed_trading_day(as_of)` 추가 — 코스피 지수(KS11)에 실제 데이터가 있는 마지막 날을 반환. 당일 데이터(장중이라도)는 절대 포함 안 함 → `as_of - 1일`까지만 조회해서 원천 차단. 공휴일이 껴도 KS11에 그날 데이터가 없으므로 자동으로 그 이전 거래일로 건너뜀 — 별도 공휴일 캘린더 없이 지수 자체를 캘린더로 씀.
- **장전 가드**: `data_collector.assert_before_market_open()` — 09:00 KST 이후엔 `run_decision()`이 아예 실행을 거부(`RuntimeError`). 이게 있어야 "장 시작 전에 실행 = 라이브 스냅샷이 직전 거래일 종가와 같다"는 가정이 코드로 보장됨 (기존엔 스케줄 타이밍만 믿고 있었음).
- **`run_weekly.run()` 안전장치**: 기존엔 `run_decision()`+`run_execution()`을 간격 없이 이어서 실행해 look-ahead 방지가 무의미해질 수 있었음. 이제 `run()`은 `run_decision()`만 실행하고 절대 `run_execution()`을 자동으로 잇지 않음 — 성과 기록(snapshots)이 간격 없는 실행으로 오염되는 걸 원천 차단. 체결이 필요하면 장 시작 후 `run_execution()`을 사람이 직접 따로 불러야 함.
- **슬리피지 양방향**: (당시) `benchmark._entry_exit_return()`에서 진입가=시가×(1+슬리피지+수수료), 청산가=시가×(1-슬리피지-수수료-거래세)로, 슬리피지를 진입/청산 둘 다 불리한 방향으로 적용. — 이 함수는 아래 5차 수정(stateful 전환)에서 `_raw_return`+`_rebalance_cost_pct`로 대체되어 지금은 없음. 원칙(양방향 슬리피지)은 그대로 유지.
- **거래세 정밀화**: `config.TRANSACTION_TAX_PCT = 0.0020` (2026년 기준 매도 시 1회) — 코스피(거래세 0.05%+농특세 0.15%=0.20%)와 코스닥(0.20%)이 결과적으로 같은 숫자라서 종목별 시장 구분 없이 단일 상수로 처리 (시장 구분 로직을 따로 안 짜도 되는 게 확인된 셈).
- **전 트랙 시가 통일**: `benchmark._get_open_price(code, date)` 공용 함수 추가 — `fdr.DataReader`로 그 날짜의 실제 시가를 가져오고, 그 날짜에 데이터가 없으면(장 시작 전 오호출 등) 바로 에러를 낸다. 기존엔 ①(내 보유)이 `fdr.StockListing`의 라이브 "Close" 필드, ③(지수)도 `fdr.DataReader`의 "Close" 필드를 썼는데(둘 다 실행 시점의 실시간 값이라 실질적으로는 시가와 비슷하지만 필드 이름과 의미가 달랐음) — 이제 ①②③ 전부 `_get_open_price` 하나로 통일해서 진짜 명시적인 시가 기준이 됨.

## AI 트랙 stateful 전환 (2026-07-16 5차 수정)
그동안 AI 트랙은 매주 완전히 백지에서 새로 판단하고, 벤치마크 계산도 "매주 100% 리밸런싱"을 가정했음. 사용자가 이걸 stateful로 바꿔달라고 요청 — 실제 트레이더처럼 "지난주 포트를 이어받아 부분 조정"하는 구조로 변경.
- **LLM 인풋에 지난주 AI 포트폴리오 추가**: `run_weekly._get_previous_ai_portfolio(conn)`이 `decisions` 테이블에서 `track_id='ai_blind'`(AI 자신의 트랙)의 가장 최근 회차만 가져와 `judge()`에 넘김. **내 실제 보유(track_id='my_holdings', holdings 테이블)는 이 함수도, `llm_judge.py` 전체도 절대 참조하지 않음** — 사용자가 별도로 감사를 요청해서 grep으로 재확인, 새는 경로 없음 확인.
- **첫 주는 여전히 백지**: `_get_previous_ai_portfolio`가 과거 판단이 없으면 빈 리스트를 반환하고, 프롬프트도 "지난주 포트폴리오: 없음(첫 판단)"으로 분기 — 2주차부터만 stateful이 실질적으로 작동.
- **앵커링/처분효과 방지 프레이밍**: 프롬프트에 매수가·수익률을 아예 안 줌(애초에 decisions 테이블에 가격 필드가 없어서 구조적으로도 샐 수 없음). "오늘 이 가격에 새로 산다면 살 것인가" 기준으로 재평가하라고 명시 지시, "이미 벌었으니 익절"/"손실 중이니 버팀" 식 사고를 하지 말라고 System prompt에 직접 금지.
- **action enum 변경**: 매수/매도/홀딩 → 확대/유지/축소/매도. "전량 유지(무거래)"가 정상적이고 권장되는 선택지임을 프롬프트에 명시 — 근거 없이 매주 흔드는 게 오히려 나쁜 신호라고 못박음.
- **거래비용을 델타 기준으로 전환**: `benchmark._raw_return()`(비용 없는 순수 시가-시가 수익률, 유지되는 포지션에 적용)과 `benchmark._rebalance_cost_pct(prev_weights, curr_weights)`(지난주/이번주 목표비중 차이에만 비용 부과) 추가. 종목별로 델타>0(신규/확대)면 슬리피지+수수료, 델타<0(축소/매도)면 슬리피지+수수료+거래세, 델타=0(유지)이면 비용 0. 유닛테스트 성격으로 완전유지/부분리밸런싱/전량매도 세 케이스 직접 계산해서 숫자 검증함.
- `snapshot_ai_track`은 이제 이번 주 decisions가 아직 없으면(`decision_job` 실패 등) 조용히 넘어가지 않고 바로 `RuntimeError`.

## 레포 공개 범위와 개인 데이터 분리
- 사용자의 다른 레포들은 다 public이라 이 프로젝트도 처음엔 public + db 커밋 방침으로 갔었음.
- 그런데 `data/shadow_track.db`에는 실제 보유 종목명/수량/평가금액이 그대로 담겨 있어서, public 레포에 커밋하면 사용자의 실제 자산 정보가 공개됨 — API 키 문제가 아니라 개인 재무 데이터 노출 문제라 별개로 처리.
- 최종 결정: 레포는 public 유지, 대신 db 파일 자체를 `.gitignore`에 추가하고 git 히스토리에서도 완전히 제거 (당시 아직 push 전이었어서 `.git` 재초기화로 간단히 해결). db는 EC2 서버 로컬 디스크에만 존재.

## 4파전 + 총수익 + PIT + 위험지표 (2026-07-16 6차 수정)
사용자가 A(동일가중 baseline)/B(배당 총수익)/C(PIT 무결성)/D(위험조정 지표) 4개를 한 번에 요청. B와 C의
재무 부분은 DART API가 있어야 제대로 되는데, 확인해보니 다른 프로젝트(`dart-ma-screener`)에 이미 키가
있어서 재사용함.

- **B 데이터 소스 확인**: FinanceDataReader는 개별 종목 배당 데이터가 아예 없고(OHLCV만), pykrx의 배당
  관련 함수(`get_market_fundamental`)도 이전에 발견한 KRX 로그인 문제로 막혀 있음. 코스피/코스닥
  총수익지수(TR) 티커도 FDR에 없음. DART의 `alotMatter.json`(사업보고서 "배당에 관한 사항" 공시)에서
  "현금배당수익률(%)" 필드를 직접 제공해서(삼성전자 보통주 1.50% 확인) 이걸로 개별 종목 배당을 처리.
  지수(③)는 DART로도 안 되는 영역이라(지수 자체의 배당재투자 데이터가 없음) 통상 언급되는 평균
  배당수익률(코스피 2.0%/코스닥 1.0%)을 고정 근사치로 씀 — 부정확함을 알고 쓰는 근사치, checklist에 명시.
- **PIT 안전한 사업연도 선택**: `dart_client._safe_fiscal_year(as_of)`는 사업보고서 법정 제출기한(결산 후
  90일=3월 말)을 감안해, 4월 이전엔 전전년도까지 내려가서 "판단 시점에 이미 공시가 끝났을 게 확실한"
  연도만 쓴다 — 실제 공시 접수일자를 개별 조회하진 않는 근사적 PIT 안전장치.
- **개별 배당 안분 방식**: 실제 배당은 연 1회 특정일(대개 결산일 전후)에 지급되지만, 지급일 데이터까지는
  없어서 연간 배당수익률을 52주에 걸쳐 매끄럽게 발생한다고 근사(`benchmark._dividend_accrual`). 배당
  지급월 전후로는 실제와 시점 오차가 있음 — 알고 있는 한계.
- **A 트랙 설계**: `benchmark._snapshot_rebalanced_track(track_id, ...)`을 만들어 AI(②)와 동일가중
  baseline(④)이 완전히 같은 함수를 공유하게 함 — 코드가 하나라 둘의 체결/비용 규칙이 절대 어긋날 수
  없음. ④의 decisions는 `run_weekly._log_equal_weight_decisions()`가 LLM 호출 없이 그 주 shortlist
  전체에 `1/N` 비중을 부여해 기록. ②−④ 스프레드는 새 테이블을 안 만들고 `benchmark.get_alpha_spread()`가
  매번 snapshots에서 계산 — 두 트랙의 값만으로 완전히 유도되는 숫자라 중복 저장할 이유가 없다고 판단.
- **C 거래정지/상장폐지**: `benchmark._get_open_price_safe()`가 그 날짜 데이터가 없으면 최근 60일 내
  마지막 시가로 "동결 청산" 처리(60일도 없으면 에러). `_raw_return`이 내부적으로 이걸 씀. 진짜 상장폐지와
  단순 장기 거래정지를 구분하는 로직은 없음 — 둘 다 "마지막 가격에 묶임" 취급.
- **C 뉴스 PIT**: `news_collector._decision_cutoff(decision_date)`가 "판단 시각"을 직전 거래일 다음날
  07:00 KST로 정의하고, 그 이후 게시된 기사는 배제. 네이버 뉴스 API가 최신순으로 실시간 검색해서 원래도
  미래 기사가 나올 수는 없는 구조지만, 수동 백테스트(과거 날짜로 `decision_date`를 지정)할 때를 위한
  방어적 안전장치. 날짜 파싱 실패 시엔 안전하게 배제(포함 아님)하도록 함.
- **C 유니버스 생존편향**: 별도 이력 테이블을 만들지 않고, 기존 `screener_output`(주차별 전체 후보군 +
  포함/제외 사유)을 그대로 활용하기로 함 — 이미 있는 데이터로 유도 가능해서.
- **D 위험지표**: `risk_metrics.py` 신설, `risk_metrics` 테이블에 트랙×주차별로 기록. Sharpe/Sortino는
  무위험수익률 0 가정(V1 단순화). 베타/알파는 ②/④에 대해서만(③ 대비), 회전율도 ②/④ 전용(①③은 매주
  트레이딩 결정을 안 하므로 무의미). "섹터 편중"은 KRX 등록 업종 정보가 부정확하다고 이미 확인된 바 있어
  (삼성전자가 "통신 및 방송 장비 제조업" 등록 — 5차 이전 수정 참조) 대신 스크리너의 상관관계
  클러스터(`cluster_id`)로 대체 — "상위 클러스터 집중도"로 이름 붙임, 진짜 GICS/WICS 섹터는 아님.
- **통합 테스트**: 실제 시장 데이터(2026-07-09, 2026-07-16 두 거래일)로 스크리너→shortlist→④균등편입
  →(LLM 호출은 생략하고 직접 구성한) 판단→벤치마크→위험지표까지 로컬에서 2주치를 직접 돌려서 검증.
  2주차엔 보유 3종목 중 2종목을 실제로 교체하도록 구성해 턴오버(0.667, 손으로 검산해서 일치 확인)와
  델타 비용 계산이 실제로 맞물려 돌아가는 걸 확인.
- **부수 발견 버그**: `screener.py`의 상관관계 행렬 구성이 `pd.DataFrame({code: series.values, ...})`
  형태였는데, 종목마다 실제 거래일 수가 미묘하게 달라(신규상장·데이터 공백 등) 배열 길이가 안 맞으면
  크래시하는 버그였음. 오늘 이전엔 우연히 안 걸렸을 뿐 — 과거 날짜로 스크리너를 돌리자마자 재현됨.
  날짜 인덱스를 유지한 `pd.concat`으로 교체해 인덱스 기준 정렬되도록 수정(코드 자체 인과관계는 이번 작업과
  무관하지만, 통합 테스트 중 발견해 바로 고침).

## SPEC.md 도입 + 4렌즈 확장 착수했다가 순서 변경 (2026-07-16 7차)
- 사용자가 `shadow-track-build-brief.md`의 확장판(4렌즈 병렬, 체결 시점 규칙, 평가 방법론 A-D, 해석 규율까지
  담긴 버전)을 `SPEC.md`로 프로젝트 루트에 저장해달라고 요청 — 이제부터 이 문서가 기준 설계 문서. 채팅에
  붙여넣은 텍스트가 인코딩이 깨져있어서(mojibake) 로컬 원본 파일(`~/Downloads/shadow-track-build-brief.md`)을
  직접 Read해서 저장함 — 채팅에 붙여넣은 텍스트를 신뢰하지 말고 항상 원본 파일을 참조할 것.
- SPEC.md 요청에 따라 ②a(가치)/②b(모멘텀)/②c(퀄리티)/②d(자유형) 4렌즈 병렬 구조를 만들기 시작함
  (config.py에 TRACK_VALUE 등 4개 트랙 상수·LLM_TEMPERATURE, db.py에 decisions.weekly_perspective 컬럼,
  llm_judge.py를 4렌즈별 시스템 프롬프트로 재작성, run_weekly.py를 4렌즈 루프로 개편).
- **작업 도중 사용자가 순서를 바꿈**: 가치·퀄리티 렌즈는 SPEC.md상 PER/PBR/ROE/부채비율 등 실제 재무 수치로
  판단해야 하는데, 그 데이터가 아직 파이프라인에 없다는 걸 지적(직전 턴에서 이미 확인된 사실). 재무 연결 없이
  4렌즈부터 만들면 가치·퀄리티 렌즈 로그를 나중에 버려야 하니, DART 재무 연결을 먼저 끝내고 검증한 뒤 4렌즈를
  재개하기로 함.
- **롤백 처리**: `llm_judge.py`는 `git checkout`으로 마지막 배포 버전으로 완전히 되돌림. `run_weekly.py`는
  DART 재무 조회/로깅 부분(안전하고 완결된 부분)만 남기고, 4렌즈 판단 루프 부분(`_get_previous_lens_portfolio`,
  `_log_lens_decisions`, `judge(lens, ...)` 루프)은 이전 단일 트랙 버전(`_get_previous_ai_portfolio`,
  `_log_ai_decisions`, 단일 `judge()` 호출)으로 되돌림. **이유**: 이 상태로 커밋·배포했으면 서버가 다음
  화요일 결정 단계에서 `TRACK_VALUE` 등 새 트랙에 로그를 쓰는데, `benchmark.py`/`risk_metrics.py`/
  `telegram_bot.py`는 여전히 옛날 단일 트랙(`ai_blind`)만 봐서 `_snapshot_rebalanced_track`이 "이번 주
  판단 없음" RuntimeError로 크래시했을 것. 아직 아무것도 커밋·배포 안 한 상태였어서 안전하게 되돌릴 수 있었음.
- `config.py`의 `TRACK_VALUE`/`TRACK_MOMENTUM`/`TRACK_QUALITY`/`TRACK_FREE`/`LENS_TRACKS`/`LENS_BY_TRACK`/
  `LLM_TEMPERATURE`와 `db.py`의 `decisions.weekly_perspective` 컬럼은 **일부러 남겨둠** (지금은 아무도 참조
  안 하지만 곧 재개할 작업의 준비물이라 되돌리지 않음 — checklist.md에 "다음 단계"로 명시해둠).

## DART 재무지표 연결 (2026-07-16 7차, 4렌즈 재개 전 선행 작업)
- `dart_client.get_financial_metrics(stock_codes, as_of)`: DART `fnlttMultiAcnt.json`(다중회사 주요 재무
  항목)을 배치 조회(최대 80개씩, dart-ma-screener의 `BATCH_SIZE=80` 관례 그대로 재사용). 연결재무제표(CFS)
  우선, 없으면 별도재무제표(OFS)로 폴백. 매출액/영업이익/당기순이익/자산총계/부채총계/자본총계를 파싱해
  ROE(순이익/자본), 부채비율(부채/자본), 영업이익률(영업이익/매출액) 계산. 계정명 매칭 세트는
  dart-ma-screener의 `financial_data.py` 패턴 그대로 재사용.
- `dart_client.compute_valuation_ratios(financials, price, shares_outstanding)`: EPS=순이익/발행주식수,
  BPS=자본/발행주식수를 구한 뒤 그 시점 시가와 결합해 PER/PBR 계산. 발행주식수는 FDR `StockListing`의
  `Stocks` 컬럼(이미 유니버스 스냅샷에 있음)을 그대로 씀. 순이익이 음수면 PER=None(적자 기업 PER은 의미
  없으므로 억지로 음수/이상값 반환하지 않음).
- `_safe_fiscal_year()`(배당 조회 때 만든 PIT 안전장치)를 재무지표 조회에도 그대로 재사용 — 사업보고서
  법정 제출기한(3월 말) 기준으로 아직 공시 안 됐을 연도는 건너뜀.
- `screener_output` 테이블에 `per`/`pbr`/`roe`/`debt_ratio`/`op_margin` 컬럼 추가(마이그레이션 포함).
  `run_weekly.run_decision()`이 shortlist 확정 직후(`_fetch_shortlist_financials`) DART를 조회해서 함께
  기록 — shortlist 밖 110여개 후보는 조회 안 함(깔때기 원칙 유지, 불필요한 API 호출 안 함).
- **실제 검증**: 실 shortlist(40종목)로 커버리지 테스트 → 40/40(100%), 소요시간 2.2초(배치 덕분). PER/PBR
  값도 상식과 부합 — 손실 기업(기가레인·모나미 등)은 자동으로 PER=N/A, 최근 급등한 성장주(에이피알·
  한미반도체 등)는 PER/PBR 모두 높게 나옴.
- **알아둘 데이터 함정**: 은행/금융지주(KB금융·하나금융지주·신한지주)는 예금이 회계상 부채로 잡혀 부채비율이
  1000%를 넘게 나옴 — 실제로 위험한 게 아니라 업종 특성. 지주회사(SK스퀘어 등)는 자체 매출액이 작아서
  영업이익률이 100%를 훌쩍 넘는 등 비정상적으로 보일 수 있음. 나중에 퀄리티 렌즈 프롬프트를 만들 때 이
  두 가지를 그대로 "나쁜/이상한 신호"로 오독하지 않게 안내가 필요함 (아직 프롬프트에는 반영 안 함).

## 4렌즈 확장 재개 + 실전 배선 완료 (2026-07-16 8차)
DART 재무 연결 검증이 끝난 뒤 보류했던 4렌즈(②a가치/②b모멘텀/②c퀄리티/②d자유형) 확장을 재개해서
`llm_judge.py`→`run_weekly.py`→`benchmark.py`→`risk_metrics.py`→`telegram_bot.py` 전 파이프라인을
일관되게 다시 연결했다.

- **`llm_judge.py` 재작성**: 4개 시스템 프롬프트(공통 프레이밍 `_COMMON_FRAMING` 공유)에 실제 DART
  재무지표(PER/PBR/ROE/부채비율/영업이익률)를 종목별로 삽입. 퀄리티 렌즈뿐 아니라 공통 프레이밍에도
  "은행/지주 부채비율·영업이익률 왜곡" 예외 안내를 넣어 4개 렌즈 전부가 이 함정을 공유해서 인지하게 함
  (가치 렌즈도 PER/PBR을 실제 근거로 쓰므로 같은 함정에 노출됨).
- **`temperature` 파라미터 제거 (블로킹 버그)**: `config.LLM_TEMPERATURE=0.25`를 그대로 `client.messages.create()`에
  넘겼더니 `400 temperature is deprecated for this model` — claude-sonnet-5는 Opus 4.7+ 세대와 마찬가지로
  `temperature`/`top_p`/`top_k`를 비-기본값으로 넘기면 거부한다. SPEC.md의 "temperature 0.2~0.3 고정" 요구는
  API로 구현 불가능하다는 뜻 — `LLM_TEMPERATURE` 상수를 완전히 제거하고 판단 일관성은 프롬프트 규율
  (`_COMMON_FRAMING`의 앵커링 금지·전량유지 허용 문구)로만 확보하기로 함. 사용자에게 이 제약을 명시적으로
  보고함.
- **자유형(②d) 렌즈 이중 인코딩 버그 (실전 테스트로 발견)**: 프로덕션 DB에 대고 실제 `run_decision()` 전체
  사이클을 돌리는 통합 테스트 중, 자유형 렌즈에서만 `decisions` 필드가 배열이 아니라 전체 JSON을
  문자열로 감싼 값으로 돌아와 `_log_lens_decisions`가 문자를 하나씩 순회하며 크래시함
  (`TypeError: string indices must be integers`). `weekly_perspective` 필드가 섞인 좀 더 복잡한 스키마에서만
  발생 — 재현 확률은 낮지만(반복 호출 3/3은 정상) 실사용에서 걸릴 수 있는 실제 결함이었음. `_DECISION_TOOL`/
  `_FREE_DECISION_TOOL` 양쪽에 `additionalProperties: false`(최상위+배열 아이템 스키마)와 `strict: true`를
  추가해 모델 출력이 스키마를 정확히 따르도록 강제 — 수정 후 자유형 렌즈만 3회 반복 호출해 전부 정상 확인.
- **`run_weekly.py`**: `_get_previous_ai_portfolio`/`_log_ai_decisions`(단일 트랙 하드코딩)를
  `_get_previous_lens_portfolio(conn, track_id)`/`_log_lens_decisions(conn, ..., track_id, decisions, weekly_perspective)`로
  일반화. `run_decision()`의 `shortlist_records`에 `_fetch_shortlist_financials`로 이미 수집된 재무지표를
  종목별로 결합한 뒤 `config.LENS_TRACKS` 4개를 순회하며 각자 자기 자신의 지난주 포트폴리오만 참고해 판단.
  반환값이 `decisions`(단일 리스트) → `decisions_by_lens`(트랙ID→리스트 dict)로 바뀜.
- **`benchmark.py`**: `snapshot_ai_track()`(단일 트랙 전용) 제거, `snapshot_all()`이 `config.LENS_TRACKS` 4개를
  기존 공유 함수 `_snapshot_rebalanced_track`으로 순회 처리하도록 확장(④·①·③과 동일한 체결/비용 규칙 공유
  유지). `get_alpha_spread()`가 `track_id` 파라미터를 받도록 바뀌어 4개 렌즈 각각의 ②x−④ 스프레드를
  독립적으로 조회 가능.
- **`risk_metrics.py`**: `rebalanced_tracks`/트랙 순회 목록에 `ai_blind` 대신 `config.LENS_TRACKS` 4개 반영.
- **`telegram_bot.py`**: `_TRACK_LABEL`에 4개 렌즈 라벨(②a~d) 추가, 구버전 `ai_blind`는 "② AI(구버전)"로
  남겨 과거 로그 조회 시에도 라벨이 깨지지 않게 함. `/latest`는 렌즈별로 메시지를 나눠 전송(자유형은
  `weekly_perspective` 선언도 함께 표시), `/history`는 트랙 목록을 동적으로 조립(하드코딩된 4컬럼 → 7컬럼
  일반화), `/alpha`는 4개 렌즈 각각의 스프레드를 순회 전송. `decision_job`도 `decisions_by_lens` 구조에
  맞춰 렌즈별로 판단 요약을 나눠 표시하도록 수정.
- **프로덕션 DB 대상 실전 통합 테스트**: 사용자 승인 하에 `data/shadow_track.db`를 미리 백업한 뒤(안전장치),
  장전 가드(`assert_before_market_open`)만 이번 검증 1회에 한해 우회해서(코드는 그대로 두고 프로세스
  내 몽키패치로만) 실제 스크리너(40종목)→DART(40/40 커버리지)→뉴스→LLM 4회 호출→`run_execution()`→
  `risk_metrics.compute_and_log()`까지 전체 사이클을 실행. 4개 렌즈 전부 정상적으로 종목을 골랐고(가치=기아/현대차
  중심, 모멘텀=반도체 장비주 중심, 퀄리티=SK하이닉스/삼성전자 중심, 자유형="반도체/AI 하드웨어 슈퍼사이클+
  최소 퀄리티 필터" 관점 선언), `snapshot_all`/`get_alpha_spread`/`risk_metrics` 모두 7개 트랙(①+④렌즈+③+④)에
  대해 정상 기록됨을 확인. 이 실행으로 실제 주차(2026-W29)에 진짜 판단 로그가 하나 남았음 — 다음 화요일
  실전 배치와 겹치지 않는지 배포 전에 확인 필요.

## 가치·퀄리티 렌즈에 업종 맥락 추가 (2026-07-16 9차)
사용자가 재무 수치를 업종 맥락 없이 기계적으로 해석하는 문제를 지적 — 은행/지주회사뿐 아니라 보험·리츠까지
포함해서 업종 정보 자체를 프롬프트에 제공하도록 확장.
- **업종 데이터 소스 확인**: `data_collector.get_universe_snapshot()`이 이미 `fdr.StockListing("KRX-DESC")`로
  `Industry` 컬럼을 가져와 유니버스 스냅샷에 merge하고 있었음(다양화 클러스터링에는 못 썼던 그 필드 —
  삼성전자가 "통신 및 방송 장비 제조업"으로 등록되는 등 일반 업종 분류로는 부정확하다고 이전에 확인됨).
  하지만 금융/보험/지주/리츠 판별이라는 **좁은 용도**로는 실제 데이터로 검증한 결과 신뢰할 만함 — 은행은
  "은행 및 저축기관", 보험사는 "보험업", 금융지주(신한지주·KB금융·SK스퀘어 등)는 "기타 금융업", 리츠는
  "부동산 임대 및 공급업"(일부는 "신탁업 및 집합투자업")으로 일관되게 분류됨. `screener.py`가 컬럼을
  드롭하지 않아 `shortlist_df`까지 `Industry`가 그대로 살아있음을 직접 확인 후 진행.
- **`run_weekly.py`**: `shortlist_records` 생성 시 `Industry` 컬럼을 `industry`로 포함해 `judge()`에 전달.
  DB 스키마 변경은 안 함(프롬프트 인풋 목적이라 로깅까지는 필요 없다고 판단, 필요해지면 나중에 추가).
- **`llm_judge.py`**: `_build_user_prompt()`가 종목명 옆에 `[업종: ...]`을 표시. `_COMMON_FRAMING`의 재무
  해석 주의 문구를 은행/지주 2개 카테고리에서 **금융업(은행/보험/증권)·금융지주·리츠 3개 카테고리**로
  확장하고, 부채비율·영업이익률뿐 아니라 **PBR 해석 차이**(리츠는 자산 대부분이 부동산이라 다른 PBR
  밴드에서 거래됨)까지 추가.
- **검증**: 삼성전자(제조업)/KB금융(금융지주)/롯데리츠(REIT) 3종목 샘플로 퀄리티 렌즈 재호출 — 셋 다
  업종 맥락에 맞게 해석함을 확인(KB금융 부채비율 1211.7%를 "은행업 특성"으로, 롯데리츠 PBR 0.9배·부채비율
  85%를 "리츠 업종 내 정상 범위"로 정확히 판단).
