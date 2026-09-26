# 작은 RAG 실행 방법 (185~214쪽)

파싱 → 청킹 → 임베딩 → 검색 순서로 실행한다. 모든 명령은 저장소 루트에서 실행한다.
생성물은 `data/processed/`에 쓰이며 커밋하지 않는다(`.gitignore`).

## 1. 환경

- Python 3.11 (3.11.9에서 확인)
- 패키지
  ```bash
  python -m venv .venv
  # Windows: .venv\Scripts\activate   /  macOS·Linux: source .venv/bin/activate
  pip install -r pipeline/requirements.txt          # 파싱: pymupdf
  pip install -r pipeline/requirements-rag.txt      # 임베딩·검색: google-genai, pyarrow, numpy
  ```
- API 키: 저장소 루트의 `.env`에 한 줄로 둔다. `.env`는 커밋 대상이 아니다.
  ```
  GEMINI_API_KEY=발급받은_키
  ```
  환경 변수 `GEMINI_API_KEY`가 있으면 그것을 먼저 쓴다. 코드는 키를 출력하지 않는다.
- BM25 검색과 노무량 환산(`agent/search/rag.py`)은 API 키 없이 동작한다.

> 이 개발 PC에서는 `.venv`의 원래 Python 경로가 없어, 저장소 안의 `.uv-python` Python에
> `PYTHONPATH=.venv-embed;.venv\Lib\site-packages`를 지정해 실행했다. 새 환경에서는 위의 일반 절차를 쓴다.

## 2. 실행 순서

```bash
python pipeline/parse.py --start 185 --end 214   # data/processed/parsed.jsonl (PyMuPDF, 운영 기본)
python pipeline/chunk.py                          # data/processed/chunks.jsonl (절·소제목·표 경계)
python pipeline/embed.py --limit 5 --batch 5      # 먼저 5개로 호출·한도 확인
python pipeline/embed.py                          # 나머지 전부
```

`embed.py`
- 모델 `gemini-embedding-2`, 3072차원. 청크는 `title: {절 제목} | text: {청크}` 형식으로 넣는다.
- 청크마다 입력을 따로 만들어 청크마다 독립된 벡터를 받는다. 벡터 수가 입력 수와 다르면 저장하지 않고 멈춘다.
- 성공한 벡터는 묶음마다 `embeddings.cache.jsonl`에 쌓인다. 중단되면 같은 명령을 다시 실행하면 이어서 한다.
  청크 글자가 바뀌면(해시 불일치) 그 청크만 다시 임베딩한다.
- 호출 한도(429)면 30초·60초 쉬고 다시 시도한다. 그래도 안 되면 멈추고, 성공분은 남긴다.
- 결과: `embeddings.parquet` (청크 ID, 절 번호, PDF·쪽·표 번호·bbox, 입력 해시, 모델, 차원, 벡터)
- 2026-09-25 기록: 159청크, API 18회. 누적 약 95개째에 429가 1회 났다(30초 뒤 계속). 무료 한도 수치는
  공식 문서에 없고 AI Studio에서 확인해야 한다.

## 3. 검색

```bash
python agent/search/rag.py search "레미콘 인력운반 타설 인원"     # BM25 (API 없음)
python agent/search/vector.py "펌프카 작업조 인원"                # 벡터: 질문 임베딩 1회 + 정확한 코사인
python agent/search/hybrid.py "펌프차 타설 현장조건 f2 계수"      # BM25 + 벡터 RRF: 질문 임베딩 1회
python agent/search/rag.py estimate --section 6-1-1 --method "인력운반 타설" --trade 콘크리트공 \
    --column "시공량(㎥) 철근구조물" --volume 100             # 구조 확인한 표에서만 노무량 환산
```

세 검색 모두 `rag.evidence`로 절 단위 근거(선택된 하위 절 전체 + 상위 절 설명, 중복 없음)를 만든다.

## 4. 질문 처리 (`agent/`)

| 폴더 | 역할 | 파일 |
|---|---|---|
| `agent/flow/` | 전체 흐름: 조건 확인 → 검색 → 품량 → 단가 → 답변 | `agent.py`, `quantity_node.py`(품량 단계 얇은 노드) |
| `agent/search/` | 검색 | `rag.py`(BM25·근거 구성), `vector.py`, `hybrid.py` |
| `agent/calc/` | 계산 | `quantity.py`(품량), `unit_price.py`(품량 × 단가), `inputs.py`(입력 검증 보조) |

```bash
python agent/flow/agent.py "철근구조물 150㎥ 레미콘 인력운반 타설 노무비는?" --rates 내_노임단가.json
python agent/flow/agent.py "…" --offline                  # 임베딩 없이 BM25만
python agent/calc/unit_price.py --volume 150 --rates 내_노임단가.json
python agent/calc/unit_price.py --golden                  # 회귀: 골든 100㎥ 사례
python agent/calc/quantity.py --section 6-1-2 --cond 유형=기계비빔타설 --cond 구조물=철근구조물 --quantity 100
```

`--json`을 붙이면 기계가 읽는 JSON(ASCII 이스케이프)을 낸다. 단가 파일 양식은 `evals/labor_rates.template.json`이다.

> 다음 단계 과제: `agent/search/rag.py`에는 검색과 옛 품량 계산(`estimate_labor`)이 함께 있다.
> 에이전트는 이제 `calc/quantity.py`를 쓰고, `estimate_labor`는 기존 회귀 검사(`check_rag`, `check_quantity`)에서만 쓴다.
> 검색 파일에서 떼어 내는 일은 아직 하지 않았다.

## 5. 점검

```bash
python evals/check_parse.py              # 파싱 골든 23건 (pymupdf 필요)
python evals/check_estimate.py           # 6-1-1 노무량 골든 사례
python evals/check_rag.py                # BM25 검색·근거 구성·적산 제한 (API 없음)
python evals/check_unit_price.py         # 노무비 계산 (가상 단가)
python evals/check_agent.py --offline    # 에이전트 흐름 (API 없음)
python evals/check_json_output.py        # --json 출력이 cp949 콘솔에서도 보존되는지 (API 없음)
python evals/check_quantity.py           # 품량 계산기 (API 없음)
python evals/compare_search.py           # BM25·벡터·하이브리드 비교 (질문 수 × 2회 임베딩 호출)
```

q06(강재거푸집 사용횟수)은 원본 파싱에서 193쪽 표가 빠진 문제라 검색 방식과 관계없이 실패한다.
`check_rag`의 알려진 실패는 q06과 n03(BM25 표현 차이) 2건이다.
