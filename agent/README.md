# agent/

표준품셈의 6-1-1 철근구조물 인력운반 타설 노무량·노무비 질문을 처리한다. 계산은 코드가 수행하며 현재 LLM은 사용하지 않는다.

## 폴더별 역할

| 경로 | 역할 |
|---|---|
| `graph.py` | 질문 처리 순서와 분기만 담당 |
| `state.py` | 응답 기본 형태와 지원 범위 |
| `nodes/` | 질문 판정(`route`), 조건 추출(`extract`), 검색 준비(`retrieve`), 품량 전달(`quantity`), 단가 결과와 근거 확인(`price`), 답변 조립(`respond`) |
| `tools/search/` | BM25, 벡터, 하이브리드 검색과 근거 구성 |
| `tools/calc/` | 품량·노무비 계산, 입력 검증, 출력 형식; `legacy_labor.py`는 회귀 검사 전용 |
| `rules/` | 6-1-1·6-1-2 명세와 지원 사례 데이터 |
| `../shared/` | 배치와 에이전트가 공유하는 임베딩 모델·입력·해시 함수 |

노드는 판단하고 도구에 전달한다. 계산 도구는 응답 상태를 알지 못한다.

## 지원 범위

에이전트는 6-1-1 레디믹스트콘크리트 타설 중 철근구조물·인력운반 타설 한 사례만 답한다. 물량과 노임단가만 입력으로 바꿀 수 있다. 다른 공종·공법은 `OUT_OF_SCOPE`, 조건 누락·모호함은 `MISSING_INFO`로 처리한다. 별도 품량 CLI는 골든셋에 등록된 6-1-1·6-1-2 일부 사례도 계산한다.

## 질문 하나의 처리 순서

`python -m agent` → `graph.answer` → `nodes.route` → `nodes.extract` → `nodes.retrieve` → `nodes.quantity` → `nodes.price` → `nodes.respond` 순서다. 범위 밖이거나 조건이 부족하면 검색·계산 전에 멈춘다. 품량 계산기가 거부하거나 계산에 쓴 원문 표가 검색 근거에 없으면 `ERROR`로 답한다. 검색은 하이브리드를 우선 시도하고 실패하면 BM25로 대체한다. `--offline`은 BM25만 사용한다.

`legacy_labor.estimate_labor`는 과거 계산과 비교하는 검사에만 사용하며 에이전트 경로에서는 호출하지 않는다.

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

저장소 루트에서 실행한다.

```bash
python -m agent "철근구조물 150㎥ 레미콘 인력운반 타설 노무비는?" --rates 내_노임단가.json --offline --json
python -m agent.tools.calc.quantity --section 6-1-1 --cond "공법=인력운반 타설" --cond 구조물=철근구조물 --quantity 100 --json
python -m agent.tools.calc.unit_price --golden --json
python evals/check_agent.py --offline
python evals/check_quantity.py
python evals/check_unit_price.py
python evals/check_json_output.py
```

단가 파일 형식은 `evals/labor_rates.template.json`을 참고한다.
