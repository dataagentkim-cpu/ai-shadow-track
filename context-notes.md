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
- ② AI 트랙은 매주 직전 주 목표비중대로 그 주간 수익률을 반영한 뒤, 이번 주 새 판단으로 리밸런싱하는 방식(매주 완전 리밸런싱 가정).

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
- 내 보유(①)/지수(③) 트랙은 손대지 않음 — 그 트랙들은 매주 새로 트레이딩 결정을 내리는 게 아니라서 애초에 look-ahead 편향도, 매주 거래비용도 해당 없음.

## 레포 공개 범위와 개인 데이터 분리
- 사용자의 다른 레포들은 다 public이라 이 프로젝트도 처음엔 public + db 커밋 방침으로 갔었음.
- 그런데 `data/shadow_track.db`에는 실제 보유 종목명/수량/평가금액이 그대로 담겨 있어서, public 레포에 커밋하면 사용자의 실제 자산 정보가 공개됨 — API 키 문제가 아니라 개인 재무 데이터 노출 문제라 별개로 처리.
- 최종 결정: 레포는 public 유지, 대신 db 파일 자체를 `.gitignore`에 추가하고 git 히스토리에서도 완전히 제거 (당시 아직 push 전이었어서 `.git` 재초기화로 간단히 해결). db는 EC2 서버 로컬 디스크에만 존재.
