# 사업 지표 가능성 조사

기준: 현재 저장소의 스키마와 코드만 확인했다. 아래 SQL은 초안이며 실행하지 않았다. 날짜 경계는 한국 시간(Asia/Seoul)으로 잡아야 한다. 실제 운영 데이터·PostHog 설정에는 접속하지 않았다.

## 지표별 가능성

| 지표 | 지금 가능한가 | SQL 초안 / 추가 기록 | 개인정보·정책 영향 |
|---|---|---|---|
| 전체 가입 회원 수 | 가능(회원 Auth 데이터 권한 필요) | 관리자 전용: `select count(*) from auth.users;` Supabase Auth API/관리자 화면 사용이 안전한 경우가 많음 | 계정 ID·이메일 접근 권한 제한 |
| 가입 추이 | 가능 | `select date_trunc('month', created_at), count(*) from auth.users group by 1 order by 1;` | 내부 집계 목적을 문서화 |
| 오늘 로그인 방문자(회원) | 제한적 가능 | `answer_runs`는 활동 일부만 나타내며 페이지 방문/로그인 전체가 아님. `count(distinct user_id)`는 견적 실행자 지표로만 해석 | 실행 데이터 접근 제한 |
| 오늘 전체 방문자(회원+비회원) | DB만으로 불가; PostHog로 가능할 수 있음 | `docs/analytics.md`의 `$pageview`/브라우저 ID 사용. 설치 테스트 제외 및 한국 날짜 기준을 PostHog에서 설정 | 무작위 브라우저 식별자·IP 수신 가능성·기기 유형, 국외이전 안내 확인 |
| 오늘 방문자, 운영자 포함/제외 | 회원 이벤트는 근사 가능, 비회원 방문은 ADMIN_USER_IDS로 제외 불가 | 관리자 계정의 user_id를 `answer_runs.user_id` 집계에서 제외 가능. PostHog 브라우저 ID와 ADMIN_USER_IDS는 연결되어 있지 않음 | 운영자 필터링을 위한 별도 식별 정보 저장은 고지 검토 |
| 월별 고객 수 | 정의에 따라 가능 | 유료 고객/구독 데이터 없음. 월간 활성 회원은 `date_trunc('month', started_at), count(distinct user_id)`를 answer_runs에서 계산(질문 전송/견적 실행 회원만) | 활성 기준을 명확히 표시 |
| 구독 회원 수 / 매출 | 불가 | 결제 제공자 webhook, subscription 테이블(회원 ID, 플랜, 상태, 기간, 결제 ID)을 추가 기록 | 금융·거래 정보 목적/보유기간/위탁처를 방침에 추가 |
| 질문 수 | 근사 가능 | `select count(*) from public.messages where role='user' and created_at >= :start;` 다만 중복 request/retry와 조건 답변 여부를 정의해야 함 | 질문 원문 읽지 않고 count만 사용 |
| 성공 견적 수 / 완료율 | 현재 정확한 분모·완료 이벤트 불가 | `answer_runs.status`, `answer_status`로 실행 성공 근사. 시작 시도와 사용자 의도(견적 완료)는 별도 이벤트/상태로 정규화 필요 | 새 본문 저장 불필요, 이벤트 ID·시간·결과 코드만 권장 |
| 다운로드 수 | PostHog `estimate_downloaded` 가능 | 앱 분석 이벤트. 서버 DB로 대조하려면 download 이벤트 기록 추가 | 이벤트 문서에 이미 목적 기재 |
| 재방문율 | DB로 전체 방문자 재방문 불가; PostHog 브라우저 ID로 가능 | 사용자 cohort/재방문 기간 정의. 회원 재방문은 user_id를 포함하는 별도 인증 이벤트 필요 | PostHog 식별자는 계정과 연결하지 않는 현재 방침과 회원 기반 연결은 구분 필요 |
| 전환율(방문→가입→첫 질문→완료) | 일부만 가능 | PostHog `$pageview`와 기능 이벤트는 있으나 브라우저 익명 ID를 계정에 연결하지 않으므로 방문→가입 개인 수준 경로는 현재 불가. 집계 전환 이벤트 또는 동의된 연결 추가 필요 | 계정·브라우저 ID 연결은 처리방침 수정 및 적법 근거/선택 검토 필요 |
| 피드백·답변 평가 수/평점 | 가능 | `select rating, count(*) from public.answer_feedback where created_at >= :start group by rating;` 및 feedback category 집계 | 내용보다 집계 사용, 본문은 관리자 한정 |
| 비용·모델 호출량 | 부분 가능 | `answer_run_steps.metadata`에 모델·시도·usage가 저장될 수 있으나 구조가 일관된 원장인지 확인 필요. 비용 원장/토큰 필드 정규화 권장 | 질문과 분리한 숫자·모델 메타데이터 보관 |

## 예시 SQL (관리자 전용, 실행하지 않음)

```sql
-- 한국 시간 기준 오늘의 회원 질문 메시지 수
select count(*)
from public.messages
where role = 'user'
  and created_at >= (date_trunc('day', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul')
  and created_at <  ((date_trunc('day', now() at time zone 'Asia/Seoul') + interval '1 day') at time zone 'Asia/Seoul');

-- 월별 활동 회원(견적 실행 기록이 있는 회원만; 전체 방문자가 아님)
select date_trunc('month', started_at at time zone 'Asia/Seoul') as month,
       count(distinct user_id) as active_members
from public.answer_runs
where started_at is not null and user_id is not null
group by 1 order by 1;

-- 오늘 실행한 회원 수: 운영자 ID는 서버의 ADMIN_USER_IDS 목록으로 수동 제외
select count(distinct user_id)
from public.answer_runs
where started_at >= (date_trunc('day', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul')
  and user_id is not null
  and user_id <> all (array['ADMIN_UUID_1']::uuid[]);

-- 완료율은 status/answer_status의 실제 의미를 확인한 뒤 사용
select status, answer_status, count(*)
from public.answer_runs
where started_at >= :period_start
group by status, answer_status;
```

회원 수를 Auth schema SQL로 세려면 service role 또는 안전한 관리자 경로가 필요하다. 일반 authenticated 사용자가 `auth.users`를 조회하게 권한을 열지 않는다. 운영자 제외 SQL의 UUID 목록은 ADMIN_USER_IDS의 실제 값을 서버 관리자만 관리하며 문서/클라이언트에 배포하지 않는다.

## 운영자 본인 제외와 비회원 방문

`ADMIN_USER_IDS`는 관리자 API 접근 권한에 쓰인다. 회원 실행 통계에서 같은 사용자 ID를 제외하는 필터로는 쓸 수 있지만, 분석 이벤트에는 계정 식별자가 포함되지 않아 PostHog의 익명 브라우저 방문을 이 설정으로 제외할 수 없다. 비회원 방문을 빼려면 다음 선택지가 있다.

1. 운영자 전용 브라우저에서 `environment=installation_test`처럼 표시하고 대시보드에서 제외(analytics 문서에 설치 확인용 속성 언급). 운영자의 실제 일상 방문 식별에는 약함.
2. 운영자 브라우저에 별도 opt-out/운영자 플래그 저장. 이 값은 분석 전에 제외하고 기기 간 동기화는 하지 않음. 오작동과 설정 초기화 가능.
3. 로그인 후 동의·고지한 운영자 식별 이벤트를 사용. 계정과 분석 ID 연결 여부를 명확히 공지하고 최소화.
4. 비회원 방문 로그 테이블을 새로 만들 경우 하루 단위 무작위/회전 식별자 또는 집계 카운터만 저장. raw IP·지문 정보는 피하고, 접근·보관·삭제·중복 제거 기준 및 처리방침을 먼저 정함.

## 추가로 기록할 데이터 권고

초기에는 개인정보를 늘리지 않는 집계 중심 기록이 적합하다. `metric_events`를 만든다면 event_name, occurred_at, anonymous/session ID(회전·만료), 선택적 user_id, environment, outcome_code만 허용하고 질문·답변·이메일·IP·기기 지문은 넣지 않는다. 사용자 ID와 브라우저 ID를 결합하면 방문→가입 전환 추적을 위해 처리 목적·근거·보관기간·선택권을 개인정보처리방침에 추가해야 한다. 구독은 별도의 서버 전용 billing/subscriptions 테이블로 두고 결제 제공자 ID와 플랜 상태만 저장한다.

정의부터 고정할 지표: “방문자”(세션/브라우저/사람), “고객”(가입/활성/유료), “질문”(메시지/새 견적/후속 조건), “완료”(계산 반환/다운로드/사용자 확인), 시간대 및 운영자 제외 기준.

## 대시보드 후보

| 도구 | 장점 | 단점/주의 |
|---|---|---|
| Supabase SQL Editor / Table Editor | 추가 제품 없이 DB 집계 시작, 접근 통제는 프로젝트 역할로 관리 | auth/사용자 콘텐츠 조회 위험, 반복 리포트·차트·운영자 필터 UI가 약함 |
| PostHog Web Analytics/Insights | 이미 문서화된 방문·기능 이벤트, 익명 방문·재방문 분석에 적합 | 국외 처리·쿠키/브라우저 식별 안내 필요, DB 회원 수와 직접 결합 안 됨 |
| Grafana + 집계 뷰/안전한 읽기 전용 연결 | 시계열 차트와 운영 알림에 강함 | 연결 비밀·읽기 권한·호스팅 운영 부담. 원본 테이블 전체 권한 부여 금지 |
| 간단한 관리자 페이지 | 필요한 핵심 지표와 ADMIN_USER_IDS 권한을 한곳에 표시 | 개발·검증 비용, 관리자 API에 집계 전용 endpoint와 감사 기록 필요 |

권장 순서: 현재 가능한 질문·실행·평가 집계부터 관리자 전용 SQL로 의미를 검토하고, 방문 수는 기존 PostHog에서 별도 표시한다. 구독/매출과 정확한 퍼널은 결제 데이터 및 명확한 이벤트 정의 후 추가한다.
