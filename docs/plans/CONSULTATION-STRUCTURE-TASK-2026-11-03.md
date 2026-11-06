# 상담 구조 보완 작업 명세 (Sol → Claude Code Sonnet)

## 기준과 범위
- 기준: `codex/hotfix-conversation-20261101`, HEAD `43a3b4acf4238681df40408cbe644dd9fc6e3a8c`. 시작 당시 미커밋 제품 파일 11개와 신규 계획/검사/보고 파일 6개를 모두 보존한다. 시작 파일 해시·diff는 `tmp/consultation-20261103/baseline.json`, `baseline.patch`에 보존한다.
- 기존 `docs/plans/APPLICABILITY-HOTFIX-PLAN.md`의 상담 흐름을 마무리하는 한 묶음이다. 기존 `docs/agent-tool-orchestration-plan.md`의 LLM=대화·서버=검증/계산 원칙을 따른다. 새 그래프나 전면 리팩터링은 하지 않는다.
- 우선 구현: (1) 설명형 규칙을 자동 차단하지 않으면서 별도 확인사항으로 전달, 긴 적용 범위는 핵심 요약+펼쳐보기 (2) 차단/결과 없음에서 실제 조건 정정·공종 재선택으로 이어지는 기존 경로를 연결 (3) 단일/다중/복원 응답에서 안내·실패 사유가 사라지지 않도록 계약을 보완한다. 이미 동작하는 것은 재구현하지 않는다.
- 계산 확대 브랜치·명세 JSON·산식·정책·단가·검색 모델·운영 저장소·인증·요금제는 범위 밖이다. 전체 품셈의 누락 규칙 보완은 하지 않는다.

## 입출력 계약
- 입력: 기존 message/answers 및 세션의 공종·조건·revision. 서버가 허용한 질문/선택값과 기존 수정/재선택 경로만 사용한다. 같은 단위의 필드를 추측하거나 실제 값을 낮추도록 유도하지 않는다.
- 출력: 기존 status/reason/result/questions 및 다중 항목 구조를 유지하고 필요한 optional 안내 필드만 추가한다. 근거 없는 규칙은 공식 적용 불가로 단정하지 않는다. 설명형 규칙은 판단 미완료의 확인사항이며 계산 차단 근거로 쓰지 않는다.
- 범위 초과는 BLOCKED, 규칙 오류는 ERROR, 전체 미산정은 NO_RESULT 또는 현재 API의 명시적 실패 상태다. 정상+차단은 PARTIAL과 각 사유를 보존한다. 전체차단을 0원 성공이나 다운로드 가능한 현재 견적으로 표현하지 않는다.
- 조건/공종 변경은 기존 revision 무효화 계약을 따른다. 최신 입력과 무관한 과거 안내·금액·Excel을 재사용하지 않고 정상 형제 항목은 보존한다. 과거 세션에 optional 필드가 없어도 복원 가능해야 한다.

## 완료 검사와 증거 재사용
- 새 집중 회귀: 설명형 안내/긴 목록, 즉시 차단/질문 없는 응답, 정상+차단/전체차단, 과거 optional 필드 없는 복원, 정정/재선택 후 낡은 안내 제거. 실제 결함에 필요한 검사만 추가한다.
- 기존 검사 기록: `docs/reviews/applicability-hotfix-2026-11-01.md`, `docs/reviews/applicability-hotfix-sol-review-2026-11-01.md`, `tmp/claude-applicability-hotfix-20261101/{sol-final-review.json,sol-checks.json,sol-final-build.log,sol-final-frontend-tests.log,static-rule-review.json,browser-download-review.json}`. 보고서 간 차이는 파일 해시·최종 로그를 우선한다. 브라우저/다운로드 증거가 존재하므로 단순히 옛 문서의 미완료를 믿고 반복하지 않는다.
- 변경으로 무효화된 검사만 재실행하고 명령·종료코드·대상 해시·로그·재실행 이유를 기록한다. frontend 변경 시 해당 컴포넌트 검사와 build, 서버 변경 시 영향받는 오프라인 집중 회귀를 실행한다. 정적 전수/변경 없는 전체 회귀를 반복하지 않는다.
- 검사 환경: AGENT_OFFLINE=1, AGENT_LLM=off, AGENT_MODE=tools. 검색 fixture는 허용하되 실 모델·임베딩·외부 유료 API·운영 DB 호출은 금지한다. 브라우저가 필요하면 기존 `evals/serve_applicability_browser.py`의 loopback fixture를 사용하고 실제 확인 여부를 구분한다.

## 실행과 인계
- 2026-11-03 추가 승인: 구독 인증된 Claude Code Sonnet 실행과 필요한 작업 명세·관련 소스의 Anthropic 전송을 사용자가 명시적으로 허용했다. 별도 API 키 기반 호출은 금지한다. `.env`, 키·토큰·개인정보·운영 DB 데이터는 읽거나 전송하지 않는다. 원시 과거 세션 로그/인증 설정도 읽지 말고, 검사 근거는 비밀값 없는 검사 요약·코드·테스트 로그만 사용한다.
- 개발자는 터미널 Claude Code의 Sonnet 한 명만 사용한다. Agent/Task 등 추가 에이전트·백그라운드 개발자 생성 금지. Sol은 구현 중 조회/코드 검토를 반복하지 않고 완료 또는 실제 차단 시에만 검토한다.
- 설치 확인: `C:/Users/user/.local/bin/claude.exe`, 버전 2.1.280. `claude auth status`로 claude.ai 구독 로그인 확인(비밀값은 기록하지 않음). 미인증 시 `claude auth login`; 현재 재로그인/설치 불필요. Sonnet 선택은 `--model sonnet`, 실제 모델은 init 이벤트로 확인한다.
- 새 세션에 이 작업 명세와 파일 경로만 전달한다. 긴 이전 대화는 재개하지 않는다. 도구는 Read/Glob/Grep/Edit/Write/Bash/PowerShell만 제공하고 Agent/Task를 금지한다.
- 같은 원인 실패 2회, 범위 확대 필요 또는 실제 환경 차단이면 원인·시도·남은 작업을 기록하고 즉시 Sol에 넘긴다. 기본 작업 묶음 45분이며 무제한 반복하지 않는다.
- `docs/reviews/consultation-structure-2026-11-03.md`에 시작 즉시 진행 기록을 만들고 의미 있는 단계마다 변경·검사·남은 작업을 갱신한다. 완료 시 최종 변경 파일/검사/미완료와 세션 ID를 남긴다. 로그는 `tmp/consultation-20261103/`에 보존한다.
- 커밋·푸시·머지·배포·별도 유료 API 호출 금지. 기존 변경의 reset/checkout/clean/stash 금지. git 쓰기 작업도 하지 않는다.
