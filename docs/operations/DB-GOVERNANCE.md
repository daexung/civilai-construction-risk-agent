# DB 거버넌스

기준: 저장소의 13개 Supabase 마이그레이션과 API·지식 검색 코드를 읽어 정리했다. 운영 DB에 접속하지 않았으며 실제 데이터의 존재·건수는 확인하지 않았다. 아래의 “코드 사용”은 검색한 파일 기준이다.

## 1. 테이블 목록

| 스키마.테이블 | 생성 마이그레이션 | 목적·주요 컬럼 | 쓰는 코드 | 읽는 코드 |
|---|---|---|---|---|
| auth.users | Supabase Auth(외부 관리) | 회원 UUID, 이메일 등 인증 데이터 | Supabase Auth 흐름; `backend/api/accounts.py` 탈퇴 | JWT 검증·회원 식별 경로 |
| public.profiles | `20261006000100_chat_foundation.sql` | 프로필: user_id, display_name, created_at | `backend/api/chat_storage.py` | `backend/api/chat_storage.py` |
| public.conversations | 동일 | 회원 대화: id, user_id, title, created_at, updated_at | `backend/api/chat_storage.py` | `backend/api/chat_storage.py`, `backend/api/accounts.py` |
| public.messages | 동일 | 대화 전문: conversation_id, request_id, role, content, payload, created_at | `backend/api/chat_storage.py` | `backend/api/chat_storage.py`, `backend/api/answer_feedback.py`, `backend/api/admin.py` |
| agent_state.* (LangGraph 체크포인트) | 001에서 스키마 생성, PostgresSaver가 내부 테이블 생성 | 회원 그래프 상태·중간 실행 상태; 구체 컬럼은 라이브러리 생성 | `backend/api/chat_storage.py` | `backend/api/chat_storage.py`, `backend/api/accounts.py` |
| agent_state.guest_imports | `20261006000200_guest_import_receipts.sql` | 비회원 대화 이전 영수증: source_id, secret_hash, user_id, conversation_id, created_at | `backend/api/chat_storage.py` | 동일 |
| agent_state.daily_chat_usage | `20261006000300_daily_chat_usage.sql` | 날짜별 한도: usage_day, HMAC subject, used | `backend/api/usage_limits.py` | 동일 |
| public.feedback | `20261006000400_feedback.sql` | 의견: id, user_id, subject, category, message, status, created_at | `backend/api/feedback.py` | 관리자 Table Editor; API는 접수 확인 |
| agent_state.daily_feedback_usage | 동일 | 피드백 제한 집계: usage_day, HMAC subject, used, last_at | `backend/api/feedback.py` | 동일 |
| agent_state.account_deletion_challenges / account_deletions | `20261006000500_account_deletion.sql` | 탈퇴 확인 challenge 및 재시도 삭제 작업(대화·피드백 ID 배열) | `backend/api/accounts.py` | 동일 |
| public.answer_feedback | `20261006000600_answer_feedback.sql`, 확장 `20261014000100_answer_runs.sql`, `20261014000200_answer_run_steps.sql` | 답변 평가: 답변/회원/대화 ID, 평점·사유·의견, 질문·답변 전문, 검토 필드 | `backend/api/answer_feedback.py`, `backend/api/accounts.py` | `backend/api/answer_feedback.py`; 관리자 Table Editor |
| agent_state.daily_answer_feedback_usage | `20261006000600_answer_feedback.sql` | 평가 제한 집계: 날짜, HMAC subject, used | `backend/api/answer_feedback.py` | 동일 |
| agent_state.chat_request_charges | `20261008000100_chat_request_charges.sql` | 요청 중복 청구 방지: request_key(HMAC), usage_day, charged_at | `backend/api/usage_limits.py` | 동일 |
| rag_knowledge.releases / release_channels / documents | `20261011000100_rag_knowledge.sql` | 자료 릴리스, 활성 채널, 문서 메타데이터·해시·경로 | 오프라인 적재 도구; `backend/knowledge/db.py` | `backend/knowledge/db.py`, `backend/knowledge/retrieve.py` |
| rag_knowledge.nodes / sections / toc_entries | 동일 | 문서 구조·목차·페이지·제목·본문 일부 | 오프라인 적재 도구 | `backend/knowledge/evidence.py`, `backend/knowledge/retrieve.py` |
| rag_knowledge.source_records / record_cells / source_relations / edges / edge_candidates / corrections | 동일, 검색기록은 `20261011000200_rag_search_records.sql` | 원문 레코드·관계·근거·정정 | 오프라인 적재 도구 | `backend/knowledge/evidence.py`, `backend/knowledge/retrieve.py` |
| rag_knowledge.search_records | `20261011000200_rag_search_records.sql` | 검색용 텍스트와 출처·절 연결 | 오프라인 색인 적재 | `backend/knowledge/retrieve.py` |
| rag_knowledge.chunks / chunk_sets / chunk_set_chunks | `20261012000100_rag_chunks.sql` | 검색 청크·색인 집합·연결 | 오프라인 적재 도구 | `backend/knowledge/embed_index.py`, `backend/knowledge/retrieve.py` |
| public.answer_runs | `20261014000100_answer_runs.sql`, 확장 `20261014000200_answer_run_steps.sql` | 답변 실행 메타데이터·제한된 JSON 요약·버전·만료시각 | `backend/api/answer_runs.py`, `backend/shared/answer_trace.py` | `backend/api/answer_runs.py`, `backend/api/admin.py` |
| public.answer_run_steps | `20261014000200_answer_run_steps.sql` | 실행 단계별 종류·이름·시간·상태·요약 | `backend/api/answer_runs.py` | `backend/api/answer_runs.py`, `backend/api/admin.py` |

## 2. 개인정보 분류

| 테이블·컬럼 | 분류 | 식별·익명화 여부 |
|---|---|---|
| auth.users.email, id | 이메일·계정 식별자 | 직접 식별. DB 접근 정책은 Supabase Auth 설정에 따름 |
| profiles.user_id, display_name | 사용자 ID·선택 이름 | ID로 계정과 연결 가능 |
| conversations.user_id, title; messages.content, payload | 사용자 ID·대화 제목·질문/답변 원문 | 직접 연결 가능. `messages`에는 질문과 응답 전문이 들어감 |
| guest_imports.user_id, source_id, secret_hash | 회원 ID 및 이전 식별자 | secret_hash는 비밀값 해시지만 익명 데이터로 볼 수 없음 |
| daily_*_usage.subject; chat_request_charges.request_key | 사용량 집계 | HMAC 식별자. 문서도 해시를 익명으로 보지 않음 |
| feedback.user_id, subject, message | 회원 ID(회원인 경우), 의견 본문 | 의견 본문은 이름 등 자발 입력 가능. 비회원 subject는 HMAC |
| answer_feedback.user_id, thread_id, question, answer, comment, review_note, reviewed_by | ID·질문/답변 전문·평가와 검토자 | 비회원 thread_id도 지속 식별 가능성이 있어 익명으로 간주하지 말 것 |
| answer_runs.user_id, conversation_id, thread_id, execution, versions | 회원 연결 ID, 계산 조건·수치·근거 인용·기술 메타데이터 | 실행 trace는 요약·크기 제한이지만 식별 가능 메타데이터이며 일부 원문 조각 포함 가능 |
| answer_run_steps input_summary/output_summary/metadata | 실행 입력·출력의 제한 JSON | `answer_trace.py`는 최대 8KB, 문자열 2,000자 등 제한. 질문 전문이 없다는 보장은 각 호출 값 점검 필요 |
| rag_knowledge.* | 공개 기준 문서와 구조·검색 데이터 | 사용자 데이터가 아님. 문서 원문은 개인정보와 별개 |
| Cloud Run/프록시/제공자 로그 | IP·접속 정보 가능 | 이 저장소의 Supabase 스키마로 확인 불가. 운영 설정 확인 필요 |

별도 “기기 정보” 컬럼은 DB 마이그레이션에서 확인되지 않았다. PostHog 설정은 무작위 브라우저 ID·페이지 경로·브라우저/기기 유형을 이용한다고 `docs/analytics.md` 및 `Privacy.tsx`에 적혀 있다. 비회원 제한은 IP 원문 대신 HMAC을 쓰는 것으로 문서화되어 있다. 서버/프록시가 실제 IP를 처리하지 않는다는 뜻은 아니다.

## 3. 보관·삭제

| 데이터 | 현재 보관 규칙 | 정리·탈퇴 동작 |
|---|---|---|
| profiles, conversations, messages, 체크포인트 | 회원이 대화를 지울 때까지(문서 기준) | 대화 삭제는 메시지와 체크포인트를 함께 지움. 탈퇴는 계정 하드 삭제 및 별도 재시도 큐. 확인: `docs/account-deletion.md`; 마이그레이션 FK cascade |
| guest_imports | 명시 만료 기간 없음 | 회원 탈퇴 cascade. 별도 정리 규칙은 확인되지 않음 |
| daily_chat_usage, daily_feedback_usage, daily_answer_feedback_usage, chat_request_charges | 문서화된 7일 초과 집계 정리 | `docs/account-deletion.md`는 서버 1분 간격 정리라고 설명. 소스 코드에서 각 정리 구현·모든 테이블 포함 여부를 운영 전 확인할 것 |
| feedback | 90일 초과 건은 다음 접수 처리 시 삭제 | 정기 작업 아님. FK는 계정 삭제 중 user_id를 먼저 NULL 처리하지만 `accounts.py` 삭제 작업이 큐에 저장한 feedback ID를 실제 DELETE한다. 미완료 큐는 재시작 후 복구 대상으로 둠 |
| answer_feedback | 90일 초과 평가 정리(문서상 주기 작업) | 회원/대화 FK cascade. 비회원 평가는 회원 탈퇴와 무관. 정리 실행 주기는 코드·배포 근거를 확인할 필요 |
| answer_runs, answer_run_steps | answer_runs.expires_at 기본 90일; 평가에 연결된 실행은 평가 유지 기간까지(Privacy 문구) | 회원/대화 삭제 FK cascade. 실행 기록 정리와 연결 평가 예외를 함께 확인할 것. `answer_runs` 만료 컬럼만으로 자동 삭제되지는 않음 |
| account_deletion_challenges, account_deletions | 만료시각 10분 / 미완료 작업 재시도 후 제거 | challenge·queue는 비공개 schema. 실패 시 재시도 작업이 남을 수 있음 |
| 비회원 임시 대화 | 마지막 요청 후 24시간, 서버 재시작 시 더 일찍 소실 가능 | 서버 메모리 정리. Supabase의 영구 메시지 테이블에는 저장하지 않는다고 persistence 문서에 기재 |
| rag_knowledge.* | 릴리스 교체/운영 정책 | 사용자가 만든 데이터가 아님. 릴리스 단위 관리 |
| PostHog 이벤트 | analytics 문서상 현재 1년 | 분석 공급자 설정에서 보관. DB 탈퇴·대화 삭제와 분리, 브라우저 ID와 계정 연결하지 않는다고 문서화 |

탈퇴 문서의 “회원 피드백 삭제”는 `accounts.py`의 삭제 큐가 성공적으로 완료되는 경로와 일치한다. 다만 FK 자체는 user_id만 NULL 처리하므로 큐 복구가 실패하지 않는지와 잔량을 운영에서 감시해야 한다. 회원 탈퇴 삭제 대상은 계정에 연결된 의견이며 비회원 피드백은 대상이 아니다.

## 4. 접근 권한

| 영역 | 권한 경계 |
|---|---|
| profiles / conversations / messages | RLS 활성. authenticated는 본인 행 읽기(프로필은 표시 이름 갱신)만. 생성·삭제·대화 변경은 검증된 서버 API가 처리. service_role은 RLS 우회하므로 API 소유권 검증 필수 |
| feedback / answer_feedback / answer_runs / answer_run_steps | RLS 활성, anon/authenticated 권한 회수, service_role만 접근. 관리자 UI는 Supabase Table Editor 운영자 권한으로 조회·수정 |
| agent_state.* | 공개·브라우저 역할 권한 회수. 서버 DB 연결만 사용 |
| rag_knowledge.* | `20261015000100_rag_server_only.sql`에서 RLS 켜고 브라우저 역할 권한 회수; 지식 API는 읽기 전용 DB 연결 |
| admin API | `backend/api/admin.py`는 ADMIN_USER_IDS에 든 회원만 허용. 실행 요약·단계, 답변 평가 목록/상세(질문·답변 포함), 의견 목록/상세(본문 포함)를 제공. 대화 메시지 전체 목록 API인지는 확인되지 않음. Table Editor와 관리자 API 권한은 별개 |

서비스 역할 키·DB URL은 서버 전용이며 `deploy/backend.env.example`에 비밀 관리 지침이 있다. 배포 workflow는 `ADMIN_USER_IDS`를 Cloud Run 환경변수로 전달한다.

## 5. 처리방침과 실제 저장의 차이

| 처리방침/문서 표현 | 실제 구현·차이 |
|---|---|
| 질문·답변은 회원 messages에 저장 | 일치. 질문/답변 본문과 응답 payload가 저장됨 |
| 답변 평가는 선택 질문·답변 전문 포함 | 일치. 비회원 평가도 DB에 들어가며 회원 ID 없이도 thread_id 및 본문 저장 |
| 실행 기록에는 원문 질문·답변이 복사되지 않고 짧은 인용/조건이 저장 | answer_runs는 제한 JSON 요약을 저장하지만 사용자 조건·인용 텍스트가 포함될 수 있음. 단순 비식별 통계가 아님 |
| 피드백은 대화·이메일·브라우저 정보를 자동 첨부하지 않음 | 일치하는 API 설계. subject/message 자체에 사용자가 개인정보를 적을 수 있음 |
| PostHog는 계정·대화와 연결하지 않으며 기기 유형·경로를 이용 | analytics 문서와 일치한다고 기재. 실제 빌드 설정/수집 공급자 설정은 별도 운영 검증 대상 |
| 탈퇴 시 저장 대화·계산 상태·피드백 삭제 | 삭제 큐가 회원 feedback ID를 별도 보관해 실제 삭제한다. FK만 보면 user_id만 NULL 처리되므로 큐 완료/복구 감시가 중요 |
| 평가/실행 기록 보관과 정기 삭제 | 마이그레이션의 expires_at은 삭제 스케줄러가 아니다. 일부 피드백은 다음 접수 때 정리되어 90일 경과 즉시 삭제되지 않음 |
| 운영 로그·백업 보관 정책 적용 | 구체 기간·삭제 근거가 저장소 문서에서 확정되지 않음 |

## 6. 마이그레이션 규칙 제안

현재 파일은 `YYYYMMDDNNNNNN_short_description.sql` 형식이며, 시간순 번호와 설명은 일관적이다. 제안:

1. 파일명에 UTC 날짜·고유 순번·짧은 영문 설명을 유지하고 이미 적용한 파일은 수정하지 않는다. 변경은 새 additive migration으로 낸다.
2. 각 파일 맨 위에 목적, 잠금/중단 가능성, 데이터 영향, 롤백 방법을 적는다. 자동 down migration이 보장되지 않으면 롤백은 복구용 forward migration 또는 백업 복원으로 명시한다.
3. 적용 전 로컬 Supabase에서 빈 DB 및 최신 스키마 양쪽에 재현 적용하고, RLS·FK·인덱스·삭제 동작을 확인한다. 운영 데이터 백업과 복구 지점을 확인한다.
4. 운영 적용은 승인된 배포 절차/관리자가 수행하고, 적용 버전과 결과를 기록한다. 현재 `.github/workflows/deploy-backend.yml`은 백엔드 배포만 하고 Supabase migration을 실행하지 않는다. 따라서 운영 DB 적용의 실제 절차는 저장소 문서에서 확인되지 않음(규칙 없음). `docs/deployment.md`도 DB 마이그레이션 자동화 단계를 명시하지 않는다.

## 7. 바로 고쳐야 할 위험

1. **높음 — 관리자·service_role 접근 검증:** 관리자 API와 Table Editor는 민감한 질문·답변·실행 요약을 볼 수 있다. 관리자 ID/프로젝트 역할 최소화와 감사 로그를 점검한다.
2. **높음 — 삭제·만료 작업의 운영 보장:** 코드상 `accounts.recover()`는 서버 startup 경로에서 돌고, feedback 90일 삭제는 접수 경로에서 돌며 실행 로그도 복구 루프에 의존한다. 스케줄러/실패 감시가 없으면 서버 중단 중 기간을 넘긴 데이터가 계속 남을 수 있다.
3. **높음 — 데이터 보관 문구의 시간 경계:** feedback은 90일 지난 즉시가 아니라 다음 접수 때 정리된다. Privacy의 “주기적 정리”와 실제 트리거를 맞춰 고지하거나 정기 작업을 보장한다.
4. **중간 — 해시를 익명 통계로 오인할 위험:** HMAC subject와 thread_id는 연결 가능한 가명 식별자다. 만료·접근 통제를 적용한다.
5. **중간 — 처리방침상 로그/백업의 보유 기간과 삭제 조건 미확정.**

## 근거 파일

`supabase/migrations/` 13개 SQL, `backend/api/accounts.py`, `admin.py`, `answer_feedback.py`, `answer_runs.py`, `chat_storage.py`, `feedback.py`, `usage_limits.py`, `backend/shared/answer_trace.py`, `backend/knowledge/`, `docs/account-deletion.md`, `docs/analytics.md`, `docs/deployment.md`, `frontend/src/landing/Privacy.tsx`.
