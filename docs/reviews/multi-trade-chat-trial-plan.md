# 복수 공종 상담 화면 연결 설계

## 결정할 범위

이 단계는 기존 복수 공종 범위 확인·항목별 품/가격·통합 계산·XLSX 흐름을 브라우저에서 실제 로컬 검색 결과로 연결한다. 기존 `backend/api/item_labor_trial.py`의 `/api/item-labor` 흐름과 `frontend/src/components/LocalTrial.tsx`의 단일 질의·답변 화면은 목적이 다르므로 섞지 않는다. 별도 기본 꺼짐 화면(`/estimate-trial`)과 로컬 전용 API를 둔다. 화면은 다음 순서를 고정한다.

1. 사용자가 요청문 입력
2. 구절별 공종·바탕·조건·제외 후보와 미확정 구절 표시
3. 모든 span의 명시적 선택을 받은 뒤 확인증 생성
4. 확인된 항목만 각자 검색하고, 후보 불확실 시 항목별 기존 질문 흐름 사용
5. 필요한 조건 질문과 답변을 항목 ID·질문 ID·질문 버전에 묶어 처리
6. 품·가격 계산 및 기존 합산 도구로 부분/완료 상태 표시
7. 최신 통합 결과만 기존 XLSX 생성기로 내려받기

범위가 확인되지 않았거나 검색/지원 불가인 항목은 합계에서 빠진 사실과 이유를 보존한다. `PARTIAL` 금액을 전체 견적액으로 부르지 않는다. 클라이언트가 검색 후보 `hits`를 보내는 현 API 계약은 실제 연결에서 제거한다.

## 검색·데이터 확인 (2026-10-16 체크아웃)

- 현재 브랜치 `codex/multi-trade-chat-trial`에는 기존 기능 커밋을 보존한 채 `origin/main`을 병합했다. 사용자가 승인한 `git fetch origin main` 결과 최신 `origin/main`은 `43d66f8` (PR #44, 상담 첫 화면 복원/오류 처리)였다. 네 파일 변경 diff를 읽고 충돌 없이 병합했다. 다른 미완성 브랜치는 가져오지 않았다.
- 현재 worktree에는 `data/processed/chunks.all.jsonl`(5,791,124 bytes)과 `chunks.jsonl`(182,707 bytes)이 있다. 그러나 사용자가 지정한 원본 저장소 `C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent`에는 별도 ignored 자산이 있다. 여기에는 `data/knowledge/vectors.parquet`(71,930,286 bytes), `manifest.json`(701 bytes), `data/processed/embeddings.all.gemini-embedding-2.parquet`(60,184,376 bytes), `page_map.json`(244,575 bytes), retrieval-v1의 문서 임베딩 캐시(95,625,991 bytes), 질의 캐시(2,126,996 bytes)가 있다. 원본 자료는 읽기만 했다.
- 원본 `data/knowledge/manifest.json`은 `ready=true`, `targets=vectors=5,764`, 모델 `gemini-embedding-2`, 차원 3072, 입력 형식 `doc-title-none-v1`, chunk set `cs-37f81b5cfb1b-46f4f035c0fa`, release `rk-complete-82c206c61e21-37f81b5cfb1b`를 기록한다. Parquet SHA-256은 manifest와 일치한다. 로컬 원본 Parquet을 읽어 5,764행, 5,764 unique chunk ID를 확인했다. 다만 현재 `data/processed/chunks.all.jsonl`은 4,813개 ID이며 vector ID와 교집합이 0이다. 이 vectors 파일만 현재 청크 파일과 붙여 검색 결과·원문을 만들 수 없다.
- retrieval-v1의 질의 캐시에는 127개 행이 있다. 모두 `studio`, `gemini-embedding-2`, 3072, `query-task-search-result-v1`, `purpose=query`다. 질의 텍스트는 출력하거나 저장하지 않았다. 캐시는 일부 기존 질의만 다루며 새 항목 요청의 임베딩이 반드시 캐시된다고 보장하지 않는다.
- Supabase 설정 파일에는 로컬 DB 포트 54322가 적혀 있지만 이 실행 환경에서 Docker/Supabase CLI, 해당 포트 listener, 로컬 DB 프로세스는 확인되지 않았다. 환경/저장 설정에는 비로컬 DSN이 존재할 수 있었지만 원격 여부를 출력하지 않고 원격 연결은 시도하지 않았다. `parsed.jsonl`도 없다. 따라서 DB에 저장된 vector와 text의 chunk set/release 정합성은 아직 검증되지 않았다.
- 검색은 원본 `KNOWLEDGE_ASSET_DIR`의 pinned release/chunk/vector/query-cache 파일을 읽기 전용으로 사용한다. `backend/agent/estimate/local_v1_search.py`는 manifest 파일 해시, chunk/vector ID·입력 해시·모델·차원, section registry 및 source role을 확인하고 기존 `Retriever.search(mode="hybrid")`에 검증된 파일 자산을 주입한다. Retriever 생성자(DB open 및 임베딩 client 생성)는 호출하지 않고 `embed_queries=False`로 고정한다. exact query cache miss는 `CACHE_MISS`로 반환하며 외부 임베딩·fallback 검색은 없다. 같은 Retriever 구현과 release 파일을 사용한 실제 로컬 hybrid 검색이지만, 운영 DB 연결이나 DB 내 원문 인용 조회까지 검증했다는 뜻은 아니다.
- 검증한 캐시 적중 질의 `시멘트 액체방수를 바닥에 300㎡ 바르려면 인력 품은 어떻게 잡아야 해?`는 후보 10개와 `api_calls=0`을 반환했다. 캐시 미스도 확인했고 임베딩 client/embed 함수는 호출되지 않았다. 이 exact query cache가 모든 새 요청을 지원하지는 않는다.

## 기존 코드 경로와 외부 호출 차단

- `backend/agent/estimate/tools.py::find_work(session, hits=None)`는 `hits=None`이면 `backend.agent.nodes.retrieve.retrieve`를 호출한다. 이 경로는 `AGENT_OFFLINE=1`일 때만 `make_search_index(offline=True)`로 BM25를 쓴다. 기본 하이브리드 경로는 `VectorIndex.search_many`에서 매 질의 임베딩을 만든다.
- `backend/agent/tools/search/vector.py::VectorIndex`에는 질의 임베딩 캐시가 없다. 벡터 인덱스가 존재해도 `embed_queries()`가 기본 client와 `embed_texts()`를 호출한다. 현재 청크 설정이 가리키는 Parquet 벡터는 없다. 이 경로를 그대로 열면 인덱스 시작 실패 또는 질의 임베딩 외부 호출 가능성이 있어 연결에 사용하지 않는다.
- `backend/knowledge/runtime.py::Engine.__init__`은 `KNOWLEDGE_RETRIEVAL=v1`일 때 모델 client warmup 후 DB를 열고 Retriever 및 `page_map.json`을 읽는다. UI 검색에 이 Engine을 만들지 않는다. 직접 `Retriever(conn=..., embed_queries=False)`를 사용하면 답변 모델 warmup은 건너뛸 수 있고, 질의 cache miss에서 `RuntimeError`로 중단한다. 다만 현재 `backend/knowledge/embed_index.py::load_cache()`는 빈 맵을 반환하고 저장 함수도 no-op이므로 실험 cache를 안전하게 주입할 옵션이 필요하다.
- retrieval-v1 질의 캐시는 정확한 포장 입력 해시만 재사용한다. 127행이라는 크기만으로 새 견적 구절이 적중한다고 보장하지 않는다. 단계 검사는 cache hit과 miss를 각각 확인하고, miss 때 외부 client/embed 함수가 호출되지 않으며 사용자에게 검색을 못 했다고 드러내야 한다. 일부 cache hit로만 실행한 경우 그 한계를 응답에 함께 표시한다.
- Docker Engine의 named pipe에 접근할 수 없어 로컬 DB 상태는 확인하지 못했다. 비로컬 DSN 연결, DB 쓰기/적재/마이그레이션은 하지 않았다. pinned 파일 자산 경로를 운영 DB Retriever 연결로 표현하지 않는다.

## 화면·API와 기존 계약

- 기존 `POST /api/chat`, 회원/비회원 ownership, usage 제한·차감, idempotency, `chat_storage` 저장, answer-run trace, 기존 XLSX export는 변경하지 않는다. 범위 시험은 기존 대화의 thread나 사용자 기록을 읽거나 쓰지 않는다.
- 새 화면은 `REACT_APP_MULTI_TRADE_TRIAL=on`일 때만 `/estimate-trial`에 노출한다. 기존 독립 FastAPI 앱을 loopback의 별도 포트로 실행하고, React 개발 proxy를 그 포트로 지정한다. 앱 기본 `main.py`와 전체 lifespan에 이 시험 API를 붙이지 않는다. API의 `LOCAL_TRIAL_ITEM_LABOR=on`, non-production, loopback 조건을 유지한다. 실제 제품 `/chat`과 별도인 휘발성 로컬 시험 세션임을 화면에 표시한다. 서버 재시작 후 복구되지 않고 운영 계정 저장·사용량 차감 대상이 아니다. 기존 로그인 상태, 대화 목록, 요금/사용량 UI와 섞지 않는다.
- trial API는 요청마다 loopback·옵션·production 가드를 확인한다. `/items/{id}/search`는 빈 요청 본문만 허용하고, 확인한 항목의 `request_text`로 검색한다. 랜덤 owner token 원문은 analyze 응답에서 한 번 반환하고 서버 메모리에는 SHA-256만 저장한다. 모든 후속 경로에서 constant-time 비교한다. `/invalidate`는 원문/범위/가격 기준일 수정 뒤 aggregate 결과를 제거한다. 서버 재시작 시 토큰과 trial은 함께 사라진다.
- 기존 scope 확인증은 원문 해시·분석 버전·선택에 묶여 있다. 모든 선택을 요구하는 동작과 안정 span/item ID를 유지한다. 검색은 항목이 확인된 뒤에만 허용한다. 수정 후 재확인, 질문 ID/버전 검증, 기존 상태(`NEEDS_INPUT`, `UNSUPPORTED`, `NOT_FOUND`, `PARTIAL`, `COMPLETE`, 가격 버전 충돌 등), 직접비 집계, 최신 결과 무효화, XLSX 생성기를 그대로 쓴다.
- 프런트엔드는 최소 입력·상태 UI만 새로 만든다. 단계별 버튼은 API 성공 후 다음 단계에서만 활성화한다. 서버가 돌려준 원문 범위 및 질문에 대한 사용자 선택은 상태에 명시적으로 보인다. 네트워크 오류나 409는 최신 상태를 새로 읽도록 안내한다. XLSX URL은 시험 API에서 내려받는다.
- 로컬 trial은 기존 회원/사용량/영속성 계약을 흉내 내거나 그 보안 보장을 주장하지 않는다. 별도 trial 페이지를 제품 상담으로 오인할 수 있다는 점은 문서와 화면에 고정 표시한다. 사용자 식별/영속성까지 요구되는 제품 연결은 이번 범위가 아니며 별도 계약 설계·승인이 필요하다.

## 상태·출처·오류 표시

공개 응답은 범위 상태, 각 항목 검색 방식/후보와 선택, 질문 상태, 품/가격 상태, aggregate 상태, 자료 버전, 다운로드 가능 여부를 구분한다. 검색 출처에는 `local_chunks_bm25`와 설정/청크 파일 식별 정보를 포함할 수 있으나 원문 개인정보나 입력 전체를 로그로 남기지 않는다. 기존 trial 로그 파일에 요청 본문을 추가 저장하지 않는다.

`PARTIAL`은 계산된 항목의 부분 합계이며 누락·미지원 항목은 별도 목록으로 남긴다. `PENDING`/`NO_RESULT`/공통조건 질문/버전 충돌은 최신 완성 파일로 오인하지 않도록 다운로드를 막는다. 가격표/근거가 없는 계산값을 검색 근거로 주장하지 않는다.

## 검사 및 확인 방법

1. route/API 통합 검사는 검색 `hits` 입력이 거부되고, 검증된 데이터 경로가 실제 후보를 반환하는지 확인한다. `Retriever` 사용 시 cache hit·miss의 provenance와 외부 embed/client 함수 호출 0을 검사한다. DB/자산을 준비할 수 없으면 실제 검색 통합 확인은 보류로 기록한다.
2. scope span 누락·중복, 다른 원문/선택 해시, item ID 교차, 오래된 질문 버전, 수정 후 재확인 누락, session 소유 토큰 불일치, disabled/production/non-loopback 가드, 부분 결과 XLSX, 최신 결과 무효화를 검사한다.
3. 외부 API 없이 기존 DB+asset+exact query cache로 실행하는 통합 스크립트를 우선 준비한다. 현재 로컬 DB가 없어 이 스크립트의 실제 retrieval 검사는 미실행이다. 별도 BM25 시험을 택하면 이를 운영 경로 통합과 분리해 결과를 기록한다.
4. 브라우저는 별도 loopback API와 CRA dev server에서 확인한다. `/estimate-trial` wrapper는 해당 화면에서 ChatApp 번들을 지연 로드해 auth/usage/storage/analytics effect가 실행되지 않게 한다. `ChatApp.tsx`는 최신 `origin/main` `App.tsx`와 줄바꿈/기본 함수명 정규화 후 동등하다는 검토를 받았다.

## 이전 API 검사 실패의 분리

`docs/reviews/multi-trade-summary.md`는 기존 `evals/check_api.py`의 전체 회귀가 `page_map.json` 부재로 앱 시작 검증에서 실패하고, 별도로 gate 경로 `TypeError`가 있었다고 기록한다. 현재 체크아웃에서도 `page_map.json`과 `parsed.jsonl`이 빠져 있어 시작/인용 관련 전체 회귀는 재현 가능한 조건이 아니다. 기록에는 TypeError의 전체 traceback/입력이 없어 원인을 특정할 수 없다. 이를 새 복수 공종 검색 연결의 통과 증거로 삼지 않고, 새 실검색 route 검사와 기존 gate 집중 회귀를 나눠 보고한다. 필요하면 누락 파일을 공급하는 승인된 로컬 fixture로 재현하되 PDF 재파싱/데이터 적재는 하지 않는다.

## 구현 후 검토를 위해 남기는 제한

기존 범위 분석기의 작업 표현은 제한적이며 모르는 span을 미확정으로 남긴다. DB release의 text와 현재 runtime 정합성은 Docker Engine을 사용할 수 없어 확인하지 못했다. 원본 pinned asset의 checksums와 chunk/vector/query-cache 정합성은 확인했으며 해당 파일로 Retriever hybrid 검색을 실행했다. 새 임베딩 생성, 적재, cache 보충은 이 단계에 포함하지 않는다.
