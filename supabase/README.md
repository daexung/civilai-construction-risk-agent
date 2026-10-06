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
애플리케이션은 아직 이 DB를 사용하지 않는다. 다음 단계는 Google 로그인과 API 저장소 연결이다.
기본 생성된 Auth 설정은 개발용이며 운영 정책인 Google 로그인 전용 설정은 아직 적용하지 않았다.

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
