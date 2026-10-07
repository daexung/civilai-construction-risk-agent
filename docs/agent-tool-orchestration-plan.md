# 대화 담당 LLM + 서버 도구 구조 설계 (agent-tool-orchestration)

기준: `v0.1.0-beta.1` (`af0b5cd`). 복수 공종 체크포인트 `ad38869`(브랜치 `claude/multi-work-estimate`)의 상태 구조를 재사용한다.
이 문서는 설계만 다룬다. 구현은 아직 시작하지 않았다.

## 0. 원칙

- LLM은 대화와 도구 선택만 맡는다. 품셈 계수·단가·수량·금액은 만들지 않는다.
- 조건 값·계산 결과·금액은 서버 도구가 명세와 공표 자료로 검증하고 계산한다.
- 사용자에게 보이는 숫자는 모두 도구 결과의 특정 필드와 대응해야 한다(§7).
- 상태는 `EstimateSession`(항목 하나)으로 관리한다. 구조는 복수 공종과 같고, 첫 검증 범위만 단일 공종이다.

## 1. 첫 범위의 대화

| 턴 | 사용자 | 기대 동작 |
|---|---|---|
| 1 | 콘크리트 1㎥ 품셈 알려줘 | 공종(타설 방식) 후보를 찾고, 미확정이면 그 선택만 묻는다. 물량 1㎥ 저장 |
| 2 | (타설 방식 선택) | 그 공종의 **품 산출 조건**만 묻는다. 관급/사급·자재 단가는 묻지 않는다 |
| 3 | (조건 답변) | 1㎥당 품과 근거(표·주석 원문)를 설명한다 |
| 4 | 같은 조건으로 100㎥ 비용 계산해줘 | 물량만 100㎥로 바꾼다. 품 결과(작업일수·인일·장비)를 다시 계산하고, **가격 조건**(관급/사급, 사급이면 레미콘 단가)을 묻는다 |
| 5 | (가격 조건 답변) | 일위대가·원가계산서 |
| 6 | 조건 변경 후 재계산 | 바뀐 조건만 반영하고, 영향받는 단계부터 다시 계산한다. 변경 전후 금액은 서버가 계산한다 |

## 2. 노드 흐름

```
START → load_session → agent ⇄ tools → reply → commit → END
                         (한 턴의 LLM 호출·시간 예산 안에서 반복, §6)
```

| 노드 | 담당 | 하는 일 |
|---|---|---|
| `load_session` | 서버 | 마지막으로 확정된 세션을 불러와 작업 사본을 만든다. 화면 버튼 답(`answers`)은 LLM 없이 `apply_answers`로 검증·반영한다 |
| `agent` | LLM | JSON 스키마로 다음 행동 하나를 고른다(§3) |
| `tools` | 서버 | 인자를 검증하고 결정적인 도구를 실행한다. 작업 사본만 바꾼다 |
| `reply` | LLM + 서버 | LLM은 도구 결과로 문장과 대응표를 만든다. 서버가 대응을 검증하고, 실패하면 템플릿 문장을 쓴다(§7) |
| `commit` | 서버 | 작업 사본을 확정 세션으로 저장한다(LangGraph 체크포인터). 실패 처리는 §8 |

질문은 `interrupt`로 멈추지 않고 세션의 `pending_questions`에 데이터로 둔다(체크포인트 `run_item` 방식).

## 3. 행동 선택(JSON 스키마)

`llm/client.generate(response_schema=...)`를 그대로 쓴다. 네이티브 함수 호출은 쓰지 않는다.

```json
{"action": "call_tool" | "reply",
 "tool": "find_work" | "set_conditions" | "compute_labor" | "estimate_cost" | "explain_basis" | "search_standard",
 "args": {},
 "reason": "한 문장"}
```

- 서버는 스키마·도구 이름·인자 형식을 검증한다. 틀리면 그 호출은 실행하지 않고 예산만 소모한다.
- `spec_id`는 세션의 `find_work` 후보에 있는 값만 받는다.
- 모델 입력: 이번 사용자 문장, 세션 요약(공종·조건과 출처·물량·결과 버전·대기 질문), 이번 턴의 도구 결과, 도구 목록.

## 4. 도구

### 공통 반환 형식

```json
{"status": "ok" | "needs_input" | "not_found" | "blocked" | "error",
 "data": {...},
 "missing": [Question],
 "rejected": {"필드": "이유"},
 "revision": {"input": 4, "labor": 4, "price": 3}}
```

`Question = {question_id, version, field, ask, choices: list | null, unit, decision_table, reason, stage: "work" | "labor" | "price" | "common"}`

- `choices`는 목록 또는 `null`이다(PR #22 규칙). 화면 버튼은 서버의 `choices`로만 그린다.
- 공종이 확정되지 않았으면 `missing`에는 `work`만 담는다(PR #23 규칙).
- LLM은 질문 문장을 다듬을 수 있지만 질문 대상과 선택지는 바꿀 수 없다.

### 도구 목록

| 도구 | 입력 | `ok`일 때 `data` | 조건 부족·검증 |
|---|---|---|---|
| `find_work` | `query` | `decision`, 후보 `[{spec_id, section, has_spec}]` | 미확정이면 `needs_input`(`work`만). 명세 없음이면 `not_found` |
| `set_conditions` | `values{필드: {value, evidence}}`, `quantity{value, unit, evidence}?`, `work_choice?` | 반영된 값, 버려진 값(`dropped_conditions`), 무효화된 단계 | ① `evidence`가 이번 사용자 문장에 실제로 있어야 함 ①-2 근거 구절을 서버 파서로 다시 읽은 값·단위가 보낸 값과 같아야 함(㎥·m3·루베, 9만원→90000 같은 표기 정규화는 허용) ② 명세 허용값·단위 검증(`_valid_for_field`, `unit_key`). 선택지 밖 값은 근거 대조보다 먼저 거부하고 가능한 값·명세의 제외 사유(`excluded`)로 안내 ③ 공종이 바뀌면 호환 값만 유지(`choose_work`) ④ 무효화 규칙(§5) |
| `compute_labor` | 없음(세션의 확정 공종·조건) | `unit_lines`(1단위당 품), `daily_volume`, `work_days`, `person_days`, `equipment_days`, `equipment_units`, 근거, `review_status` | 품 산출 조건이 부족하면 `needs_input`(stage=labor), 보류 조건이면 `blocked` |
| `estimate_cost` | `basis_date?` | 일위대가(`priced`), 원가계산서(`statement`), 공통 조건과 출처 | `compute_labor` 결과가 최신이 아니면 먼저 다시 계산한다. 가격 조건이 부족하면 `needs_input`(stage=price) |
| `explain_basis` | `topic?` | 최신 계산 결과에 붙은 표·주석 원문 인용(`resolve_cites`) | 계산 결과가 없으면 `needs_input` |
| `search_standard` | `query` | 원문 자료: 절 `[{section, chunk_id, text, truncated}]` (`build_context`) | 답변 문장은 만들지 않는다. 답은 `reply`가 쓰고, 인용은 서버가 원문과 대조한다(`answer.match_quote`) |

`search_standard`는 도구 안에서 LLM을 부르지 않는다. 기존 `answer` 노드의 답변 작성은 대화 담당 LLM의 `reply`로 옮기고, 인용 검증 로직만 재사용한다.

## 5. 품 조건과 가격 조건 분리, 물량 변경

### 5.1 분류 규칙(명세 데이터 변경 없음)

명세에 이미 있는 정보로 가격 조건을 구분한다.

- **가격 조건** = `spec["supply_rules"][].input` ∪ `when.input`이 가격 조건인 필드
  - 예: 6-1-4의 `concrete_supply`, `ready_mix_price`(`when: concrete_supply = 사급`)
  - 현재 `supply_rules`가 있는 명세: 12개(`concrete_supply`, `material_supply`, `fertilizer_supply`, `wire_mesh_supply`, `wood_supply`)
- **안전 조건**: 후보의 이름이 가격 단계 키(`inputs`·`supply_rules`·`cost_rules`) 밖의 명세 어디에든 나오면(품 계산 `quantity_model`, 할증, 보류 `blocked`, 표 등) 품 조건으로 남긴다. 품 조건의 `when`이 후보를 가리켜도 그 후보는 품 조건이다. 쓰임이 불확실하면 품 조건이다.
- **품 조건** = 나머지 필수 입력(물량 포함)
- **공통 조건**(공사 종류·기간·업종·규모)은 원가계산서 단계에서만 쓴다. 기본값과 출처를 세션에 저장한다(`aggregate.resolve_common`).

### 5.2 최소 코드 변경과 영향 범위

| 변경 | 위치 | 내용 |
|---|---|---|
| 분류 함수 | 새 독립 모듈 `backend/agent/rules/conditions.py` | `price_fields(spec) -> frozenset[str]`. `specs.py`가 계산기를 가져오므로, 순환 참조를 피하려고 `specs.py`·계산기를 가져오지 않는 모듈에 둔다 |
| 계산기 품 산출 모드 | `tools/calc/daily_crew.adjusted_daily_crew`, `tools/calc/per_unit.per_unit` | 키워드 인자 `labor_only=False` 추가. **True일 때만** 필수 누락 검사에서 가격 조건을 뺀다. 기본값의 검증은 그대로다 |
| 가격 전 검사 | 새 `estimate_cost` 도구 | `price_unit` 호출 전에 가격 조건 누락을 `needs_input`(stage=price)으로 돌려준다 |

영향:
- **기존 그래프**: `compute` 노드는 `labor_only`를 넘기지 않으므로 계산기 동작이 같다. `fill`도 그대로 필수 입력 전체를 묻는다.
- **명세 JSON·요율·계산식·버림·반올림**: 변경 없음.

### 5.3 물량 변경 시 갱신 범위

물량은 **품 조건**이다. 1단위당 품(`unit_lines`)은 물량과 무관하지만, 아래 값은 물량에 비례한다.

- `adjusted_daily_crew`: `work_days`(= 물량 ÷ 일당 시공량), `person_days`, `equipment_days`, `equipment_units`
- `price_unit`의 참조 금액(`_reference_amounts`: 총액 × 물량)
- 원가계산서 전체

규칙(체크포인트 `_bump` 확장):

| 바뀐 것 | 다시 할 단계 |
|---|---|
| 공종 | 조건 재구성(`choose_work`) → 품 → 가격 → 원가계산서 |
| 물량·품 조건 | 품 → 가격 → 원가계산서 |
| 가격 조건 | 가격 → 원가계산서 (품 결과 유지) |
| 공통 조건 | 원가계산서만 (`set_common`) |
| 기준일 | 가격 → 원가계산서 |

품 결과가 최신인지는 **품 입력 키**(`labor_key` = 명세 id + 품 조건 + 물량의 해시)로 판정한다. 키가 같으면 품을 다시 계산하지 않는다. 그래서 가격 조건·공통 조건만 바뀌면 품은 그대로 두고 가격·원가만 다시 만든다. 이를 위해 체크포인트 `_bump`는 품 결과를 지우지 않고 가격 결과만 지우도록 바꾼다. 가격 결과는 **가격 키**(`price_key` = 품 키 + 가격 조건 + 기준일)와 `result_revision == input_revision`으로 판정해 재사용한다. 원가계산서는 **원가계산서 키**(`statement_key` = 기준일 + 공통 조건 + 항목별 입력·결과 버전·품 키·가격 키)가 현재 상태와 같을 때만 최신이다. `set_conditions`로 무엇이든 반영되면 이전 원가계산서를 지우고, 도구를 거치지 않은 변경(예: `set_common`, 기준일)도 키 불일치로 최신이 아니게 된다. 결과를 보여주거나 내려받을 때는 `current_estimate(session)`이 돌려주는 최신 결과만 쓴다.

## 6. 호출 예산

한 사용자 턴의 예산 하나에 아래를 모두 포함한다.

- `agent` 호출(재시도 포함)
- `reply` 호출(재시도 포함)
- 도구 내부의 LLM 호출(첫 PR에는 없음. 생기면 같은 예산에서 차감)

| 항목 | 첫 값 | 비고 |
|---|---|---|
| LLM 요청 시도 수 | 턴당 6회 | `LLMResult.attempts`·`LLMUnavailable.attempts`를 그대로 차감 |
| 도구 실행 | 턴당 4회 | 결정적 도구. LLM 시도와 별도로 셈 |
| 시간 | 턴당 25초 | 각 LLM 호출의 `timeout_ms`는 남은 시간으로 줄인다 |

예산이 소진되면 더 부르지 않는다. 이미 확정된 도구 결과로 템플릿 응답을 만든다. 예산 사용량은 응답의 `llm_info`에 기록한다(시도 수, 소요 시간, 소진 여부).

## 7. 응답 문장 검증

`reply`는 문장(`{"text": "..."}`)만 낸다. LLM이 쓴 대응표는 검증에 쓸 수 없어(스스로 맞다고 적을 수 있다) 받지 않는다.

서버 검증(`estimate/reply_check.py`). 서버가 이번 턴 도구 결과로 사실 목록(`facts`: 항목·값·단위·총액/단위당 구분)을 만들고, 문장 속 숫자마다 아래를 모두 만족하는 사실이 있어야 통과한다.
1. 값이 같다(천 단위 쉼표 무시, `9만원`처럼 만·억 단위는 환산한 값이 같을 때만). 표기는 `tools/calc/format.py` 규칙.
2. 숫자 바로 뒤가 그 사실의 단위로 시작한다.
3. 같은 문장에서 숫자 앞에 가장 가까운 항목명이 그 사실의 항목이다(물량·단가처럼 생략 가능한 항목은 없어도 됨).
4. 총액을 '단가·㎥당'으로, 단위당 값을 '총·합계'로 설명하지 않는다. 공종 번호·조건 값 같은 서버 문자열과, 근거 설명 턴의 원문 인용 속 숫자는 허용한다.
5. 이번 턴에 서버가 거부한 요청 값(`set_conditions`의 `refused`, 예: 25m)은 같은 문장이 '지원하지 않음·유지'로 설명하고 바로 뒤에 '…로 계산/변경'이 붙지 않을 때만 허용한다. 전역 허용 목록에는 넣지 않는다.
6. 사실값은 기존 표시 규칙으로 보여 준다: 끝나는 소수는 그대로(천 단위 쉼표), 순환소수는 반복 구간 괄호(작업일수 30/13 → 2.(307692)). 내부 값과 검증은 정확값(분수)으로 한다.
7. 하나라도 실패하면 LLM 문장을 버리고 템플릿 문장을 쓴다. 실패 이유는 `llm_info.rejected`에 남긴다.

인용(`search_standard`, `explain_basis`)은 원문 대조(`match_quote`)를 통과한 것만 보여준다.

## 8. 실패 처리와 복구

작업 사본 방식으로 처리한다. 각 턴은 확정 세션(`committed`)을 복사한 `working`에서만 진행하고, `commit`에서 한 번에 저장한다.

| 실패 시점 | 처리 |
|---|---|
| 상태 변경 전 (첫 `agent` 호출 실패, 행동 형식 오류 반복, 예산 소진) | `working`을 버린다. 새 흐름 안의 규칙 대체 정책으로 처리한다: 규칙 라우터(`route.py`) + 결정적 도구 순서(find_work → set_conditions(규칙 추출) → compute_labor/estimate_cost) |
| 상태 변경 후 · 도구는 성공, `reply` 실패 | 도구 결과는 유효하므로 `working`을 확정하고 템플릿 응답을 보낸다 |
| 상태 변경 후 · 도구 실행 중 예외 | `working`을 버리고 `committed`(직전 조건·결과)를 유지한다. 응답은 `status: ERROR`와 "저장된 조건은 유지됩니다. 다시 시도해 주세요." 안내 |
| `commit` 저장 실패 | 응답을 보내지 않고 오류로 끝낸다. 회원은 기존처럼 체크포인트와 대화 기록이 한 트랜잭션이라 함께 롤백된다 |

- 조회·설명 질문(변경 표현 없이 '몇·얼마·알려줘·?')은 저장된 조건을 바꾸지 않는다. 숫자·단위가 있어도 같다('1㎥당'은 단위당 기준). 규칙 경로는 지금 견적의 품 항목을 물으면 `compute_labor`만 부르고, LLM이 `set_conditions`를 불러도 서버가 적용하지 않는다(이번 턴에 시작한 견적의 첫 문장은 예외).
- 기존 그래프(`build_graph`)로 자동 전환하지 않는다. 새 흐름 세션이 있는 대화는 계속 새 흐름에서만 처리한다.
- 기존 그래프는 기능 설정(`AGENT_MODE`)이 off이거나 새 흐름 세션이 없는 대화에만 쓴다.
- 재시도는 클라이언트가 같은 `request_id`로 보낸다. 회원은 기존 중복 감지(`messages.request_id`)로 같은 결과를 돌려준다. 비회원은 `비회원 세션 + request_id` 기준으로 같은 방식으로 처리한다(§13).
- 자동 재요청은 하지 않는다. 사용량 차감은 기존 규칙(요청당 1회)을 유지한다.
- `AGENT_MODE=tools`는 요청별 차감 기록(`agent_state.chat_request_charges`, 마이그레이션 `20261008000100`)으로 재시작·다른 인스턴스에서 같은 `request_id`를 다시 보내도 한 번만 차감한다. 기존 모드는 이 테이블을 쓰지 않아 마이그레이션 전 DB에서도 동작한다.
- `AGENT_MODE=tools`에서 이 테이블이 없으면 서비스 준비가 실패한다: `/api/ready`·채팅 503(운영은 시작 실패). 검사: `evals/check_request_charges_compat.py`.

## 9. 저장·조회·Excel

- 세션은 대화 thread의 LangGraph 체크포인터에 저장한다(비회원 MemorySaver, 회원 PostgresSaver). 기존 thread와 같은 키를 쓰고, 새 흐름인지는 세션의 존재로 구분한다(체크포인트 `estimate_service.latest_flow` 참고).
- 응답은 기존 `ChatResponse` 형식(`status`, `questions`, `inputs`, `result`, `priced`, `statement`, `answer`, `evidence`)으로 변환한다. 화면은 바꾸지 않는다.
- Excel은 기존 `build_xlsx(response)`와 `tables.py`를 그대로 쓴다. `/api/export/{thread_id}.xlsx`가 새 흐름 세션이면 **최신 확정 결과**(`price_revision == input_revision`)로 응답을 만들어 넘긴다. 결과가 낡았거나 질문이 남아 있으면 기존처럼 404다.

## 10. 재사용

### main (`af0b5cd`)

| 용도 | 코드 |
|---|---|
| 공종 찾기 | `nodes/retrieve.py`, `nodes/select.py` |
| 조건 추출·검증 | `nodes/fill.py`: `extract_inputs`, `_valid_for_field`, `_compatible_inputs`, `_common_fields`, `_format_rational` |
| 품 | `nodes/gate.py`, `nodes/compute.py`, `tools/calc/daily_crew.py`, `per_unit.py`, `adjustments.py` |
| 가격·원가 | `tools/calc/price.py`, `cost_statement.py` |
| 근거 | `tools/source/citation.py`, `nodes/qa_context.py`, `nodes/answer.py`의 `validate`·`match_quote` |
| 숫자 검증 | `nodes/compose.py`의 숫자 거부 로직(§7로 확장) |
| LLM·대체 | `tools/llm/client.py`, `nodes/route.py` |
| API·저장 | `api/main.py`(사용량, 회원 저장, 내보내기), `api/tables.py`, `api/chat_storage.py` |

### 체크포인트 `ad38869`

| 가져올 것 | 쓰임 |
|---|---|
| `estimate/state.py` 전체 | `EstimateSession`(항목 하나), `EstimateItem`, `Question`, `choose_work`, `set_quantity`, `set_explicit`, `set_common`, `_bump`, `unit_key`, `question_version` |
| `estimate/flow.py`의 `run_item`, `_build_conditions`, `_normalize_answer`, `apply_answers`, `run_items`, `session_complete` | 도구 내부 실행. `run_item`은 품 단계와 가격 단계로 나눈다 |
| `estimate/aggregate.py` | 원가계산서(`resolve_common`, `aggregate`). 항목 하나에서 기존 `statement`와 같은 합계인지 검증 |
| `api/estimate_service.py`의 `snapshot`, `latest_flow`, `_question_out`, `response` | 저장·응답 변환. 공종 수정·공통 조건 변경 함수는 첫 PR에서 쓰지 않는다 |
| `evals/check_estimate_items.py`, `check_estimate_aggregate.py`의 단일 공종 사례 | 단위 검사 출발점 |

가져오지 않을 것: `build_estimate_graph`(부모 그래프. 새 그래프로 대체), `rules/intent.py`(main의 `route.py`가 대체), `estimate_output.py`와 프론트 변경(화면 범위 밖), baseline 픽스처(9a2af9f 기준이라 그대로 쓰지 않음).

체크포인트 코드는 main의 `fill`·`compute` 등을 수정 없이 감싸는 구조라 `af0b5cd`(PR #23 반영)와 함께 쓸 수 있다. 다만 #23에서 바뀐 `fill`(공종 미확정 시 공종만 질문)과의 중복 처리는 PR에서 확인한다.

## 11. 검증 계획

### 11.1 단위 검사 (CI, 오프라인)

고정 후보와 대본 LLM은 여기서만 쓴다.

- 도구별: 반환 형식, `choices`는 목록 또는 null, 허용값 밖 거부, 원문에 없는 `evidence` 거부, 공종 변경 시 호환 값만 유지
- 조건 분리: 6-1-4에서 품 단계 질문에 `concrete_supply`·`ready_mix_price`가 없고, 가격 단계에서만 나오는지
- 물량 변경: 1㎥ → 100㎥에서 `unit_lines`는 같고 `work_days`·`person_days`·`equipment_days`·참조 금액은 100배인지
- 금액 일치: 같은 입력의 기존 그래프 결과와 일치하는지(260㎥ 도급액 10,032,436원 포함)
- 대본 LLM으로 §1 대화 6턴: 도구 호출 순서, 턴별 질문, 결과 버전
- 엉뚱한 LLM: 근거 없는 조건, 문장 속 지어낸 금액, 숫자-항목·단위 불일치, 후보 밖 `spec_id`, 예산 초과
- 실패 복구: 도구 예외 시 `committed` 유지, `reply` 실패 시 확정 + 템플릿, 기존 그래프로 전환하지 않음
- 저장·Excel: 비회원·회원(로컬 PostgreSQL) 각각 재계산 후 내려받은 Excel의 합계가 최신 결과와 같은지, 낡은 결과는 404인지
- 설정 off: 기존 검사 결과가 그대로인지

### 11.2 실제 검색 대화 검사 (로컬, 유료 호출 없음)

- 실제 검색 색인(오프라인 BM25/하이브리드)과 새 흐름의 **규칙 대체 정책**으로 §1 대화와 변형 10개를 끝까지 돌린다. 문서·검사 시나리오는 `evals/agent_conversations.json`에 둔다.
- 확인: 공종 후보에 기대 공종이 있는지, 질문 단계(work → labor → price), 최종 금액이 같은 입력의 기존 그래프와 같은지.
- 현재 알려진 한계: 오프라인 검색에서 "콘크리트 타설 1㎥" 후보에 6-1-1이 빠질 수 있다. 실패는 숨기지 않고 검색 문제로 기록한다.

### 11.3 소량 실제 LLM 평가 (수동, 지금 실행하지 않음)

- 모델: 현재 운영 모델(`llm/config.json`). 첫 평가는 약 10턴(§1 대화 1회 + 변형 몇 턴)으로 한다.
- 실행 전 예상 호출 수와 비용을 보고하고 확인받는다. 확인 전에는 실행하지 않는다.
- 실행: `AGENT_LLM=on`, `AGENT_MODE=tools`, 로컬 키, 운영 DB·운영 API 미사용.
- 측정: 도구 선택 정확도, 턴별 LLM 시도 수, 예산 소진 비율, 응답 문장 검증 실패율, 템플릿 대체율, 최종 금액 일치 여부.
- 결과 파일만 `evals/results/`에 남긴다. CI에는 넣지 않는다.

## 12. 구현 순서: 두 PR

PR 1은 계산 도구가 준비됐는지, PR 2는 LLM이 그 도구로 대화를 제대로 진행하는지 확인한다.

### PR 1 — 검증 가능한 서버 도구

1. `EstimateSession` 재사용: 체크포인트 `estimate/state.py`(`_bump`만 §5.3대로 수정), `estimate/aggregate.py`
2. 품 조건/가격 조건 분리(§5.1~5.2): `rules/conditions.py`, 계산기 `labor_only` 모드
3. 서버 도구(§4): `estimate/tools.py`의 `new_estimate`, `find_work`, `set_conditions`, `compute_labor`, `estimate_cost`, `explain_basis`, `search_standard`
4. 물량·조건 변경 시 결과 갱신(§5.3)
5. 검사: `evals/check_estimate_tools.py`(`run_quick` 포함). 기존 검사 결과가 그대로인지 확인

실행 경로(API·그래프)에는 연결하지 않는다. 운영 동작 변화는 없다.

### PR 2 — 대화 담당 LLM 연결

1. 설정 `AGENT_MODE=tools`(기본 off)와 새 그래프(load_session → agent ⇄ tools → reply → commit)
2. JSON 행동 스키마(§3), 호출 예산(§6), 응답 문장 대응 검증(§7), 실패 복구(§8)
3. 저장·조회·API·Excel 연결(§9), 비회원 중복 요청 처리(§13)
4. 검사: §11.1의 남은 항목, §11.2 실제 검색 대화 검사, §11.3 평가 스크립트(실행은 비용 확인 후)

제외(두 PR 모두): 여러 공종 계획·합산 화면, 공종별 수정 API, 프론트 변경, 검색 개선.

## 13. 결정 사항

- **비회원 중복 요청**: `비회원 세션 + request_id` 기준으로 처리한다. 같은 요청을 다시 보내면 재실행·재차감하지 않고 저장된 결과를 돌려준다. 같은 ID로 다른 내용이 오면 거부한다.
- **숫자 표기**: 기존 `tools/calc/format.py` 규칙을 유지한다. 화면·설명·Excel의 표기가 어긋나지 않도록 응답 문장 검증(§7)도 같은 규칙으로 정규화한다.
- **실제 LLM 평가**: 현재 운영 모델로 첫 10턴을 계획한다. 예상 비용을 확인하기 전에는 실행하지 않는다(§11.3).
