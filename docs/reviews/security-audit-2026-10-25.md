# 품셈이 긴급 보안 점검 — 2026-10-25

## 결론

PHP 애플리케이션 구성은 발견되지 않았다. 그러나 서비스 전체를 안전하다고 결론 내릴 수 없다. 로컬 Node.js의 패치가 필요하고, npm 잠금 의존성의 취약 버전이 확인됐다. 운영 Vercel Node.js의 실제 패치 버전은 확인되지 않았다. 이번에는 점검과 기록만 수행했다.

## 확인 기준과 실제 운영 확인

GitHub main은 `168d80a426d5a348f666a9d2f03153b818e0fec7`(2026-10-17)이며 GitHub Production deployment 7139576936도 이 SHA를 가리킨다. Vercel 로그인 대시보드에서 해당 운영 배포 표시까지 확인했다. 로컬 frontend/package-lock.json은 CRLF 등 바이트 차이가 있으나 JSON 내용은 이 커밋과 동일하다. 런타임이 실제로 설치한 모든 패키지나 Cloud Run 이미지 digest를 검증한 것은 아니다.

- 공개 Vercel `/api/ready`: HTTP 200, status=ok.
- `/api/health`: 첫 요청 타임아웃, ready 정상 확인 후 한 번 재확인해 HTTP 200, status=ok. 초기 원인을 확정하지 않았다.
- Cloud Run 직접 `/api/health`: 인증 없이 HTTP 403. Vercel 경유는 정상이고 직접 익명 접근은 차단됨을 확인했다. 전체 IAM 권한·로그를 검토한 것은 아니다.
- 프록시 보안 단위 검사 `node --test frontend/server/cloud-run.test.cjs`: 4/4 통과. 경로/외부 호스트 차단, 헤더/사용자 토큰과 IAM 토큰 분리, 실패 시 upstream 미호출, 다운로드 응답 처리 등을 모의 fetch로 확인했다. 침해 여부나 Node 바이너리 패치를 검증하는 검사가 아니다.

## 구성 및 영향

| 대상 | 확인 사항 | 판단·조치 |
|---|---|---|
| Python FastAPI/Cloud Run | Python 기반 Dockerfile, PHP 코드·설치·실행 설정 미발견 | PHP2Shell 직접 대상인 구성은 발견되지 않음. 실행 이미지 SBOM은 미확인 |
| Vercel API 프록시 | Node.js 함수, 고정 Cloud Run/Google 인증 주소에 fetch 사용 | Node Brotli 및 기타 보안 릴리스의 실제 운영 패치 확인 필요 |
| 로컬 Node | v24.16.0 | 10월 21일 보안 수정 24.22.1보다 이전. 패치된 24.x로 업데이트 필요 |
| React | React/ReactDOM 18.3.1, Next·react-server-dom-* 없음 | 이번 확인한 RSC 원격 코드 실행 취약점의 해당 패키지 미사용 |
| Python 명시 의존성 | 운영 커밋의 13개 고정 버전을 OSV querybatch와 대조 | langgraph-checkpoint-postgres 3.1.2에서 알려진 advisory 1개 일치. 미고정 tzdata·전이 의존성은 이 검사에 미포함 |

Vercel 공식 공지는 Node.js 22.23.4/24.22.1/26.12.1을 안내하고, 관리 런타임 패치를 배포 중이라고 설명한다. WAF는 가져오는 외부 응답을 보호하지 않으므로 WAF만으로 패치 완료를 판단하지 않는다. 프록시 upstream은 사용자 지정 URL이 아니라 고정 주소이고 redirect를 거부해 일부 공격 표면은 줄지만, 이것이 런타임 업데이트를 대체하지 않는다. package.json에는 engines.node가 없어 저장소만으로 운영 Node major도 확정하지 못했다.

## npm 잠금 파일 검사

`npm audit --package-lock-only --ignore-scripts --json` 실행. 공식 npm registry에 공개 패키지 이름·버전으로 조회했으며 설치·자동 수정은 하지 않았다.

결과: info 0 / low 9 / moderate 30 / high 25 / critical 2 / total 66. 이는 npm이 표시한 영향 패키지 수이고 중복된 전이 경로·빌드 도구를 포함한다. 66개가 전부 운영 요청에서 공격 가능하다는 뜻이 아니다.

| 항목 | 경로·조건 | 권고 |
|---|---|---|
| DOMPurify 3.4.16 (critical) | posthog-js의 전이 의존성. 앱에서 직접 sanitize 호출은 발견되지 않았고 surveys/session recording/external loading이 꺼져 있다. 특정 DOM 반환/후크/XML 모드의 취약 조건이 실제 사용되는지는 입증되지 않음 | 수정 버전 3.4.17 이상으로 잠금 해소 및 프런트 회귀 필요 |
| shell-quote 1.10.0 (critical) | react-dev-utils/launch-editor 개발 도구 경로. Node 운영 프록시가 직접 import하지 않음. 공격자 입력을 quote/쉘 실행으로 전달하는 경로는 입증되지 않음 | 1.11.0 이상으로 해소하고 빌드/개발 도구 확인 |
| Zod 4.1.11 (high) | @vercel/oidc → @vercel/cli-config. 검증 대상의 비신뢰 대형 배열 도달 여부는 미입증 | 수정 4.6.6 이상과 SDK 호환성 검토. audit가 제안하는 SDK downgrade를 무조건 적용하지 않음 |
| 나머지 react-scripts 전이 항목 | 개발 서버·번들/최적화 도구와 브라우저 의존성이 혼재 | 원시 audit의 경로를 따라 운영/브라우저/빌드별 수정 묶음으로 처리. `npm audit fix --force` 금지 |

## Python advisory

`langgraph-checkpoint-postgres==3.1.2`는 GHSA-6hmw-9432-67qq / CVE-2026-115883의 영향 범위(<3.1.3)에 해당한다. 원문은 namespace 라벨을 점으로 합치는 PostgresStore/SQLiteStore 경로의 검증 누락을 설명한다. 앱 코드에서는 PostgresSaver를 사용하며 langgraph.store/PostgresStore/AsyncPostgresStore 사용은 발견하지 못했다. 따라서 취약 패키지 버전 사용은 확인했지만 현재 요청에서 다른 사용자의 데이터에 접근 가능하다고 단정하지 않는다.

수정 3.1.3은 langgraph-checkpoint 4.3.0도 요구하므로 현재 고정 4.2.0과 함께 호환성 변경이 필요하다. 단일 버전 줄만 올리지 말고 상담 저장·복원·사용자 격리 회귀를 수행해야 한다. 운영 이미지에서 설치 버전 및 전이 의존성을 다시 검사해야 한다.

## 운영 조회 차단과 남은 확인

Vercel 계정에는 2FA 안내가 표시됐다. 이 안내의 'Skip securing my account' 클릭은 자동 승인 검토에서 보안 상태 변경으로 거부됐다. 재시도나 다른 방법의 UI 우회를 하지 않았으며 계정·2FA 설정도 변경하지 않았다. 사용자에게 안내 화면 처리를 요청했고, 페이지를 인계 상태로 유지했다. 이 때문에 현재 운영 Node patch 버전, function 로그와 WAF 사건 기록 확인은 미완료다. 침해 여부를 판단한 보고서는 아니다.

다음 조치 우선순위: (1) 운영 Node major/patch 및 Vercel 패치 완료 확인, 로컬 Node 업데이트, (2) DOMPurify·shell-quote 및 OIDC/Zod 의존성 해소, (3) Python 관련 패키지 동반 업데이트와 저장/복원 회귀, (4) 운영 이미지·전이 의존성·로그 확인. 이번 점검으로 대량 계산 미커밋 변경을 운영 반영하지 않는다. 보안 수정은 운영 main 기준 별도 최소 변경으로 준비해야 한다.

## 증거·제한

증거 폴더: `C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent/tmp/security-audit-20261025` (`npm-audit.json`, `python-direct-osv.json`, `public-health-checks.json`, `summary.json`). 비밀값·쿠키·토큰·사용자 대화·DB 내용을 저장하거나 공개하지 않았다. 운영 설정·패키지·DB 수정, 배포, 유료 모델 호출은 없다. 저장소 점검·공개 health와 unit 검사만으로 침해 부재를 보증하지 않는다.

## 공식 근거

- PHP: https://www.php.net/archive/2026.php#2026-10-21-5
- Node.js: https://nodejs.org/en/blog/vulnerability/october-2026-security-releases
- Vercel: https://vercel.com/kb/bulletin/node-js-security-advisory
- React: https://github.com/react/react/security/advisories/GHSA-xqc2-xf4c-x3h3
- DOMPurify: https://github.com/advisories/GHSA-cg2g-xh64-v4q7
- shell-quote: https://github.com/advisories/GHSA-pqg4-j6r4-53mv
- Zod: https://github.com/advisories/GHSA-mrhx-c7xc-m3w5
- LangGraph: https://github.com/langchain-ai/langgraph/security/advisories/GHSA-6hmw-9432-67qq
