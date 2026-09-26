# agent/

건설공사 표준품셈으로 "이 공사의 노무량·노무비는 얼마인가"에 답하는 에이전트 코드다.
세 폴더로 나뉜다.

| 폴더 | 하는 일 | 쉬운 말로 |
|---|---|---|
| `flow/` | 질문 처리 순서와 분기 | 질문을 받아 무엇을 할지 정하고, 검색·계산을 차례로 부른 뒤 답을 만든다 |
| `search/` | 품셈 근거 검색 | 품셈 원문 조각(청크)에서 질문에 맞는 절·표를 찾아 출처와 함께 돌려준다 |
| `calc/` | 품량·금액 계산 | 원문 표 값으로 품량(인·일)을 계산하고, 입력한 노임단가를 곱해 금액을 낸다 |

## 지원 범위

**현재 에이전트가 끝까지 답하는 사례는 하나뿐이다.**
6-1-1 레디믹스트콘크리트 타설 중 **철근구조물 · 인력운반 타설**의 노무량(콘크리트공·보통인부)과 노무비.
사용자가 바꿀 수 있는 값은 물량(㎥)과 노임단가 파일뿐이다.
다른 절·공법·구조물을 물으면 계산하지 않고 `OUT_OF_SCOPE`로 답한다. 조건이 모자라거나 모호하면 `MISSING_INFO`로 되묻는다.

`calc/quantity.py`는 `evals/golden_quantity.json`에 정답을 먼저 적은 사례(6-1-1, 6-1-2 일부)를 명령줄로 계산할 수 있다.
하지만 에이전트는 그중 6-1-1 철근구조물 인력운반 타설만 연결해 두었다.

## 질문 하나가 처리되는 순서

`flow/agent.py`의 `answer()`가 아래 순서로 진행한다.

```
질문
 │
 ├─ route    지원 사례(레미콘 타설)를 묻는가?  아니면 → OUT_OF_SCOPE
 ├─ extract  공법·구조물·물량을 뽑고 검증        빠지거나 모호하면 → MISSING_INFO (검색·계산 안 함)
 ├─ retrieve search/hybrid.py (BM25 + 벡터, RRF). 쓸 수 없으면 search/rag.py의 BM25로 대신하고 경고
 ├─ quantity flow/quantity_node.py → calc/quantity.py   품량 계산. 거부되면 → ERROR
 ├─ price    calc/unit_price.py의 apply_prices          단가 적용 + 계산에 쓴 원문 표가 검색 근거에 있는지 확인
 │                                                       없으면 → ERROR (답하지 않음)
 └─ respond  절·PDF 쪽·표 위치, 단가 기준일·출처를 붙여 답한다 (OK / PARTIAL)
```

## 파일별 역할과 호출 관계

### flow/ — 처리 순서

- **`agent.py`**: 에이전트의 입구. 질문 판정(route), 조건 추출(extract), 검색 인덱스 준비, 품량·단가 단계 호출, 답변 조립(compose)을 한다.
  LLM 없이 규칙으로 판정한다. `--offline`이면 임베딩 API 없이 BM25만 쓴다.
- **`quantity_node.py`**: 품량 단계. **계산을 요청하고 결과를 전달하기만 한다.**
  에이전트가 뽑은 조건(공법·구조물·물량)을 계산기 입력 형태로 옮겨 `calc/quantity.py`의 `compute()`에 넘긴다.
  값을 바꾸거나 추정하거나 직접 계산하지 않는다.

### calc/ — 계산

- **`quantity.py`**: **실제 산식을 수행하는 품량 계산기.** 원문 표를 읽어 조건에 맞는 행을 정확히 하나 고르고
  `품량 = 물량 ÷ 일당 시공량 × 작업조 인원`(6-1-1) 등을 유리수(Fraction)로 정확히 계산한다.
  표 구조가 불확실하거나 조건에 맞는 행이 하나가 아니면 추정하지 않고 거부한다. 금액은 다루지 않는다.
- **`unit_price.py`**: 품량 결과에 노임단가를 곱해 직종별 금액·합계·1㎥당 금액을 낸다(`apply_prices`).
  품량을 다시 계산하지 않는다. 단가는 외부 JSON에서만 읽고, 단가·기준일·출처 중 하나라도 없으면 그 직종은 `미산정`이다.
  금액 처리 규칙은 `AMOUNT_POLICY`에 적는다(아래 "금액 처리 규칙" 참고).
- **`inputs.py`**: 물량 검증(`parse_volume`)과 콘솔 설정. 다른 모듈을 가져오지 않는다.

의존 방향: `inputs ← quantity ← unit_price`. `quantity_node`는 `quantity`와 `unit_price`(사례 정의)를 가져온다.

### search/ — 근거 검색

- **`rag.py`**: 청크 파일 읽기(`load`), BM25 검색(`Index`), 같은 절 단위 근거 묶기(`evidence`), 출처 표기(`citation`).
- **`vector.py`**: 미리 만든 청크 벡터(parquet)와 질문 임베딩(질문마다 API 1회)의 코사인 검색.
- **`hybrid.py`**: BM25와 벡터 검색 순위를 RRF로 합친다. `rag.Index`와 같은 모양이라 `rag.evidence`에 그대로 넣을 수 있다.

### rag.py의 옛 품량 함수

`search/rag.py`의 `estimate_labor()`(와 보조 함수 `one_value()`)는 품량 계산기가 생기기 전에 쓰던 노무량 환산 함수다.
**현재 에이전트 계산 경로에서는 사용하지 않는다.** 에이전트의 품량은 `quantity_node.quantity_step → calc/quantity.compute`에서만 온다.
지금 이 함수를 부르는 곳은 다음뿐이다.

- `python agent/search/rag.py estimate …` 명령줄
- `evals/check_rag.py`: 옛 함수 자체의 회귀 검사
- `evals/check_quantity.py`: 새 계산기 결과가 옛 함수 결과와 같은지 대조
- `evals/check_agent.py`: 에이전트 실행 중 이 함수가 호출되면 실패하도록 막아 두고, 호출되지 않음을 확인

## 금액 처리 규칙

내부 계산은 품량·금액·합계를 모두 유리수로 정확히 보존한다(순환소수도 거부하거나 반올림하지 않는다).
결과의 `amount_policy`에 확정된 것과 남은 것을 나눠 적는다.

**품셈 원문에서 확인한 것** — 2026 건설공사 표준품셈 1-2-2 단위표준('12, '23년 보완) 2. 금액의 단위표준,
`data/raw/standard_estimation/` PDF 62쪽(인쇄 6쪽):

| 종목 | 단위 | 자리 | 비고 |
|---|---|---|---|
| 일위대가표의 계금 | 원 | 1 | 미만버림 |
| 일위대가표의 금액란 | 원 | 0.1 | 미만버림 |

같은 표의 [주]: 일위대가표 금액란 또는 기초계산금액에서 소액이 산출되어 공종이 없어질 우려가 있어
소수자리 1자리 이하의 산출이 불가피할 경우에는 소수자리의 정도를 조정 계산한다.

**아직 정하지 않은 것** (그래서 `applied_amount`는 `{"value": null, "policy": "미정"}`이고 버림도 계산에 적용하지 않는다):

- 단가를 곱하기 전 품량(인·일)에 적용할 소수 자릿수와 그 적용 여부
- 위 [주]의 소액 예외를 언제, 어떻게 적용할지
- 이 결과의 값(직종별 금액, 1㎥당 금액, 합계)을 금액란·계금 중 어디에 대응시킬지

## 실행과 검사

```
python agent/flow/agent.py "철근구조물 150㎥ 레미콘 인력운반 타설 노무비는?" --rates 내_노임단가.json --offline
python agent/calc/quantity.py --section 6-1-1 --cond "공법=인력운반 타설" --cond 구조물=철근구조물 --quantity 100
python agent/calc/unit_price.py --golden
```

API 호출 없는 검사: `evals/check_quantity.py`, `evals/check_unit_price.py`, `evals/check_agent.py --offline`,
`evals/check_json_output.py`.
