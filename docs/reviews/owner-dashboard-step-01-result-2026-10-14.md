# 운영자 대시보드 1단계 결과

작성일: 2026-10-14
작업 브랜치: `codex/owner-dashboard`
시작 기준: `origin/main` (`046efc4aefbac66c84c20b4ba409443ff41b9cb1`)
작업 위치: `C:\Users\user\.codex\worktrees\owner-dashboard-0609\civilai-construction-risk-agent`

## 구현 내용

- `/admin` 화면과 백엔드 `/api/admin/*` 읽기 전용 API를 추가했다.
- 운영자 API는 기존 Supabase `/auth/v1/user` 토큰 검증과 탈퇴 처리 계정 차단을 재사용한다. 서버 환경 변수 `ADMIN_USER_IDS`에 등록한 UUID만 허용한다. 값이 없으면 403, UUID 형식이 잘못되면 503으로 차단한다. 브라우저가 보낸 사용자 ID·이메일·역할은 권한 판단에 쓰지 않는다. 실제 운영자 UUID는 지정하거나 등록하지 않았다.
- 관리자 API 응답에 `Cache-Control: private, no-store`, `Pragma: no-cache`, `X-Robots-Tag: noindex, nofollow, noarchive`를 적용했다. Vercel의 `/admin`·`/api/admin` 경로에도 캐시 금지와 검색 제외 헤더를 설정했다. 기존 홈페이지 메타·사이트맵·상담 경로 규칙은 건드리지 않았다.
- 요약·답변 평가 목록/상세·일반 의견 목록/상세·실행 목록/상세를 제공한다. 목록은 50개 단위 서버 페이지네이션과 날짜·상태 필터를 쓰며, 본문은 선택한 상세에서만 반환한다. 평가·실행 목록에는 질문·답변과 이메일을 넣지 않는다.
- 실행 상세는 연결된 답변 평가, 단계 순서와 부모, 상태·시간·요약·오류·호출 메타데이터를 보여 준다. 과거 평가의 실행 연결이 비어 있으면 당시 실행을 추정해 붙이지 않는다. 조회를 위해 모델을 다시 호출하지 않는다.
- 화면은 기간 변경, 탭 전환, 새로고침과 60초 간격 갱신을 지원한다. 숨겨진 탭의 반복 조회는 중단한다. 계정 변경·로그아웃·기간·필터·페이지 변경 때 이전 상세를 지우며, 늦게 도착한 과거 상세 응답이 화면을 덮지 못하게 했다. 같은 계정의 인증 갱신은 화면을 비우지 않고 다시 조회한다.
- 평가 이유 필터는 `amount`를 ‘금액’, `evidence`를 ‘근거’, `understanding`을 ‘질문 이해’로 표시한다.
- PostHog 방문 통계는 서버 조회가 연결되지 않아 “연결되지 않음”으로 표시한다. 방문·검색 실적을 추정하지 않는다.

### 지표 정의와 원천

- 기간은 한국 시간 `Asia/Seoul`의 오늘 또는 오늘을 포함한 7일·30일 달력 구간이다. 시작 시각은 포함하고 조회 시각은 제외한다. 응답에 집계 시작·기준 시각을 반환한다.
- 현재 가입자는 `auth.users` 중 `is_anonymous=false`인 계정이며, 삭제된 계정은 인증 테이블에서 제거된 것으로 본다. 신규 가입은 같은 기간 `auth.users.created_at` 기준이다.
- 실행은 `answer_runs.environment='production'`이며 `started_at`이 기간에 든 건만 센다. 완료·실패·진행 중·미완료 상태를 분리한다. 실행 완료는 답변 정확도를 뜻하지 않는다.
- 처리 시간은 완료 실행의 `answer_run_steps` 중 `step_kind='answer'`, `name='answer_summary'` 단계의 `duration_ms`만 사용한다. 시간 미수집 건은 0으로 넣지 않으며 p50·p95와 표본 수를 표시한다.
- 긍정·부정·검토 대기 수는 `answer_feedback`의 생성 시각 기준이다. 검토 대기는 `review_status <> 'resolved'`다. 일반 의견 수는 `feedback`의 생성 시각 기준이다. 날짜별 추이는 실행 시작 시각을 한국 시간 날짜로 묶는다.
- 대화 `messages` 수를 전체 질문 수로 표시하지 않는다. 실행 로그가 생기기 전 요청이나 인증·한도 차단 요청, 비회원의 전체 대화는 포함되지 않을 수 있다.
- 실행, 평가, 일반 의견은 별도 쿼리로 집계해 단계 조인 때문에 수가 부풀지 않게 했다. 처리 시간 집계만 실행별 답변 요약 단계와 연결한다.

## 변경 파일

- `backend/api/admin.py`: 서버 인증 허용 목록, 기간 계산, 요약·목록·상세 SQL API.
- `backend/api/main.py`: 관리자 라우터와 관리자 API 보안 헤더 미들웨어 연결.
- `frontend/src/OwnerDashboard.tsx`, `frontend/src/OwnerDashboard.css`: 화면, 필터, 갱신, 상세 표시와 상세 초기화.
- `frontend/src/adminApi.ts`: Supabase 세션 토큰 전달을 위한 호출부.
- `frontend/src/index.tsx`: `/admin`에서 채팅 앱 대신 대시보드만 마운트해 기존 대화 복원 효과가 실행되지 않도록 분리.
- `frontend/src/App.tsx`: `/admin` 경로 연결.
- `frontend/vercel.json`: 관리자 화면/API 검색 제외와 캐시 금지 헤더.
- `frontend/server/cloud-run.cjs`: 백엔드 `X-Robots-Tag` 응답 헤더 전달.
- `evals/test_admin_dashboard.py`: 권한·입력 제한 검사.
- `docs/reviews/owner-dashboard-step-01-result-2026-10-14.md`: 이 결과 보고서.
- 요청에 따라 지시서와 계획서 두 파일을 원본 저장소에서 새 worktree로 복사했다.

DB 스키마나 마이그레이션은 수정하지 않았다. 로그 테이블의 RLS·일반 역할 권한 회수 정책도 바꾸지 않았다. 검토 수정과 평가 사례 승인·내보내기는 이번 범위에 넣지 않았다.

## 로컬 검증

- `evals/test_admin_dashboard.py`, `evals/test_answer_runs.py`, `evals/test_answer_trace_lifecycle.py`: 최신 재실행 **14개 통과, 3개 건너뜀**. 기존 저장소의 `.venv`와 검사 의존성을 읽기 전용으로 사용했다. 모델 호출은 비활성화했다. Python 의존성에서 Python 3.16 관련 폐기 예정 경고 13개가 있었고 실패는 없었다.
- 시험 자료를 쓰기 전에 DB 원천 행에서 오늘·7일·30일 기대값을 계산해 고정했다. 그 뒤 실제 관리자 API 결과와 비교해 실행 상태·평가·일반 의견·처리 시간·날짜별 추이가 모두 일치했다. KST 자정 전날(10월 13일) 미완료 실행 1건과 자정 이후(10월 14일) 완료 2건·실패 1건이 각 기간에 올바르게 집계됐다. 실제 표본은 실행 4건(완료 2·실패 1·미완료 1), 평가 3건(긍정 1·부정 2), 일반 의견 52건이었다. 일반 의견 52건은 실제 페이지 2개와 두 번째 페이지 2건을 확인하기 위한 가상 자료였다.
- 연결 평가 상세에서 4단계 실행을 열었고, 생성 전 실패 상세에서 실패한 두 단계와 오류 표시를 확인했다. 실행 연결이 없는 과거 평가는 ‘당시 실행 기록 없음’으로 표시했다. `amount` 필터는 1건을 반환했으며 화면 문구는 ‘금액’이었다. 익명 요청은 401, 일반 회원은 요약·평가·의견·실행 목록 모두 403이었고, 일반 회원이 `X-User-ID`·역할 헤더로 운영자를 가장해도 차단됐다.
- Supabase 로컬 이메일 로그인 공급자가 비활성화되어 비밀번호 로그인은 422(`email_provider_disabled`)였다. 실제 로컬 Auth 사용자를 만들고, 로컬 Auth가 검증하는 짧은 만료 JWT와 세션으로만 시험했다. 한 브라우저의 다른 탭에서 같은 운영자 사용자의 새 JWT 세션을 설정한 뒤 원래 대시보드가 기존 화면을 유지하고 다시 조회하는 것을 확인했다. 정식 refresh-token 교환 자체는 실행하지 않았다. 실제 운영자 계정은 지정하거나 등록하지 않았다.
- 로컬 PostgreSQL 카탈로그에서 `answer_runs`, `answer_run_steps`, `answer_feedback`, `feedback` 모두 RLS가 켜져 있고 `anon`·`authenticated`의 SELECT 권한이 없는 것을 확인했다.
- 프런트 `npm run build`: **성공**, 기존 홈페이지 사전 생성도 완료했다. `npm ci --offline --ignore-scripts`로 잠금 파일 기준 의존성을 설치했다. 기존 의존성 소스맵 파일 누락과 Node `fs.F_OK` 폐기 예정 경고가 출력됐으며 대시보드 컴파일 오류는 없었다.
- 브라우저에서 자료가 있는 운영자 요약, 오늘/최근 7일 변경, 연결된 평가와 단계, 미연결 과거 평가, 실패 상세, 이유 필터, 일반 의견 상세와 2페이지 이동을 확인했다. 기간·필터·페이지 변경 직후 이전 상세가 사라졌다. 로그아웃 후 로그인 안내만 남았고 자료가 제거됐다. 일반 회원 화면은 권한 거부였다. 390×844 모바일 뷰포트에서 요약 카드·메뉴가 표시됐고 가로 넘침 없이 읽을 수 있었다. 브라우저 콘솔 오류는 없었다.
- `npm start`는 현재 CRA/Webpack 개발 서버의 `allowedHosts[0]` 옵션 오류로 시작하지 않았다. 성공한 최종 운영 빌드의 로컬 정적 미리보기로 `/admin` 경로를 확인했다.
- `git diff --check`: 통과. 홈페이지 사전 생성 HTML의 기존 메타와 내용은 유지됐다.

## 제한과 운영 준비

- 실제 운영자 계정은 지정되지 않았다. 운영 API 활성화 전 Cloud Run 서버 환경 변수 `ADMIN_USER_IDS`에 확인된 Supabase 인증 UUID를 넣어야 한다. 브라우저 번들이나 공개 변수에는 넣지 않는다. 현재 기본 상태는 모든 로그인 사용자 차단이다.
- PostHog 서버 조회가 연결되기 전 방문·페이지 조회 통계는 제공하지 않는다. 실제 사람 수, 검색 유입·순위, 전체 상담 수를 추정하지 않는다.
- 별도 API 지연 벤치마크와 대시보드 응답 크기는 측정하지 않았다. 새 로그 적재는 추가하지 않아 기존 로그 보관량을 늘리지 않는다. 응답은 요약, 50건 이하 목록 또는 선택 상세 한 건으로 제한했다.
- 관리자 API 로컬 검증 서버는 대시보드 라우트만 확인하도록 FastAPI lifespan을 끄고 실행했다. 이 worktree에 기존 무시 파일 `data/processed/page_map.json`이 없어 전체 앱 초기화가 준비 단계에서 실패했기 때문이다. 따라서 같은 로컬 실행에서 채팅 API·자료 인덱스 준비까지 검증한 것은 아니다. 관리자 화면/API는 해당 초기화에 의존하지 않고 실제 응답을 확인했다.
- 로컬 Auth의 실제 refresh-token grant/회전은 이메일 공급자 설정 제약으로 검증하지 않았다. 같은 사용자 세션이 바뀌었을 때 화면을 보존하고 다시 조회하는 경로는 브라우저 교차 탭으로 확인했다.

## 운영 변경 여부

- 프로젝트 로컬 Supabase에만 고유한 가상 시험 계정 2개, 실행 4건, 단계 8건, 평가 3건, 의견 52건을 만들고 API·화면 확인 후 모두 삭제했다. 종료 확인 쿼리에서 시험 계정·실행·평가·의견 표식은 각각 0건이었고 브라우저 미리보기/API 테스트 포트도 닫혔다. 시험 자료 외 기존 로컬 자료는 삭제하지 않았다. 운영 DB·원격 설정·마이그레이션은 변경하지 않았다.
- 외부 모델 호출 0회, PostHog 원격 조회 0회.
- 커밋·푸시·PR·머지·배포를 하지 않았다. 검토를 위해 이 상태에서 멈춘다.

## 로컬 재검증 안내

새 worktree PowerShell에서 기존 Python 검사 환경과 로컬 Supabase 연결을 별도로 준비한 뒤 실행한다. 연결 정보는 이 문서나 저장소에 적지 말고 로컬 환경에서만 설정한다.

```powershell
$env:PYTHONPATH="$PWD;C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\tmp\pr-check-deps"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:AGENT_OFFLINE='1'
$env:AGENT_LLM='off'
$env:QUOTA_HASH_SECRET='local-only-test-value'
C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\.venv\Scripts\python.exe -m pytest evals\test_admin_dashboard.py evals\test_answer_runs.py evals\test_answer_trace_lifecycle.py -q --tb=short
cd frontend
npm run build
```


## PR 준비 검토

- 별도 검토에서 로컬 DB 연결을 명시해 관리자·로그·생명주기 검사를 다시 실행했고 17개가 모두 통과했다. 앞선 3개 건너뜀은 로컬 DB 연결 미설정 조건 때문이었다.
- 실제 운영자 허용 UUID는 공개 코드에 넣지 않는다. GitHub 저장소 변수 `ADMIN_USER_IDS`를 기존 백엔드 배포에서 Cloud Run 서버 환경 변수로 전달한다. 값이 없으면 기본 접근 차단을 유지한다. 여러 UUID를 구분하는 쉼표가 배포 변수 구문과 충돌하지 않게 구분자를 별도로 사용한다.
- 실제 계정 허용 설정과 운영 로그인 확인은 계정 확인 후 수행한다. 실제 토큰 자동 갱신은 아직 미확인이다.
- PR 준비 중 기존 프런트 검사 71개와 Cloud Run 프록시 검사 4개가 통과했다. Windows 경로에서 기본 Jest 파일 탐색이 실패해 테스트 패턴을 명시하여 실행했다. 가짜 타이머 정리 경고가 있었고 실패는 없었다.
