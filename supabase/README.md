# 품셈이 로컬 Supabase

Docker Desktop의 Linux 컨테이너에서 PostgreSQL, Auth, API만 실행한다.
메모리 사용을 줄이기 위해 현재 사용하지 않는 Studio, 실시간 구독, Storage, 메일 테스트,
Edge Functions, 로그 분석은 `config.toml`에서 비활성화했다.
운영 프로젝트 연결과 데이터 반영은 별도 작업이며 아래 명령은 로컬 환경만 사용한다.

저장소 루트에서 실행한다. 초기 설정은 Supabase CLI 2.119.0으로 생성했다.

```powershell
npx --yes supabase@2.119.0 start --exclude postgres-meta
npx --yes supabase@2.119.0 status
npx --yes supabase@2.119.0 stop
```

- 관리 화면은 기본적으로 꺼져 있다. 필요하면 `[studio].enabled = true`로 변경하고
  `stop` 후 `start`를 실행한다. 이때 `--exclude postgres-meta`는 빼야 한다.
  관리 화면 주소는 http://127.0.0.1:54323 이다.
- API: http://127.0.0.1:54321
- PostgreSQL 포트: 54322
- `stop`은 로컬 데이터를 보존한다. `db reset`은 로컬 데이터를 삭제하므로 초기화할 때만 사용한다.
- `status`에 출력되는 비밀 키는 프런트엔드나 Git에 넣지 않는다.

로컬 실행 환경과 `profiles`, `conversations`, `messages` 테이블 및 사용자별 접근 권한을 준비했다.
프런트에 Google 팝업 로그인과 로그아웃, 회원 대화 목록·내용 복원을 연결했다.
API는 Supabase Auth에서 Bearer 토큰을 확인하고, 회원별 대화 소유권을 검증한다.
회원 메시지와 PostgresSaver 체크포인트는 같은 DB 트랜잭션에 저장한다.
사이드바의 로그인 버튼은 안내 모달을 열고, 모달의 Google 버튼이 인증 팝업을 연다.
로그인 후에는 이름과 이니셜 계정 행을 표시한다. 설정의 계정 항목에서 이메일과 로그인 방식을 확인하고
이 기기에서 로그아웃할 수 있다. 일반 항목에는 현재 언어와 이용약관 링크를 제공한다.
Google provider는 활성화하고 이메일 회원가입과 익명 Auth 가입은 비활성화했다.
운영 프로젝트의 Auth 설정은 별도로 적용해야 한다.

## Google 로그인 설정

`google.env.example`의 두 항목을 저장소 루트 `.env`에 넣는다. 기존 설정은 유지한다.
Google OAuth 클라이언트의 리디렉션 URI는 `http://127.0.0.1:54321/auth/v1/callback`이다.
프런트 원본은 `http://127.0.0.1:3000` 또는 `http://localhost:3000`이다.
프런트 `.env.local`에는 `REACT_APP_SUPABASE_URL`과 `REACT_APP_SUPABASE_PUBLISHABLE_KEY`만 넣는다.
OAuth Secret과 Supabase 서버 전용 키를 프런트에 넣지 않는다.
환경값 변경 뒤 Supabase를 stop/start하고 프런트 개발 서버도 재시작하거나 다시 빌드한다.

콜백 `/auth/callback`은 PKCE로 세션을 확인한 뒤 원래 탭에 완료 상태만 알린다.
원래 탭은 출처와 팝업 창이 일치하는 메시지만 받고 SDK에서 세션을 확인한다.
팝업 취소·차단 시 대화를 유지하며 로그인 후에도 진행 중인 대화는 현재 탭에 유지한다.
로그인 이후 시작한 새 대화는 DB에 저장되어 새로고침 후 목록에서 다시 열 수 있다.
로그인하면 현재 탭의 임시 대화를 계정으로 자동 이전한다. 서버가 가진 메시지와 체크포인트를 함께 복사한다.
임시 소유권과 로그인 사용자를 모두 검증하며, 원래 질문을 다시 실행하지 않는다.
이전이 끝나면 회원 대화로 이어가고 새로고침 후에도 복원된다.
실패 시 임시 기록을 유지하고 다시 시도할 수 있다. 확인이 끝나기 전에는 해당 대화의 새 요청을 막는다.
기존 localStorage 대화 저장은 제거했으며 로그인 세션 저장은 대화 저장과 별개다.
목록·내용·계산 조건 변경·엑셀 다운로드에 소유권 검증을 적용한다.
비회원 대화는 별도 임시 세션 비밀값이 있어야 이어갈 수 있다.

```powershell
# 운영 프로젝트를 건드리지 않고 로컬 마이그레이션만 적용
npx --yes supabase@2.119.0 migration up --local

# A/B/비회원 접근 권한 검증. 테스트 데이터는 종료 시 롤백한다.
Get-Content supabase/tests/chat_access.sql -Raw | docker exec -i supabase_db_civilai-construction-risk-agent psql -U postgres -d postgres -v ON_ERROR_STOP=1
```

설계와 남은 구현: [회원별 대화 저장과 멀티턴](../docs/chat-persistence-plan.md).
`agent_state`에 API 시작 시 공식 PostgresSaver 테이블을 준비한다. 브라우저 역할의 접근 권한은 제거한다.

## 백엔드 저장소 연결

`backend/api/chat.env.example`의 항목을 루트 `.env`에 추가한다. 로컬 API URL, 공개 키,
서버 전용 `CHAT_DATABASE_URL`을 사용한다. Google 설정은 그대로 둔다.

```powershell
.venv\Scripts\python.exe -m uvicorn backend.api.main:app --env-file .env --host 127.0.0.1 --port 8000 --no-proxy-headers

# 실제 PostgreSQL 저장·격리·롤백·재시도·계산 복원 검증(로컬만 허용)
$env:CHAT_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'
.venv\Scripts\python.exe evals/check_chat_storage.py
```

회원 요청은 `conversation_id`, `request_id` UUID를 보내며 사용자 ID는 검증된 토큰에서만 얻는다.
대화별 PostgreSQL 잠금으로 요청을 직렬화하고 동일 요청 ID는 기존 응답을 반환한다.
실패한 요청은 메시지·내부 상태를 함께 롤백한다. 목록에는 최근 대화 최대 200개를 반환한다.
회원 계산 상태는 서버 재시작 후 복원되며 비회원 상태는 서버 메모리에서만 유지한다.
비회원은 마지막 요청 후 24시간 만료되며 새 요청 시 만료 상태를 정리한다. 여러 API worker 간 공유는 하지 않는다.

저장 정책: 비회원 대화는 탭과 서버의 임시 메모리에서만 유지하고 자동 만료한다.
`agent_state.guest_imports`는 소유자·임시 비밀값 해시·대상 대화 ID를 기록하는 비공개 이전 영수증이다.
네트워크 오류로 같은 이전을 재시도하거나 API가 재시작돼도 중복 저장하지 않는다.
이전 실패 시 DB 기록을 롤백하고 임시 상태를 보존하며, 성공 커밋 후에만 임시 상태를 지운다.
영수증은 대화 하드 삭제 시 함께 삭제되어 이전 요청으로 대화를 다시 만들 수 없다.

```powershell
$env:CHAT_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'
.venv\Scripts\python.exe evals/check_guest_import.py
```

완료된 견적의 자연어 멀티턴 개선은 후속 구현이다.
대화 목록의 점 세 개 메뉴 → 삭제 → 확인은 하드 삭제다. 회원 대화·메시지·체크포인트를 같은
트랜잭션에 삭제하며 실패 시 전부 롤백한다. 삭제는 대화 쓰기와 같은 잠금으로 직렬화한다.
비회원 대화도 임시 소유권을 확인한 뒤 서버 메모리와 화면에서 제거한다. 복원 기능은 제공하지 않는다.
운영 Supabase 연결, 클라우드 비용 상한, 탈퇴 시 체크포인트 정리도 공개 전 후속 작업이다.

## 일일 사용량 제한

`20261006000300_daily_chat_usage.sql`을 적용하면 채팅 전송을 한국 시간 자정 기준으로
비회원(IP별) 5회, 회원(검증된 계정별) 20회, 모든 비회원·회원 합산 500회로 제한한다.
질문, 추가 조건 답변, 조건 변경은 각각 1회다. 목록 조회, 대화 이전·삭제, 엑셀 다운로드는 차감하지 않는다.
처리가 시작된 요청은 실패하더라도 차감한다. 외부 API 호출 뒤 실패한 요청을 반복해서 비용을 발생시키는 것을 막는다.
완료된 회원 요청의 동일 `request_id` 재전송은 저장된 응답을 반환하고 추가 차감하지 않는다.

사용량은 비공개 `agent_state.daily_chat_usage`에 저장하고, 7일보다 오래된 집계는 새 요청 때 정리한다.
원본 IP나 대화는 집계 테이블에 넣지 않는다. 식별자는 HMAC 해시로 저장한다.
운영 환경에는 독립된 긴 랜덤 `QUOTA_HASH_SECRET`을 설정하고 유지한다.
로컬에서는 설정하지 않으면 `CHAT_DATABASE_URL`을 해시 키로 사용하므로 DB 연결 문자열을 변경하면
비회원 식별자가 바뀐다. 동일 네트워크의 비회원은 IP 한도를 공유하고, 회원은 각 계정 한도를 사용한다.

전체 한도는 DB 트랜잭션으로 원자적으로 차감하고, 사용자별 PostgreSQL advisory lock으로
동시 처리를 차단한다. 서버 재시작과 대화 삭제로 한도가 초기화되지 않는다.
DB에 연결할 수 없으면 유료 처리를 허용하지 않는다. DB 연결은 직접 연결 또는 세션 풀러를 사용해야 한다.
트랜잭션 풀러는 세션 advisory lock을 지원하지 않으므로 사용하지 않는다.

비회원 IP는 ASGI `request.client`에서 가져오며 임의의 `X-Forwarded-For`를 직접 읽지 않는다.
배포 시 외부에서 백엔드로 직접 접근하지 못하게 하고, Uvicorn `--forwarded-allow-ips`에는
실제 신뢰하는 리버스 프록시 주소만 지정해야 한다(`*` 사용 금지).
로컬 서버 실행 명령에는 `--no-proxy-headers`를 사용해 임의 전달 헤더를 무시한다.

```powershell
.venv\Scripts\python.exe evals/check_usage_limits.py
```
