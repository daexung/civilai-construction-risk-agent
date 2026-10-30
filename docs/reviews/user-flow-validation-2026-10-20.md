# 사용자 실사용 흐름 검증 — 2026-10-20

## 범위와 실행 판정

요청 범위는 현재 개발본의 A–F 사용자 흐름이며, 전체 품셈 수정·회귀는 하지 않았다. checkout은 `C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\tmp\integration-main-168d80a`, Git HEAD는 `168d80a426d5a348f666a9d2f03153b818e0fec7`이다. 기존 작업 트리 변경은 보존했다. 이번 검증에서 추가로 수정한 제품 코드는 없다.

현재 project checkout 기준으로 API·프런트엔드 서버는 실행 중이지 않았다. 상위 저장소의 Python `.venv`는 있고 Node/npm은 있으나 `frontend/node_modules`는 없다. 브라우저에는 이 프로젝트가 열린 탭이 없었다. React 개발 서버는 실행되지 않아 실제 UI와 새로고침을 확인하지 못했다. API 시작을 시도했으나 포트 8010에 서비스가 열리지 않았고, health 요청은 약 648ms 뒤 연결 오류로 끝났다. 중단 시 Python/Node 프로세스나 시험 포트 listener는 남아 있지 않았다.

모델 설정은 `backend/agent/tools/llm/config.json`의 Vertex `gemini-3.5-flash-lite`다. 인증 항목은 상위 저장소 `.env`에 존재하지만 task checkout의 `backend.paths.ROOT`는 해당 파일을 자동으로 읽지 않는다. 키 값은 표시·기록하지 않았다. 기존 표준 견적 API의 채팅 경로는 `usage_limits.processing/consume`에서 요청 사용량을 DB에 기록한다. 상위 `.env`의 대화 DB endpoint는 원격 Supabase pooler이므로 이번 검증에 사용하지 않았다. DB 없는 요청은 503 경로로 중단되고, 원격 DB로 호출하면 승인된 범위(운영 DB 변경 금지)를 벗어난다.

별도 `local_trial` 경로는 원격 저장 없이 검색 답변을 하도록 설계됐지만, 코드 상 호출/비용 상한은 30회/$1이고 승인 한도는 20회/$2다. 이 경로의 retrieval은 `127.0.0.1:54322/civilai_rag_verify`의 전용 읽기 전용 로컬 DB를 필요로 하며 해당 포트 listener도 없었다. 기본 서비스는 턴당 LLM 시도 상한 6회만 있고, 전체 6개 시나리오를 합산하는 $2/20회 장부·예약기는 확인되지 않았다. 따라서 요청 전에 실제 최대 누적 비용·재시도 수를 안전하게 보장할 수 없었다. 이 사유로 모델 생성 요청은 전송하지 않았다.

## 가격·호출 장부

Google Cloud 공식 가격표에서 Gemini 3.5 Flash-Lite는 Global 기준 입력 $0.30/1M tokens, 텍스트 출력(추론 포함) $2.50/1M tokens이며 Non-global 표시는 각각 $0.33/$2.75다. 현재 서비스의 실제 endpoint region과 토큰량을 확인하지 못해 보수적인 Non-global 단가를 상한 추정에 써야 한다. [공식 Vertex AI 가격표](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing?authuser=3)

코드상 일반 답변 생성기는 기본 최대 출력 4,096 tokens·최대 3회 시도를 허용한다. 견적 그래프는 LLM 요청별 최대 2회, 턴 전체 최대 6회 시도로 제한한다. 별도 retrieval 선택기는 최대 출력 8,192 tokens·요청별 최대 2회 시도를 설정한다. 위 Non-global 단가 기준 출력만 최대치로 계산하면 일반 답변 생성기 한 번은 출력만 최대 약 $0.0113, retrieval 선택기 한 번은 출력만 최대 약 $0.0226이며 입력 비용이 추가된다. 견적 그래프 요청은 최대 2회 시도 기준 출력 상한을 계산해야 한다. 실제 입력 토큰을 미리 측정·예약하지 않았고, 전체 대화에 적용되는 상한 장부도 없어 6개 시나리오 예산으로 승인할 수 없었다. 생성 요청은 0회이므로 이번 검증 사용량은 **0회 / $0 추정 사용액**이다. 이는 청구액 확인이 아니라 호출 기록에 기반한 추정이며 청구 시스템은 조회하지 않았다.

이번 run 전용 `ledger_05b.jsonl` 및 `trial_log.jsonl`은 생성되지 않았다. 과거 평가 비용은 이번 장부와 분리해야 하나, 저장소에는 과거 평가 전체를 합산하는 청구 장부가 확인되지 않아 **과거 평가 비용은 미상**이다. 이번 run에서 미리 예약한 금액은 없다.

## 시나리오 결과

| 시나리오 | 상태 | 실제 질문·응답/조건 | 결과·근거 |
|---|---|---|---|
| A. 콘크리트 100㎥ 단일 견적 | 미실행 | 요청 문구를 API/UI에 제출하지 않음 | 모델 호출 전 실행 경로·예산 차단. 공종/조건/표/계산/금액/Excel 미확인. 응답 시간·오류 N/A |
| B. 콘크리트 100㎥ + 거푸집 200㎡ | 미실행 | 요청 문구를 제출하지 않음 | A와 동일. 항목별 질문·계산·합계·공통비용 중복·미산정 항목·Excel 미확인 |
| C. 거푸집 7m·양중장비 미사용 → 10m | 미실행 | B 대화가 없어 조건을 설정·변경하지 않음 | 보정 규칙, 시스템 가정, 물량 유지, 작업량/일수/인력/금액 변화 모두 미확인 |
| D. 콘크리트 100㎥ → 120㎥ | 미실행 | B 대화가 없어 물량 수정하지 않음 | 거푸집 보존, 재계산, 합계 및 Excel 갱신 미확인 |
| E. 새로고침 후 복원·수정 | 미실행 | 프로젝트 UI 서버가 실행되지 않아 브라우저 새로고침 안 함 | 화면/API/Excel 일치 미확인 |
| F. D16 앵커 적용 가능 여부 | 미실행 | 질문을 검색 API에 제출하지 않음 | 격리 retrieval DB가 내려가 있고 호출 상한을 승인치로 제한할 수 없어 모델 요청 금지. 대상·조건 이해, 근거 제시 미확인 |

시험 현장값은 제출하지 않았다. 선택된 공종·명세·표·규칙이 없고 계산 출력도 없으므로 독립 기대값 계산, 실제값과의 비교, 원문 계산 정확성 판정은 수행하지 않았다. 대화 응답 기록이나 Excel 파일 경로는 없다.

## 확인된 사용자 경험·계산 상태

**실제 확인된 것:** 현재 task checkout에서 사용자 UI/API가 기동되지 않았다. 이는 계산 오류가 아니라 실행환경 차단이다. 실제 견적 시나리오가 0개여서 계산 성공이나 오류를 주장할 근거가 없다.

**코드 문서로 확인했으나 브라우저 실험은 안 한 것:** `frontend/README.md`는 비회원 대화를 현재 탭 메모리에 두고, 서버 쪽 상태는 `MemorySaver`라 서버 재시작 후 복원되지 않는다고 설명한다. 따라서 새로고침 후 복원 시나리오 E는 실패 위험이 높은 미검증 항목이다. 이번에는 화면 동작을 실제로 보지 않았으므로 제품 실패로 확정하지 않는다.

**계산 정확성:** 판정 불가. 원문 표·비고, 물량 단위·조건, 계산 추적, Excel 어느 것도 사용자 흐름에서 확인하지 못했다. 확인하지 못한 결과를 통과로 집계하지 않는다.

## 재현 및 우선순위

- 재현 질문과 승인 시험 조건은 사용자 요청의 A–F 문구 그대로다. 이번 실행에서는 어떤 질문도 모델/API에 보내지 않았다.
- 현재 대화 기록/trace 및 Excel 산출물은 없다. `experiments/retrieval-v1/pilots/step05b/ledger_05b.jsonl`와 `trial_log.jsonl`도 없다.
- **P0 — 실행 경로와 예산 격리:** 원격 Supabase를 쓰지 않는 전용 로컬 개발 DB와 UI/API를 제공하고, 전체 run에 걸쳐 모든 생성·선택·검색·재시도 호출을 합산하는 20회·$2 하드 상한과 요청 전 최대 비용 예약을 확인할 수 있어야 한다. 현재 `local_trial`의 30회 설정도 승인 한도와 맞지 않는다.
- **P1 — 브라우저 흐름 복원:** 게스트 대화가 새로고침 후 복원 가능한지 실제로 재검증한다. README의 메모리 보관 설명이 현재 UI 동작과 일치하는지 먼저 확인한다.
- **P1 — 프런트엔드 실행환경:** 잠금 파일에 맞는 로컬 의존성을 제공해 채팅 화면·수정·Excel 다운로드 흐름을 시험할 수 있어야 한다.
- **P2 — 실제 계산 정확성:** 실행 격리와 UI가 준비된 뒤 A–D에서 선택 원문 표·비고를 독립 계산해 대조하고, F에서는 적용 가능 여부를 조건부로 답하며 원문 근거를 제시하는지 확인한다.

다음 범위는 미확인이다: 여섯 시나리오 전체, API/브라우저 응답 시간, 검색·명세 선택 품질, 모든 조건 질문의 적절성, 합계·비용 중복 처리, 원가·금액, Excel 내용, 화면/API 일치, 새로고침 후 복원, 모델 청구액. 이번 검증은 전체 품셈 정확도나 릴리스 적합성을 평가하지 않는다.



## 재개 확인 — 2026-10-20 추가 점검

이번 이어가기에서 기존 판단을 바꿀 수 있는 전용 로컬 실행환경이 있는지 다시 확인했다. checkout의 Git HEAD는 계속 `168d80a426d5a348f666a9d2f03153b818e0fec7`이며, 기존 변경은 903개 `git status --short` 항목으로 관찰됐다. 이 변경을 수정·정리하지 않았다. 해당 경로에서 `frontend/node_modules`는 없고 Docker CLI는 있지만 Docker Desktop Linux engine named pipe에 연결할 수 없어 daemon이 실행 중이지 않다. `docker ps`도 같은 이유로 실패했다. API/UI 및 PostgreSQL/RAG 확인 포트(3000, 5173, 8000, 8001, 8010, 5432, 54322)에 listener가 없으며, 검사 후 남아 있는 Python/Node/Docker 실행 프로세스도 확인되지 않았다.

따라서 전용 local RAG DB를 시작하거나 기존 서비스를 재사용하는 실행 경로를 찾지 못했다. 상위 저장소의 원격 Supabase 설정을 쓰지 않았고, 오프라인 프런트엔드 설치를 시도하지 않았다. A–F에 대한 실제 질문·답변, 응답 시간, 검색 결과, 계산·Excel 및 브라우저 새로고침 증거는 여전히 없다. 이번 확인에서도 모델 호출 0회, 신규 사용액 추정 $0이며, 이는 청구액 확인이 아니다. 모델 호출 없이 제한을 우회하는 시뮬레이션을 실사용 검증으로 계산하지 않았다.

**재개 조건:** Docker Desktop/local test DB를 안전하게 실행할 수 있거나, 원격 DB를 전혀 쓰지 않는 지원된 개발 저장소 설정이 제공되어 API usage 기록 및 RAG 읽기를 모두 로컬로 수행할 수 있어야 한다. 실제 모델 호출을 재개하기 전에는 내부 모든 LLM 호출·재시도를 하나의 20회/$2 장부로 묶고 호출별 최대 입력·출력 비용을 사전 예약할 수 있음을 확인해야 한다. 프런트엔드 패키지는 lockfile에 맞는 오프라인 캐시가 확인되기 전까지 설치하지 않는다.

## 2026-10-20 재개 시도 — 실행환경 준비에서 외부 차단

이번 사용자의 승인에 따라 설치·로컬 실행을 실제로 시도했다. 시도 전 코드 경로 확인 결과:
- 기본 `/api/chat` 경로는 `CHAT_DATABASE_URL`의 PostgreSQL을 사용한다. `backend/api/usage_limits.py`의 `processing()`은 `pg_try_advisory_lock`으로 동시 요청을 막고 `consume()`은 `agent_state.daily_chat_usage`와 `agent_state.chat_request_charges`에 차감·중복 방지를 기록한다. `main.py` 시작 시 `require_request_charges()`가 해당 마이그레이션 적용을 확인한다. 대화 저장도 같은 CHAT DB 경로를 쓴다. 승인되지 않은 상위 `.env`의 원격 Supabase 주소는 읽기/쓰기 연결에 사용하지 않았다.
- 독립 local-trial은 `experiments/retrieval-v1/src/db.py`의 로컬 기본 DSN `127.0.0.1:54322/civilai_rag_verify` 또는 `RAG_DATABASE_URL`로 PostgreSQL의 `rag_knowledge` 릴리스·청크·검색 레코드를 읽는다. 이는 빈 DB나 mock으로 대체하면 정상 검색 흐름이 아니다. 기본 `CAPS`는 30회/$1이고, 이번 승인에 맞춘 20회 전역 장부가 구성되기 전에는 호출하지 않았다.
- 마이그레이션은 repo의 `supabase/migrations`와 retrieval `sql/20261011000100_rag_knowledge.sql`, `sql/20261011000200_rag_search_records.sql`에 존재한다. Docker 기반 local Supabase 이외에 사용할 기존 PostgreSQL/supabase 실행 파일은 PATH 및 `C:\Program Files\PostgreSQL`에서 발견되지 않았다. Docker가 기동되지 않아 이 마이그레이션이나 공개 코퍼스를 DB에 적용하지 않았다.

### 실제 실행 시도와 실패

1. `frontend`에서 `npm ci --offline` 실행 — exit 1, Windows `EPERM`으로 `frontend/node_modules/eslint-plugin-react/node_modules` 생성 불가. 같은 시점 npm cache는 `Content verified: 0 (0 bytes), Index entries: 0`이었다.
2. `frontend`에서 `npm ci --no-audit --no-fund` 실행 — exit 1, Windows `EPERM`으로 `frontend/node_modules/@xtuc/long` 생성 불가. 따라서 lockfile 의존성 설치는 완료되지 않았다. 두 시도 사이 네트워크 다운로드 문제가 아니라 OS 디렉터리 생성 권한/실행환경 오류로 끝났다. 실패 시도만 만든 불완전 `frontend/node_modules`는 시작 전 존재하지 않았음을 확인한 뒤 제거했다.
3. 기존 설치본 `C:\Program Files\Docker\Docker\Docker Desktop.exe`를 숨김 실행 및 `--unattended`로 기동 시도 — 프로세스는 잠시 실행됐지만 Docker Linux 엔진 named pipe `npipe:////./pipe/dockerDesktopLinuxEngine`가 끝내 열리지 않아 `docker info`/`docker ps` 연결 실패. `wsl --status`는 `Wsl/Service/E_ACCESSDENIED`를 반환했다. 작업 후 Docker Desktop 프로세스는 남지 않았다.
4. 로컬 확인 포트 3000, 5173, 8000, 8001, 8010, 5432, 54322에 서비스 listener가 없다. API나 UI는 기동하지 못했다.

### 시나리오 집계와 사용량

A–F는 모두 **미실행**으로 유지한다. 질문 제출, 모델 응답, 시험 조건 확정, 표 선택, 계산·합계, Excel, 브라우저 새로고침/복원 모두 수행하지 않았다. API/UI 결과가 없으며 실사용 통과 건수는 0/6이다. 실제 모델 요청 0회, 이번 승인 예산의 추정 사용액 $0, 청구액 미조회다. 호출 전에 실행된 요청이 없으므로 재시도·내부 호출도 0회다. 공식 Vertex AI 가격표는 이번 점검에서 재확인했다: Gemini 3.5 Flash-Lite 텍스트 입력은 Global $0.30/백만 토큰, Non-global $0.33/백만 토큰이고 텍스트 출력(추론 포함)은 각각 $2.50/$2.75다. endpoint region과 입력량을 특정하지 못해 실제 요청 비용 예약은 하지 않았다. [공식 Vertex AI 가격표](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)

### 재개에 필요한 실제 외부 조치

현재 막힌 원인은 코드 미비 판정이 아니라 Windows 실행 권한/WSL 가용성이다. 사용자/관리자가 Docker Desktop Linux engine 및 WSL 서비스의 `E_ACCESSDENIED`를 해소하고, 해당 checkout에서 npm이 lockfile 모듈을 생성할 수 있도록 허용한 뒤 다시 실행해야 한다. 재개 시 `.env` 원본을 덮지 않고 시험 전용 env를 만들며 CHAT DB와 RAG DB를 모두 local-only DSN으로 지정하고, local-trial 및 기본 API 전 경로의 재시도까지 합산하는 영속 20회/$2 예약 장부를 호출 전에 확인한다. 이를 집행하지 못하면 생성 호출은 계속 보류한다. 본 실행에서는 제품 계산·검색·UI 코드와 마이그레이션을 수정하지 않았고, 운영 DB, 커밋, 푸시, 배포를 수행하지 않았다.

## 2026-10-20 로컬 실사용 검증 재개 결과 (중단 체크포인트)

이 절은 앞선 환경 미준비 기록을 갱신한다. 요청된 A–F 전체 완료는 아니다. 사용자가 즉시 중단을 지시한 시점까지 실제 브라우저·로컬 API에서 확인한 범위만 기록한다. checkout C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\tmp\integration-main-168d80a, Git HEAD 168d80a426d5a348f666a9d2f03153b818e0fec7. 기존 미커밋·미추적 변경은 보존했고 제품 계산·검색·답변·UI 코드는 수정하지 않았다.

### 로컬 실행 환경과 예산

- 사용자가 띄운 Docker의 로컬 Supabase DB를 재사용했다. API CHAT DB는 상위 .env의 원격 URL 대신 로컬 postgres DB, RAG DB는 별도 로컬 civilai_rag_verify를 지정했다. 운영 Supabase/DB를 호출하거나 수정하지 않았다.
- lockfile 기준 프런트 의존성이 checkout frontend/node_modules에 설치된 것을 확인했다. 상위 저장소 .venv를 사용했다. UI http://localhost:3000 응답 200, API http://127.0.0.1:8000/api/ready 응답 200이었다.
- /api/local-trial/health는 500: local-trial 벡터 manifest 누락(embed_index.py export). 이번 A–F는 표준 /api/chat UI 경로를 사용했으므로 local-trial 검색 검증은 별도로 통과시키지 않았다.
- Vertex gemini-3.5-flash-lite 실제 호출을 전역 파일 장부로 제한했다. 장부 user-flow-validation-2026-10-20/model-call-budget.jsonl: 실제 HTTP 모델 요청 9회, 추정 비용 $0.00552211, 최대 예약액 합계 $0.75417936. 청구 시스템은 조회하지 않았다. 최대 한도 20회/$2 미도달. 장부의 9개 요청은 모두 HTTP 200, usage metadata로 정산 완료였다. 외부 모델 호출은 A/B 채팅 흐름 중 9회에서 끝났고 이후에는 보내지 않았다. 기존 평가 비용은 이번 장부와 분리되며 합계에 포함하지 않았다.
- 공식 비글로벌 단가는 Gemini 3.5 Flash-Lite 입력 $0.33/M, 출력·추론 $2.75/M tokens를 적용했다. [Vertex AI 공식 가격표](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing). 실제 청구액과 구별되는 추정치다.

### 시나리오 결과

| 흐름 | 실제 실행 및 판정 | 원문·계산·화면 근거 |
|---|---|---|
| A. 콘크리트 100㎥ | 부분 확인. 정확한 시작 질문 제출. 서비스가 필요한 조건을 먼저 묻지 않고 “작업을 이번 견적에 포함할까요?”로 시작했다. 포함, 공통 6-1-1 레디믹스트콘크리트, 장비사용 타설, 철근구조물, 산재 소량 아님, 사급을 선택했다. | 화면 산출근거: 기준 일당 55㎥, 100÷55=20/11=1.81818 작업조·일; 콘크리트공 60/11 인·일, 보통인부 20/11 인·일, 굴착기 20/11 대·일. 원문 crop data/processed/sources/p185-t0.png의 장비사용·철근구조물 교차 셀은 55㎥/일, 작업조는 콘크리트공 3인·보통인부 1인·굴착기 1대여서 독립 계산과 일치한다. [원문 표 이미지](../../data/processed/sources/p185-t0.png). 단가대비표는 2026 H2 콘크리트공 276,285원/일, 보통인부 172,698원/일을 표시했다. 1-2-8/1-2-1 소수자리·금액 규칙 적용 결과 화면 단가표는 1㎥ 노무 18,304.1원, 경장비 366.0원, 100㎥ 참고 직접공사비 1,867,000원(10원 단위 절사), 직접노무비 1,830,400원, 도급액 3,574,066원이었다. 사급 레미콘 재료비, 굴착기 경비, 표면마무리, 양생은 미산정으로 표시했다. 도급액은 로컬 개발 기본 현장조건의 제비율을 포함한다. Excel 버튼을 눌렀고 /api/export/<thread>.xlsx는 HTTP 200을 반환했으나 브라우저 저장 파일 경로를 확인하지 못해 workbook 내부 셀 대조는 미확인이다. |
| B. 콘크리트+거푸집 | 부분 확인 후 일일 한도에 막힘. 요청 제출, 두 항목 포함, 공통 6-1-1 및 합판거푸집 6-3-1을 선택했다. 조건 카드 7개 중 콘크리트 장비사용·철근구조물·산재 아님, 거푸집 보통 복잡도·지붕슬래브 아님·상시 크레인 불필요를 선택했다. | “수직고는 몇 m입니까?”는 화면에 숫자 입력 control 없이 일반 텍스트로 나타났다. 사용자가 “수직고 7m, 지붕 슬래브 작업은 아니며 상시 크레인은 사용하지 않습니다.”라고 답하자 앱은 높이 조건 반영 대신 “합계는 유지하고 바꿀 작업을 골라 주세요”로 전환했다. 계산 전이라 합계/공통비 중복/미산정/Excel 항목 대조는 못 했다. |
| C. 거푸집 높이 7→10m | 미실행 — 선행 B 조건 계산 실패 및 비회원 한도. | B 결과가 생성되지 않아 보정·근거·가정·작업일수·인력·금액 변화를 대조하지 못했다. |
| D. 콘크리트 100→120㎥ | 미실행 — 선행 B 계산 및 수정 UI 차단. | 같은 대화에서 항목 변경/재계산 및 거푸집 조건 보존을 확인하지 못했다. |
| E. 새로고침 복원 | 부분 확인. B 대화에서 브라우저 실제 reload를 실행했고, 안내 확인 후 같은 대화의 질문·선택 메시지·최근 응답이 재표시됐다. | 복원 후 입력/선택 control은 비활성이었다. 당시 /api/usage는 비회원 한도 5/5, 잔여 0을 반환했고 사이드바는 “오늘 무료 이용을 모두 사용했어요”를 표시했다. 대화 렌더 복원은 확인했으나 복원 후 수정 가능성은 일일 한도로 미확인이다. |
| F. D16 앵커 적용 질문 | 미실행 — 비회원 일일 한도. | 독립 새 대화로 이동했지만 입력창·예시 질문이 비활성이고 사이드바가 사용량 소진을 표시했다. 질문을 전송하지 않았으며 모델 호출도 추가하지 않았다. 의미 이해·원문 근거는 미확인. |

### 확인된 결함 및 우선순위

1. P1 — 계산 조건 UX: 거푸집 수직고를 묻는 문구에 입력 가능한 control/선택지가 없고, 일반 채팅으로 7m에 답하면 조건 반영 대신 “어느 작업을 바꿀까요?”로 전환되어 계산을 이어갈 수 없었다. B/C/D를 막았다. 재현은 B 저장 대화와 user-flow-validation-2026-10-20의 브라우저/API 기록을 참조한다.
2. P1 — 비회원 일일 한도: /api/usage가 limit=5, used=5, remaining=0을 반환했다. A/B 흐름 도중 추가 진행이 불가했고 F도 보내지 않았다. 테스트 한도·로그인·quota를 우회하지 않았다.
3. P2 — Excel 검증 공백: export endpoint는 HTTP 200이었지만 파일 경로를 찾지 못해 Excel 항목/합계 셀과 화면 대조는 미확인이다.
4. 별도 환경 문제: local-trial health가 벡터 manifest 누락으로 500. 표준 채팅 흐름 결과와 섞지 않는다.

### 재현 자료와 중단 상태

- 선택 조건: user-flow-validation-2026-10-20/scenario-conditions.md. A 선택: 6-1-1·장비사용·철근구조물·소량 산재 아님·사급. B 선택: 6-1-1·6-3-1·장비사용·철근구조물·소량 산재 아님·보통 복잡도·지붕 슬래브 아님·크레인 미사용. 7m 자유 입력은 반영되지 않음.
- 요청·비용 장부: user-flow-validation-2026-10-20/model-call-budget.jsonl. 인증값·프롬프트는 기록하지 않는다. API 로그 api.stdout.log, api.stderr.log; UI 로그 ui.stdout.log, ui.stderr.log.
- A 부분 실행, B 부분 실행, E 부분 복원 확인, C/D/F 미실행이다. 기본 실행 성공과 원문 표/물량 규칙 대조를 구분하며 계산 전체 규칙 검증 완료로 간주하지 않는다.
- 중단 지시 시 외부 생성 요청은 진행 중이지 않았다. 이 보고 반영 뒤 내가 띄운 로컬 API/UI 프로세스만 종료한다. 사용자가 띄운 Docker, 기존 미커밋·미추적 작업물, 로컬 DB 자료는 보존한다.
