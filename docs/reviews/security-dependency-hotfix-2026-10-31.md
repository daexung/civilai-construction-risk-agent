# 의존성 보안 핫픽스 2026-10-31

기준: main 1091889, 브랜치 codex/hotfix-security-dependencies-20261031. 커밋/푸시/배포는 이 작업에서 하지 않았다. 이 문서는 변경 내역과 실제 실행한 검사만 기록하며, 과거 보고서(security-audit-2026-10-25.md, security-current-summary-20261031.md)는 수정하지 않았다.

## 변경한 패키지

### frontend/package.json, frontend/package-lock.json

- `npm audit fix --package-lock-only --ignore-scripts`로 비-major 전이 의존성을 1차 패치: dompurify 3.4.16→3.4.17, shell-quote 1.10.0→1.12.0, follow-redirects 1.16.0→1.16.2 등.
- `overrides.zod`: 설치 4.1.11(`@vercel/oidc`가 당기는 `@vercel/cli-config`가 정확히 고정)→`^4.6.6`로 강제. `@vercel/oidc`/`@vercel/cli-config` 자체도 4.0.5/0.3.5로 최신화됨. **정정**: 최초 보고서에서 `@vercel/oidc`를 "미사용"이라고 적었으나 이는 오류였다. `frontend/src`만 검색해 놓치고 있었고, 실제로는 `frontend/api/[...path].js` → `frontend/server/cloud-run.cjs`의 Vercel 서버리스 프록시 함수가 `await import('@vercel/oidc')`로 `getVercelOidcToken()`을 호출해 GCP Cloud Run Workload Identity Federation 토큰 교환에 쓰고 있다(운영 API 프록시 인증 경로). 따라서 이 zod override는 미사용 패키지 정리가 아니라 실제 운영 인증 경로의 취약 전이 의존성 수정이다.
- `overrides.bfj`: `^9.1.4`. react-scripts가 요구하던 bfj 7.1.0의 전이 의존 jsonpath(1.3.0, underscore 1.13.6 정확히 고정)를 제거해 jsonpath/underscore의 high 취약점 경로를 끊음. bfj는 react-scripts 빌드 시 통계 파일(JSON) 직렬화에만 쓰이는 빌드 전용 도구.
- `overrides.serialize-javascript`: `^7.1.3`. css-minimizer-webpack-plugin/rollup-plugin-terser가 당기던 <=7.1.2(RCE/XSS/DoS 다중 advisory)를 해결. 빌드 시 minify 단계에서만 쓰임.
- `overrides."sockjs".uuid`: `^11.1.1`. webpack-dev-server의 sockjs가 내부적으로 쓰는 별도 uuid(버퍼 바운드 체크 누락, moderate)를 해결. 개발 서버(`npm start`) 경로에만 영향.
- 직접 의존성 `uuid`: `^9.0.0`→`^11.1.1`(처음 14.0.3 적용 시도 → Jest가 ESM-only 패키지를 transform하지 못해 4개 테스트 스위트 실패, 되돌림). 11.1.1은 `require`(CJS) export 조건을 유지해 CRA의 기본 Jest 설정과 호환되면서 advisory 수정 버전(≥11.1.1) 요건을 만족.
- `@types/uuid` 제거: uuid 11.1.1부터 자체 타입(`dist/*.d.ts`)을 포함해 중복.

적용하지 않은 것: `npm audit fix --force`, react-scripts 메이저 교체/다운그레이드, CRA→Vite/Next 전환. react-scripts 5.0.1이 정확히 고정한 webpack-dev-server/webpack-dev-middleware/svgo/postcss/css-select/nth-check/jest 계열(high/low 다수)은 이번 제한된 핫픽스 범위에서는 미해결로 남긴다(react-scripts 자체를 건드리지 않는 조건에서 추가로 끊을 수 있는 체인은 찾지 못했다는 뜻이며, CRA 교체 자체가 유일한 해법이라고 단정하지는 않는다). 이들은 **개발 서버 실행(`npm start`) 또는 빌드 시점(svg 최적화, postcss, jest)에만** 동작하며, 배포되는 정적 번들에는 포함되지 않는다. 실제 운영 경로에서의 악용 재현은 확인하지 않았다(확인 불가가 아니라 범위 밖).

### backend/api/requirements.txt, backend/agent/requirements.txt, backend/requirements.txt(중복 핀)

- `langgraph-checkpoint-postgres`: 3.1.2→3.1.3 (advisory GHSA-6hmw-9432-67qq 수정 버전).
- `langgraph-checkpoint`: 4.2.0→4.3.0 (langgraph-checkpoint-postgres 3.1.3의 `Requires-Dist: langgraph-checkpoint<5.0.0,>=4.3.0` 요건).
- `langgraph`: 1.2.12 유지. 1.2.12의 `Requires-Dist: langgraph-checkpoint<5.0.0,>=4.1.0`과 4.3.0이 호환됨을 PyPI 메타데이터로 확인.
- 세 requirements 파일(배포용 include 경로 2개 + 중복 루트 핀 1개) 모두 동일하게 패치해 버전 불일치를 없앴다.
- API·상담 저장/복원·계정 격리 로직 코드는 변경하지 않았다. 앱은 PostgresSaver만 사용하며, advisory의 PostgresStore/AsyncPostgresStore 경로는 이번에도 코드에서 발견하지 못했다.

## npm audit 전후 (package-lock-only, ignore-scripts)

| | critical | high | moderate | low | total |
|---|---|---|---|---|---|
| 수정 전 | 2 | 21 | 8 | 16 | 47 |
| 수정 후 | 0 | 7 | 2 | 17 | 26 |

low가 16→17로 1개 늘어난 것은 새 의존성 그래프에서 낮은 심각도 항목 하나가 추가로 노출된 것이며 은폐가 아니다. 남은 7 high/2 moderate는 모두 react-scripts 5.0.1이 정확히 고정한 개발/빌드 전용 패키지(webpack-dev-server, webpack-dev-middleware, svgo, postcss, css-select, nth-check, react-scripts 자체, resolve-url-loader)로, 운영 정적 번들에 포함되지 않는다. 원시 결과는 tmp/security-hotfix/npm-audit-after-step5.json.

## Python 버전 계약 확인

`.venv`에서 직접 설치/검증(OS/전역 Python 미사용):
- `pip show`로 설치 전 langgraph 1.2.12 / langgraph-checkpoint 4.2.0 / langgraph-checkpoint-postgres 3.1.2 확인.
- PyPI 휠 METADATA로 langgraph-checkpoint-postgres 3.1.3의 요구 범위(`langgraph-checkpoint<5.0.0,>=4.3.0`)와 langgraph 1.2.12의 요구 범위(`langgraph-checkpoint<5.0.0,>=4.1.0`)가 4.3.0에서 동시에 만족됨을 확인.
- `pip install langgraph-checkpoint-postgres==3.1.3 langgraph-checkpoint==4.3.0` 후 `pip check` → "No broken requirements found."
- `from langgraph.checkpoint.postgres import PostgresSaver`와 `backend.agent.graph.build_graph` 임포트가 새 버전에서 정상 동작함을 확인.

## 실행한 검사

- `cd frontend && CI=true npm run build` — 성공(exit 0). prerender-home.cjs까지 정상 완료.
- `cd frontend && CI=true npm test -- --watchAll=false --runInBand` — uuid 14.0.3 적용 시 4개 스위트 실패(ESM만 지원해 Jest가 transform 못함) → uuid 11.1.1로 되돌린 뒤 재실행, 13 스위트/85 테스트 전부 통과.
- `./.venv/Scripts/python.exe -m unittest evals.test_single_trade_conditions -v` — 11개 테스트 통과(오프라인, AGENT_OFFLINE=1).
- `./.venv/Scripts/python.exe evals/check_unified_estimate_chat.py` — 12개 PASS(오프라인, retrieve 모킹, DB/모델/캐시 미사용).
- `evals/check_chat_storage.py`는 실행하지 않음: `CHAT_DATABASE_URL`이 로컬 Supabase(127.0.0.1:54322)를 요구하며 해당 포트가 떠 있지 않음(curl 확인). 운영 DB·외부 계정을 쓰지 않는 조건이라 기동시키지 않았다.
- `git diff --check` — frontend/backend 변경 파일 모두 공백 오류 없음.

가격 unittest·통합 견적(check_unified_estimate_chat으로 대체 확인)·거푸집 높이·장비 e2e·근거 계약·단일 공종18개의 개별 재실행은 하지 않았다. 이번 변경이 프런트 의존성(uuid/dompurify 등)과 langgraph-checkpoint 계열에만 한정되고, 위 두 검사(단일 공종 11종 + 통합 견적 12종)가 backend.agent/backend.api의 핵심 임포트 경로(graph, estimate, dialogue, tools)를 이미 오프라인으로 실행해 통과했으므로 중복 재실행은 생략했다.

## 남은 범위와 한계

- react-scripts 5.0.1 고정으로 인한 잔여 7 high/2 moderate는 react-scripts를 건드리지 않는 이번 제한된 핫픽스에서는 미해결로 남겼다. CRA 메이저 교체가 유일한 길이라고 단정하지는 않으며, 이번 작업 범위 밖이었을 뿐이다. 실제 영향은 로컬 개발 서버/빌드 시점으로 제한된다.
- langgraph-checkpoint-postgres 패치는 로컬 `.venv` 설치·임포트까지만 검증했다. 운영 Postgres(Supabase)에 대한 실제 체크포인트 저장/복원 라운드트립은 로컬 Supabase가 기동되지 않아 확인하지 못했다(`check_chat_storage.py` 미실행).
- PostHog(posthog-js) 자체 버전은 변경하지 않았다. session recording/surveys/외부 의존성 로딩은 기존처럼 비활성 상태를 유지했고, 다시 켜지 않았다.
- 원시 npm audit/설치 로그는 tmp/security-hotfix/(gitignore 대상)에 보관.

## 추가 보강 2026-10-31 (같은 핫픽스, 후속 확인)

tmp/security-hotfix-addendum.md 기준. 첫 작업 변경은 보존하고 아래를 추가했다. 커밋/푸시/배포/운영 DB·모델 호출은 이번에도 하지 않았다.

### 추가 패치

- `langgraph`: 1.2.14로 상향(기존 1.2.12는 GHSA-3fx2-cqw9-xr3c 영향 범위 `>=1.2.3,<1.2.14`). `backend/agent/requirements.txt`, `backend/requirements.txt`에 반영.
- `langgraph-sdk`: 0.4.6을 명시적으로 핀 추가(기존엔 langgraph의 전이 의존이라 버전이 파일에 적혀 있지 않았음). langgraph 1.2.14의 PyPI 메타데이터가 `langgraph-sdk<0.5.0,>=0.4.6`을 요구함을 확인하고 정확히 하한에 맞췄다. 앱 코드에서 SDK v3 streaming의 `get_tree`/`_fetch_state` 경로는 여전히 발견하지 못했지만, 호환 가능한 수정 버전으로 맞췄다.
- `certifi`: 2026.10.19를 `backend/api/requirements.txt`, `backend/agent/requirements.txt`, `backend/requirements.txt`에 명시적으로 핀 추가(기존엔 httpx/requests의 전이 의존이라 파일에 없었음, 설치본은 2026.7.22였음). Vercel eMudhra 공지(침해된 중간 CA 키)의 수정 인증서 목록 버전과 맞췄다. 운영 이미지에 실제로 어떤 certifi가 깔려 있었는지는 이번에도 확인하지 못했다 — 이 핀은 향후 빌드부터 수정 버전을 보장하기 위한 것이다.
- `.venv`에 위 세 패키지를 설치: `pip install langgraph==1.2.14 langgraph-sdk==0.4.6 certifi==2026.10.19` → `pip check` = "No broken requirements found."
- Node.js: 시스템 전역 Node(`C:/Program Files/nodejs/node.exe`, 24.16.0)는 바꾸지 않았다. tmp/security-hotfix/node/node-v24.22.1-win-x64(공식 SHASUMS256 대조, verified-runtime.json 참조)를 이번 검증 세션의 PATH 맨 앞에만 둬서 `node`/`npm`이 그 경로로 해석되는 것을 확인(`node --version` → v24.22.1, `npm --version` → 11.19.1 — 24.22.1에 내장된 npm). `frontend/package.json`에 `"engines": { "node": "24.x" }`를 추가해 개발 환경 안내로 남겼다(전역 설정 변경 아님). 운영 Vercel 배포가 실제로 어떤 patch 버전을 쓰는지는 process.version을 직접 조회하지 않았으므로 단정하지 않는다.

### 정정

- 최초 보고서의 "`@vercel/oidc` 미사용" 서술을 정정했다(위 변경한 패키지 절 참조). `frontend/api/[...path].js`가 사용하는 운영 경로였다.
- "CRA 교체 없이는 불가능"이라는 단정을 완화했다: react-scripts를 건드리지 않는 이번 제한된 핫픽스에서는 미해결이라는 뜻이며, CRA 교체가 유일한 해법이라고 확정하지 않는다.

### 패치된 Node 24.22.1로 재실행한 검사

- `npm ci --ignore-scripts` (PATH 맨 앞 node-v24.22.1-win-x64) — 성공, 1398개 패키지 설치, lockfile 그대로 재현(강제 major 업데이트 없음), audit 26건(critical 0/high 7/moderate 2/low 17) 동일.
- `CI=true npm run build` — 성공(exit 0), prerender 정상.
- `CI=true npm test -- --watchAll=false --runInBand` — 13 스위트/85 테스트 전부 통과.
- `HOST=127.0.0.1 PORT=3100 BROWSER=none npm start`(기본 옵션) — webpack-dev-server가 `options.allowedHosts[0] should be a non-empty string` 스키마 오류로 즉시 종료. 코드를 보면 `package.json`의 `proxy` 설정으로 host-check가 켜지고(react-scripts 5.0.1 `config/webpackDevServer.config.js`), 이 환경에서 LAN IP를 해석하지 못해 `allowedHost`가 빈 값으로 전달되는 것으로 보인다. 이번 핫픽스(sockjs/uuid override, serialize-javascript override 등)와 무관한 react-scripts/react-dev-utils의 기존 환경 의존 동작이다. 이 증상은 이번 세션 이전에도 발생한 기록이 있어, 이번 보안 수정으로 새로 생긴 회귀로 보지 않는다.
- 위 상태에서는 sockjs 경로 자체를 검증할 수 없어, 같은 조건에 `DANGEROUSLY_DISABLE_HOST_CHECK=true`만 추가해 1회 재시작 — `Compiled with warnings`로 정상 기동, `curl 127.0.0.1:3100/` → `HTTP 200`. sockjs의 override된 uuid(11.1.1)를 포함한 webpack-dev-server 스택이 실제로 요청을 처리함을 확인했다. 이 환경변수는 코드/설정 파일에 반영하지 않았고 검증 종료 후 제거했다.
- 검증에 쓴 PID만 종료: `netstat`로 127.0.0.1:3100을 리스닝하던 PID(25524, 로그의 `node:25524`와 일치)를 확인해 `taskkill /PID 25524 /F`로 종료, 포트 해제 확인. 그 전 `allowedHosts` 오류로 즉시 크래시한 두 시도(PID 4480, 26884)는 이미 자체 종료된 상태였다. 종료 후 `tasklist`로 남은 node.exe 프로세스(다른 PID 7개)를 확인했으나 이번 세션에서 띄운 것이 아니므로 건드리지 않았다.

### 패치된 Python 패키지로 재확인한 검사

- `./.venv/Scripts/python.exe -m unittest evals.test_single_trade_conditions -v` — 11개 통과.
- `./.venv/Scripts/python.exe evals/check_unified_estimate_chat.py` — 12개 PASS.
- `from langgraph.checkpoint.postgres import PostgresSaver`, `backend.agent.graph.build_graph` 임포트 정상.
- `evals/check_chat_storage.py`는 이번에도 미실행(로컬 Supabase 127.0.0.1:54322 미기동, 운영 DB 사용 금지 조건 유지).

## 추가 보강 2 2026-10-31 (Sol 검증 + pip 핫픽스)

### pip (프로젝트 .venv만, 전역/시스템 미변경)

- Sol이 `.venv` 설치 패키지 62개를 공식 OSV에 일괄 조회(tmp/security-hotfix/python-installed-osv-after.json)한 결과 남은 advisory는 `pip` 26.1.2의 GHSA-qwm4-qh6w-59xr/PYSEC-2026-3721(영향 범위 `<26.2.0`, 수정 `>=26.2.0`)뿐이었다.
- `./.venv/Scripts/python.exe -m pip install --upgrade pip==26.2.2` 실행 → `pip --version`으로 26.2.2 확인, `pip check` → "No broken requirements found."
- `Dockerfile`의 의존성 설치 RUN을 수정해 `pip install -r deploy/backend-requirements.txt` 전에 `python -m pip install --no-cache-dir --upgrade pip==26.2.2`를 먼저 실행하도록 했다. 다른 Dockerfile이나 실행 로직(CMD, USER, COPY 순서 등)은 바꾸지 않았다. **Docker 엔진이 이 세션에 준비되어 있지 않아 이미지 빌드 자체는 실행하지 않았다 — 빌드 성공을 주장하지 않는다.** 텍스트 수정만 적용했다.

### frontend/package.json ↔ package-lock.json 메타데이터 일치

- `package.json`의 `engines.node: "24.x"`가 `package-lock.json`의 루트 패키지 메타데이터(`packages[""]`)에는 반영돼 있지 않아 Node로 직접 JSON을 읽고 `engines` 필드를 추가해 맞췄다(`npm install`/`ci` 전체 재실행 없이 메타데이터만 동기화, 설치된 패키지 버전은 그대로 유지).

### Sol이 추가 검증한 항목 (출처: tmp/security-hotfix/, 이번 세션에서 직접 재실행하지 않음)

- **패치된 Node 24.22.1에서 프록시 검사 4개 통과** — tmp/security-hotfix/proxy-node24.log: `cloud_run_proxy` 관련 node 테스트 스위트 4개(IAM/사용자 토큰 분리 및 스푸핑 헤더 제거, 트래버설/임의 호스트/누락-다중 IP 거부, 다운로드 바이트·파일명·쿼터 상태 보존, 토큰 교환 실패 시 백엔드 미호출) 전부 pass. 로그에 `GCP_TOKEN_EXCHANGE_FAILED` 두 건이 보이는데, 이는 테스트가 실패를 유도해 "교환 실패 시 백엔드로 요청을 보내지 않는지"를 확인하는 의도된 음성 경로이지 예외적 오류가 아니다.
- **OIDC 모듈의 실제 export 확인(토큰 발급 없음)** — `@vercel/oidc`가 실제로 쓰이는 `frontend/server/cloud-run.cjs`의 `getVercelOidcToken` export 존재를 확인한 것으로, 위 proxy 테스트가 이 함수를 모킹한 `oidc` 콜백으로 대체해 검증했다는 뜻이다. 실제 Vercel 환경에서 살아있는 OIDC 토큰을 발급·교환한 적은 없다.
- **네임스페이스 입력 검증** — tmp/security-hotfix/namespace-security-verification.log: `get`/`search`/`delete`/`list_namespaces` 4개 경로 모두 잘못된 네임스페이스 입력이 `InvalidNamespaceError`로 DB 접속 전에 거부됨을 확인. 로그 마지막 줄의 설치 버전 표(`langgraph 1.2.14`, `langgraph-sdk 0.4.6`, `langgraph-checkpoint 4.3.0`, `langgraph-checkpoint-postgres 3.1.3`, `certifi 2026.10.19`)는 이번 핫픽스로 패치된 버전과 일치한다. **이 검사는 입력 검증 로직만 확인했고, 실제 Postgres/Supabase 접속을 거친 라운드트립 검증은 하지 않았다** — 운영 DB 검증은 이번에도 미실행이다.

### 남은 한계 (추가분)

- `langgraph-sdk` 0.4.6은 advisory가 명시한 수정 하한에 정확히 맞췄다. 더 최신(0.4.10)은 범위를 벗어난 추가 변경이라 적용하지 않았다.
- certifi 핀은 로컬 `.venv` 설치까지만 검증했다. 운영 배포 이미지의 실제 certifi 버전은 이번에도 조회하지 못했다.
- Node 24.22.1 검증은 이번 세션의 PATH 선두 지정으로만 확인했고, 사용자 시스템의 전역 Node(24.16.0)나 Vercel 운영 런타임의 실제 patch 버전은 바꾸지도, 조회하지도 않았다.
- webpack-dev-server의 `allowedHosts` 스키마 오류는 기존에도 발생 기록이 있는 환경 의존적 동작이며, 이번 보안 수정으로 새로 생긴 회귀가 아니다. 별도 이슈로 다룰 필요가 있다.
- Dockerfile의 `pip==26.2.2` 선행 설치는 텍스트만 수정했고 실제 이미지 빌드는 이 세션에 Docker 엔진이 없어 실행하지 못했다 — 빌드 성공을 주장하지 않는다. 다른 Dockerfile·실행 로직은 변경하지 않았다.
- Sol의 proxy/네임스페이스 검증(위 섹션)은 이번 세션에서 재실행하지 않고 제공된 로그를 그대로 인용했다. 실제 Postgres/Supabase 라운드트립과 운영 OIDC 토큰 발급은 여전히 미검증이다.
