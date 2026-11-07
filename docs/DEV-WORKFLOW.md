# 개발 흐름 (2026-11-07부터)

## 브랜치

```
main 에서 작업 브랜치 (feat/…, fix/…, chore/…, style/…)
   │  작업 브랜치를 로컬에서 띄워 확인
   │  PR → main
   ▼
main       ← 머지되면 자동 배포 (백엔드: Cloud Run, 프론트: Vercel)
```

- 별도 dev 브랜치나 스테이징 서버는 두지 않는다. 로컬에서 띄운 서버가 개발 서버다.
- 작업 브랜치는 항상 최신 `main`에서 만들고, main으로 PR 하기 전에 그 브랜치를 로컬에서 확인한다.
- 백엔드 자동 배포는 `main` 푸시 중 `backend/`, `data/rates/`, `data/drafts/`, `deploy/`, `Dockerfile` 등이 바뀐 경우에만 돈다(`.github/workflows/deploy-backend.yml`).

## 로컬 확인

저장소 루트의 PowerShell에서 터미널 두 개로 각각 실행한다.

```powershell
.venv/Scripts/python.exe scripts/dev_server.py
```

```powershell
cd frontend; $env:PORT='3001'; $env:BROWSER='none'; $env:CIVILAI_API_PROXY='http://127.0.0.1:8001'; npm start
```

브라우저에서 http://localhost:3001 을 연다. (Claude 데스크톱 앱에서는 `.claude/launch.json`의 `backend-local`, `frontend`로 띄울 수 있다.)

`scripts/dev_server.py` 기본 모드는 운영과 같은 경로다.
- Gemini 켜짐, 품셈 지식 검색 v1. 품셈 지식 DB는 `.env`의 연결을 **읽기 전용**으로만 쓴다.
- 대화 저장·사용량 DB는 끈다(로컬 대화가 운영 DB에 쌓이지 않게). 그래서 **비회원으로 시험**한다. 회원 기능은 운영에서 테스트 계정으로 시험한다.
- `--offline`: 외부 호출 없이(Gemini 끔) 화면 배치만 볼 때.

## 주의

- 로컬 화면의 구글 로그인은 Supabase Redirect URLs에 `http://localhost:3001/**`가 없으면 운영 사이트로 넘어간다.
- Vercel PR 미리보기는 화면만 새 버전이고 **백엔드는 운영 서버**로 간다(`frontend/server/cloud-run.cjs`). 백엔드 변경은 로컬에서 확인한다.
- 실제 Gemini 호출은 비용이 든다(질문당 수 원 수준).
