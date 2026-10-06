# 품셈이 배포

확정 구성: Vercel 프론트, GCP Cloud Run 백엔드, 기존 Supabase 운영 DB.
GCP 프로젝트는 `civil-ai-jds`, Cloud Run 리전 후보는 서울 `asia-northeast3`.

## 현재 준비한 것

- Dockerfile: Python 3.14, 한 API worker, 일반 사용자 실행, 플랫폼 PORT 사용.
- 임베딩 Parquet, 청크, 페이지 맵, 품셈 PDF, 규칙·단가 JSON을 백엔드 이미지에 포함.
- .dockerignore와 .gcloudignore 및 배포 번들은 환경변수 파일·프론트·개발 환경을 제외.
- 배포 번들의 PDF 파일명은 영문 `standard-estimation-2026.pdf`로 고정한다. Docker COPY가 런타임에서 사용하는 원래 한글 이름으로 배치한다. 이미지 빌드 중 PDF 열기와 검색 데이터 존재 여부를 검사하여 누락이면 빌드 단계에서 실패시킨다.
- Docker 빌드 컨텍스트는 `deploy/prepare_backend_bundle.py`로 만든 ZIP의 압축 해제 폴더를 사용한다.
- 운영 환경은 원문·검색 인덱스 준비가 끝난 뒤 ASGI startup을 완료한다. 요청 기반 Cloud Run의 CPU 제한으로 백그라운드 초기화가 멈추지 않게 하며, 준비 실패 시 프로세스 startup을 실패시켜 잘못된 revision에 트래픽이 넘어가지 않게 한다. 개발 환경의 비동기 준비/상태 표시는 유지한다.
- `deploy/prepare_backend_bundle.py`로 서버 소스 번들을 생성.
- `deploy/cloud-shell-build.sh`는 API 활성화·이미지 저장소 생성·빌드만 수행하며 서비스를 공개하지 않음.

## 다음 단계

1. Cloud Shell을 열고 `tmp/poomsemi-backend-deploy.zip` 업로드.
2. 새 폴더에서 압축을 풀고 `bash deploy/cloud-shell-build.sh` 실행.
3. 빌드된 이미지로 Cloud Run을 설정. 초기 후보: CPU 1, 메모리 2 GiB, 요청 기반 과금, 최소 0·최대 1 인스턴스, 동시 요청 4, 타임아웃 120초.
4. `deploy/backend.env.example`의 서버 설정을 실제 값으로 연결. 비밀 값은 Secret Manager 사용.
5. Vercel의 프로젝트 root는 `frontend`, 빌드 `npm run build`, output `build`로 설정.
6. 프론트에는 공개 Supabase 키·PostHog 토큰만 넣고 서버 비밀키·DB 연결 문자열은 넣지 않음. `REACT_APP_API_URL`은 비워 두어 동일 사이트 `/api`를 사용.
7. 배포된 프론트 주소를 서버 ALLOWED_ORIGINS, Supabase Site URL/redirect 허용 목록 및 Google OAuth 설정에 반영.

## 공개 전 해결할 항목

- Vercel 프록시와 아래 IAM 설정을 배포하고 실제 접속 IP로 비회원 제한이 적용되는지 확인.
- 사용량 DB 한도는 이미 영속적이지만, 로그인하지 않은 대화는 서버 임시 메모리다. Cloud Run 재시작·인스턴스 변경 시 만료될 수 있으며 최소 인스턴스 1도 영속성을 보장하지 않는다.
- 임베딩 색인은 Gemini Studio의 `gemini-embedding-2`이고 LLM 설정은 Vertex다. GCP $300 크레딧이 두 API 모두에 적용된다고 가정하지 않음. 적용 과금 계정을 각각 확인.
- AI 호출·토큰·오류 집계와 비용 알림, 개인정보처리방침의 운영·국외 처리 세부 정보 확정.
- 실제 이미지 빌드·컨테이너 준비 시간/메모리 검증, 배포 로그인·탈퇴 테스트는 아직 완료하지 않음.
- 최대 인스턴스 수나 비용 알림을 절대적인 청구 상한으로 간주하지 않음.

코드와 환경 설정 준비와 실제 서비스 배포는 별도 단계다. 현재 문서는 서비스 공개 완료를 의미하지 않는다.

## Vercel → Cloud Run 인증 연결

- 프론트 프로젝트 root: `frontend`. `frontend/api/[...path].js`가 같은 사이트 `/api/*`를 받아 Cloud Run으로 전달한다. SPA 경로는 `frontend/vercel.json`에서 처리한다.
- 현재 프로젝트: 팀 slug `bidfriend`, 프로젝트 이름 `civilai-construction-risk-agent`, production 환경. Vercel OIDC issuer mode는 Team.
- GCP pool `poomsemi-vercel`, provider `vercel`. Issuer `https://oidc.vercel.com/bidfriend`, allowed audience `https://vercel.com/bidfriend`, subject mapping `assertion.sub`.
- Provider condition 및 caller 서비스 계정의 `roles/iam.workloadIdentityUser` principal은 `owner:bidfriend:project:civilai-construction-risk-agent:environment:production` 하나로 제한.
- Caller `poomsemi-vercel-caller@civil-ai-jds.iam.gserviceaccount.com`에는 `poomsemi-api` 서비스의 `roles/run.invoker`만 부여한다. DB·Secret Manager 권한은 부여하지 않는다.
- 런타임 서비스 계정 `poomsemi-api-runtime`과 caller는 분리. 서비스 계정 JSON 키는 만들지 않는다.
- Cloud Run은 **인증 필요 / IAM** 유지. `allUsers`, `allAuthenticatedUsers` invoker 접근이 없어야 한다. ingress All은 IAM 인증을 해제하지 않는다.
- 프록시는 Vercel OIDC → Google STS → IAM Credentials `generateIdToken`으로 인증한다. Google 토큰은 `X-Serverless-Authorization`, Supabase 사용자 토큰은 기존 `Authorization`으로 전달한다. 토큰은 서버 메모리에 만료 1분 전까지 보관하며 클라이언트에 반환하거나 로그에 기록하지 않는다.
- Cloud Run URL: `https://poomsemi-api-691785957289.asia-northeast3.run.app`. GCP 호출 설정은 서버 모듈에만 포함되어 추가 비밀 환경변수가 필요 없다.
- **백엔드 이미지를 새 코드로 업데이트하고 `CLIENT_IP_SOURCE=vercel` 추가.** 이 설정은 위 IAM 경계가 유지될 때만 사용한다. 프록시가 플랫폼의 `x-forwarded-for`를 검사한 후 `X-Poomsemi-Client-IP`를 직접 설정한다. 브라우저가 보내는 동명 헤더는 전달하지 않는다. 백엔드는 누락·잘못된 IP에서 503을 반환하고 IPv4-mapped IPv6를 정규화한다.
- Vercel Fluid compute 사용, 프록시 maxDuration 150초. Cloud Run timeout 120초, 프록시 upstream timeout 115초. 자동 요청 재시도는 하지 않아 견적 사용량이 중복 차감되지 않게 한다.
- 현재 로컬 모의 테스트는 토큰 분리, IP 위조 헤더 제거, 경로 탈출 방지, 엑셀 바이너리·파일명 및 429 전달, 인증 실패 후 재시도를 검증한다. 실제 Vercel 함수의 라우팅/OIDC와 Cloud Run 연결은 배포 후 확인해야 한다.
- 배포 확인: Cloud Run 직접 호출은 IAM 거부, Vercel `/api/health` 및 `/api/ready` 확인, 로그인/비회원 견적·엑셀·사용량 확인. Preview 환경은 의도적으로 GCP 권한이 없다.

공식 문서: https://vercel.com/docs/oidc/gcp, https://vercel.com/docs/headers/request-headers, https://docs.cloud.google.com/run/docs/authenticating/service-to-service

## main 머지 후 백엔드 자동 배포

- `.github/workflows/deploy-backend.yml`은 main의 백엔드·규칙·배포 설정 변경 또는 main에서의 수동 실행으로 동작한다. 프론트만 수정하면 백엔드 빌드를 실행하지 않는다. PR/fork와 다른 브랜치에는 배포 권한이 없다.
- 초기 설정은 Cloud Shell에서 `deploy/setup_github_deploy.py`를 한 번 실행한다. 같은 폴더의 `serving_assets.py`, `serving-assets.json`도 필요하다. 기본 소스는 기존 `~/poomsemi-deploy`이며, PDF 이름이 깨져도 원본 SHA-256이 일치하는 파일만 선택한다. 5개 원본을 검증한 다음 클라우드 설정을 시작한다.
- 서버 데이터 5개는 서울의 비공개 GCS bucket `civil-ai-jds-poomsemi-assets`의 `serving/20261006`에 저장한다. uniform bucket-level access와 public access prevention을 설정한다. 원문 PDF나 임베딩을 GitHub 공개 저장소에 추가하지 않는다.
- GitHub Actions는 저장소에 커밋한 `deploy/serving-assets.json`의 크기 및 SHA-256을 검증한 뒤 기존 임베딩을 이미지에 포함한다. 임베딩을 다시 생성하지 않는다. 검색 데이터가 업데이트되면 새 GCS version 경로와 manifest를 함께 변경한다.
- WIF pool `poomsemi-github`, provider `github`, issuer `https://token.actions.githubusercontent.com`. 숫자 repository ID `1277805743`, owner ID `164707261` 및 main ref를 모두 조건으로 제한하고, 서비스 계정 impersonation principal도 정확한 main subject 하나만 허용한다.
- 전용 배포 계정 `poomsemi-github-deploy`는 해당 bucket의 Object Viewer, `poomsemi` Artifact Registry의 Writer, 기존 `poomsemi-api`의 Cloud Run Developer, `poomsemi-api-runtime`의 Service Account User 권한만 사용한다. 프로젝트 Owner/Editor, Secret Manager 직접 조회, API invoker, 서비스 계정 키는 부여하지 않는다. 런타임, Vercel caller, CI deployer는 서로 다른 계정이다.
- GitHub 공식 Actions는 commit SHA로 고정한다. 인증 credential 파일은 `.gitignore`와 Docker 허용 목록에서 제외된다. Docker 빌드 후 인증을 갱신하고 이미지를 push한다.
- 저장소가 공개이므로 PDF·임베딩이 포함된 Docker layer를 GitHub Actions cache/artifact에 저장하지 않는다. 이미지는 비공개 GCP Artifact Registry에만 push한다.
- 빌드 이미지 태그는 Git commit SHA. 서비스 업데이트는 이미지 및 `CLIENT_IP_SOURCE=vercel`만 변경하며 기존 IAM, 비밀 값, CPU/메모리/스케일링 설정을 유지한다. 자동 배포는 같은 서비스에 동시에 실행되지 않는다.
- 마지막에 Vercel `/api/ready`를 통해 실제 IAM 프록시 및 서버 준비 상태를 확인한다. 실패하면 Actions가 실패로 표시된다. 배포 후 readiness 실패 시 자동 rollback은 하지 않으므로 로그 확인 또는 기존 정상 revision으로 복구해야 한다.
- 운영 상태는 GitHub → Actions → Deploy backend에서 확인한다. GitHub Actions/OIDC와 GCP 실제 권한 적용은 초기 설정 및 첫 머지 배포 후 검증한다.

GitHub 인증 공식 문서: https://github.com/google-github-actions/auth
