# 개발 흐름 (2026-11-07부터)

## 브랜치 3단계

```
작업 브랜치 (feat/…, fix/…, chore/…)
   │  PR → dev 로 머지
   ▼
dev        ← 로컬에서 백엔드·프론트를 띄워 확인
   │  문제없으면 PR → main 으로 머지
   ▼
main       ← 머지되면 자동 배포 (백엔드: Cloud Run, 프론트: Vercel)
```

- 작업 브랜치는 항상 `dev`에서 만들고, PR 대상도 `dev`다.
- `main`으로는 `dev`에서 확인을 마친 PR만 보낸다. 운영 핫픽스만 예외로 `main`에서 바로 만들고, 머지 뒤 `dev`에 `main`을 합친다.
- 백엔드 자동 배포는 `main` 푸시 중 `backend/`, `data/rates/`, `data/drafts/`, `deploy/`, `Dockerfile` 등이 바뀐 경우에만 돈다(`.github/workflows/deploy-backend.yml`).

## dev 확인 (로컬)

저장소 루트에서 `dev`를 받은 뒤:

```bash
git checkout dev && git pull
.venv/Scripts/python.exe scripts/dev_server.py
```

```bash
cd frontend && set PORT=3001&& set BROWSER=none&& set CIVILAI_API_PROXY=http://127.0.0.1:8001&& npm start
```

브라우저에서 http://localhost:3001 을 연다. (Claude 데스크톱 앱에서는 `.claude/launch.json`의 `backend-local`, `frontend`로 띄울 수 있다.)

`scripts/dev_server.py` 기본 모드는 운영과 같은 경로다.
- Gemini 켜짐, 품셈 지식 검색 v1. 품셈 지식 DB는 `.env`의 연결을 **읽기 전용**으로만 쓴다.
- 대화 저장·사용량 DB는 끈다(로컬 대화가 운영 DB에 쌓이지 않게). 그래서 **비회원으로 시험**한다. 회원 대화 저장은 로컬에서 동작하지 않는다.
- `--offline`: 외부 호출 없이(Gemini 끔) 화면 배치만 볼 때.

## 주의

- Vercel PR 미리보기는 화면만 새 버전이고 **백엔드는 운영 서버**로 간다(`frontend/server/cloud-run.cjs`). 백엔드 변경은 미리보기로 확인할 수 없다 — 로컬에서 확인한다.
- 실제 Gemini 호출은 비용이 든다(질문당 수 원 수준).
