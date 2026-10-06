# 품셈이 로컬 Supabase

Docker Desktop의 Linux 컨테이너에서 PostgreSQL, Auth, API, Studio를 실행한다.
운영 프로젝트 연결과 데이터 반영은 별도 작업이며 아래 명령은 로컬 환경만 사용한다.

저장소 루트에서 실행한다. 초기 설정은 Supabase CLI 2.119.0으로 생성했다.

```powershell
npx --yes supabase@2.119.0 start
npx --yes supabase@2.119.0 status
npx --yes supabase@2.119.0 stop
```

- 관리 화면: http://127.0.0.1:54323
- API: http://127.0.0.1:54321
- PostgreSQL 포트: 54322
- `stop`은 로컬 데이터를 보존한다. `db reset`은 로컬 데이터를 삭제하므로 초기화할 때만 사용한다.
- `status`에 출력되는 비밀 키는 프런트엔드나 Git에 넣지 않는다.

로컬 실행 환경과 `profiles`, `conversations`, `messages` 테이블 및 사용자별 접근 권한을 준비했다.
프런트에 Google 팝업 로그인과 로그아웃을 연결했다. API 저장소와 회원 대화 영속화는 아직 연결 전이다.
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
아직 DB 이전은 구현되지 않았으므로 회원 대화도 새로고침하면 사라진다.
기존 localStorage 대화 저장은 제거했으며 로그인 세션 저장은 대화 저장과 별개다.
백엔드의 JWT 검증과 대화 소유권 검증은 후속 구현이며 현재 API는 회원 인증을 사용하지 않는다.

```powershell
# 운영 프로젝트를 건드리지 않고 로컬 마이그레이션만 적용
npx --yes supabase@2.119.0 migration up --local

# A/B/비회원 접근 권한 검증. 테스트 데이터는 종료 시 롤백한다.
Get-Content supabase/tests/chat_access.sql -Raw | docker exec -i supabase_db_civilai-construction-risk-agent psql -U postgres -d postgres -v ON_ERROR_STOP=1
```

설계와 남은 구현: [회원별 대화 저장과 멀티턴](../docs/chat-persistence-plan.md).
`agent_state`는 내부 체크포인트용 비공개 스키마만 준비했으며 테이블·그래프 연결은 아직 구현 전이다.

저장 정책: 비회원 대화는 탭과 서버의 임시 메모리에서만 유지하고 자동 만료한다.
Google 로그인 성공 시 서버가 임시 대화의 소유권을 검증한 뒤 메시지와 에이전트 상태를 함께 계정에 저장한다.
회원 대화는 서버 재시작 후에도 이어갈 수 있어야 한다.
