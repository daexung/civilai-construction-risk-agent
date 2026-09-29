# 공사비 챗봇 화면

`api/main.py`(FastAPI)가 `agent/graph.py`의 `route → retrieve → select → fill ⇄ ask → gate → compute → price → statement → compose` 흐름을 호출하고, 한 페이지 채팅 화면이 결과를 보여준다. 범위 밖이면 `OUT_OF_SCOPE`, 명세 없이 근거만 있으면 `EVIDENCE_ONLY`로 끝난다. 조건이 부족하면 `MISSING_INFO`로 질문하고 답변을 받아 `fill`로 돌아간다. 조건이 모이면 `gate`가 계산 보류 여부를 확인한 뒤 계산·단가·원가계산서를 만들고 `OK` 또는 `PARTIAL`로 답한다. 상태와 이유는 `status`, `reason`에 담기며 검색 방식은 `search_info`, 근거는 `hits`, 입력은 `inputs`, 계산 결과는 `result`, 가격 결과는 `priced`, 원가계산서는 `statement`에 저장된다. 로그인·프로젝트·대화 목록·설정 화면은 없다.

## 실행

API 서버와 화면을 각각 다른 터미널에서 띄운다.

```powershell
# 1) API 서버 (저장소 루트에서)
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
# 오프라인(BM25)만 쓰려면: $env:AGENT_OFFLINE = "1"

# 2) 화면 (frontend/에서, 최초 1회 npm install)
cd frontend
npm install
npm start
```

`npm start`는 `package.json`의 `proxy` 설정으로 `/api/*` 요청을 `http://localhost:8000`으로
넘긴다. 브라우저에서 http://localhost:3000 을 연다.

운영 빌드에서 API 서버 주소가 다르면 `frontend/.env`에 다음을 넣고 빌드한다.

```
REACT_APP_API_URL=https://your-api-host
```

## 빌드

```powershell
npm run build
```

## 화면 구성

- 채팅 목록 + 입력창 한 페이지. 새로고침하면 대화가 사라진다(저장 없음).
- 에이전트 응답은 상태별 카드로 보여준다: `MISSING_INFO`(선택지 버튼 + 힌트 + 판정표 + 자유
  입력창), `READY`(공종·입력값 표), `EVIDENCE_ONLY`(근거 목록), `OUT_OF_SCOPE`(안내 문구).
- 검색이 임베딩 하이브리드가 아니라 BM25로 대체됐으면 노란 경고 띠가 뜬다.
- 상단 "새 대화" 버튼이 thread_id를 초기화한다.
