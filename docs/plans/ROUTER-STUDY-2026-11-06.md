# 채팅 질의 라우터 개선 사전 조사

**범위:** 현재 저장소 코드와 지정된 참고 자료를 읽었습니다. 파일은 만들거나 고치지 않았고, git 상태를 바꾸는 명령도 실행하지 않았습니다. `evals/check_router.py`는 `AGENT_OFFLINE=1`, `AGENT_LLM=off`로 실행을 시도했지만, 환경에 `langgraph`가 없어 시작 단계에서 멈췄습니다. 따라서 아래 “통과 여부”는 실행 결과와 기존 코드·기록을 구분해 적었습니다.

## 1. 질문이 경로를 정하기까지의 판단 지점

요청에 적힌 “경로”는 두 층으로 나뉩니다. API가 **대화형 Dialogue와 기존 그래프 중 어느 쪽을 탈지** 먼저 고르고, 대화형 경로 안에서는 다시 **견적·상담·조회·변경·새 견적 여부**를 결정합니다. 기존 그래프 경로의 `_rule_route`와 LLM 라우터는 이 두 번째 판단과 완전히 같은 체계가 아닙니다.

| 파일:줄 | 판단 내용·방법 | 입력 → 출력 | 틀렸을 때 |
|---|---|---|---|
| [backend/api/main.py:556](backend/api/main.py:556)–572 | `_uses_dialogue`: 저장된 Dialogue checkpoint가 있으면 Dialogue를 계속 사용. legacy checkpoint가 있으면 `_rule_route`와 “새 견적” 정규식을 적용하고, 아니면 Dialogue 활성화 설정을 봄. | checkpoint, 요청 문장 → Dialogue 여부 | 기존 대화를 잘못된 런타임에서 이어 가거나, 견적 요청이 legacy 그래프로 감 |
| [backend/agent/nodes/route.py:47](backend/agent/nodes/route.py:47)–65 | `_rule_route`: 범위 밖 단어, 이전 견적 재계산, 금액·품셈·공종·방법·요청 단서·수량을 정규식으로 순서 판정 | 질문, 이전 route → `estimate` / `qa` / `out_of_scope` | 규칙이 질문의 의도·대상·대화 문맥을 놓쳐 잘못된 route를 반환 |
| [backend/agent/nodes/route.py:74](backend/agent/nodes/route.py:74)–110 | 기존 그래프 LLM 라우터: 규칙 결과를 fallback으로 준비. `out_of_scope`면 LLM 호출 없이 반환하며, 그 외에는 `AGENT_LLM=on`일 때 구조화 route 호출. confidence가 0.6 미만이면 `qa`. | query, previous context → route, confidence, 검색어 | 잘못된 fallback 또는 낮은 confidence 정책이 route를 바꿈. Dialogue의 주 라우팅 경로와 별도 |
| [backend/agent/estimate/dialogue.py:84](backend/agent/estimate/dialogue.py:84)–108 | `_lookup_only` / `_is_lookup`: 조회어가 있고 변경어가 없으면 조회. `_answers_pending`은 `_rule_changes`가 대기 중 질문·기본값 필드에 해당하는 조건을 추출하는지 검사해 “조회”로 분류하지 않게 함 | 메시지, 세션, pending → 조회 여부·대기 답변 여부 | “몇 명?” 같은 설명 요청을 변경으로 보거나, 값 답변을 조회로 취급해 pending에 반영하지 않을 수 있음 |
| [backend/agent/estimate/dialogue.py:149](backend/agent/estimate/dialogue.py:149)–160 | `_cost_target`: 현재 공종·값 어휘와 검색 인덱스 공종 어휘를 비교. 다른 공종 단어가 있으면 새 견적 또는 현재 공종과 함께 언급된 경우 모호로 분류 | session의 제목·조건·라인명과 메시지 → `current` / `new` / `ambiguous` | 현재 조건을 새 공종에 적용하거나, 새 공종 요청을 현재 견적에 섞을 수 있음 |
| [backend/agent/estimate/dialogue.py:163](backend/agent/estimate/dialogue.py:163)–169 | `_confirm_scope`: 대상이 모호하면 상태 변경 전에 “현재 견적/새 견적” 선택 질문을 만듦 | session, 메시지 → `needs_input` 선택 카드 | 앞 단계가 모호함을 놓치면 확인 기회 없이 잘못된 견적 대상 선택 |
| [backend/agent/estimate/dialogue.py:491](backend/agent/estimate/dialogue.py:491)–534 | `_rule_actions`: `_rule_route`를 다시 호출하고, pending 답변·대상·근거 조회·현재 값 변경·QA 검색 등을 순서대로 판정 | 상태, 메시지, 답변 여부 → tool action 목록 | API/라우터와 다른 규칙이 최종 실행 도구를 선택할 수 있음 |
| [backend/agent/estimate/dialogue.py:537](backend/agent/estimate/dialogue.py:537)–544 | `_start_actions`: 새 세션에서 작업 찾기 → 정규식 물량 추출 → route에 맞춰 비용 또는 품 계산 | 메시지, route → `find_work`, 선택적 `set_conditions`, 계산 tool | 물량이 조건값이거나 여러 값인데 단일 물량으로 오인될 수 있음 |
| [backend/agent/estimate/dialogue.py:758](backend/agent/estimate/dialogue.py:758)–892 | `run_turn` 초반: 범위 카드 답을 검증·확정하고, 다중 작업을 합산 처리. 세션이 없거나 명시적 새 견적일 때 `_rule_route == estimate`면 `scope.analyze_request`로 먼저 분기 | 기존 상태, 메시지, 답·참조 → 카드 응답, 다중 견적 세션, scope 분기 | `scope` 진입 조건이 route 정규식과 다중 작업 규칙의 영향을 받아 단일·복수 경로가 달라짐 |
| [backend/agent/estimate/dialogue.py:893](backend/agent/estimate/dialogue.py:893)–945 | `run_turn` 후반: 카드 답은 LLM 금지, 조건 payload는 규칙 처리, QA 지식 경로를 우선 검토하고 나머지는 LLM agent loop 또는 `_rule_actions` 선택 | 메시지·답·조건·세션 → 실제 tool 호출·응답 정책 | 같은 문장이 LLM on/off, knowledge 활성화, 세션 상태에 따라 다른 도구 경로를 탈 수 있음 |
| [backend/agent/estimate/scope.py:94](backend/agent/estimate/scope.py:94)–155, [347](backend/agent/estimate/scope.py:347)–353 | `analyze_request`: 구절 분리, 작업명 사전·정규식, 제외·대안·질문 표현 규칙으로 작업/바탕/조건/미확정 구절 분석. 계산 계획 자체는 만들지 않음 | 원문 → 작업 항목·구절·조건·미확정 항목·확인 질문 | 작업명 사전에 없는 표현이나 부정·대안 문맥을 잘못 나누면 누락·과잉 포함·불필요한 확인 발생 |
| [backend/agent/tools/llm/prompts/router.md:1](backend/agent/tools/llm/prompts/router.md:1)–28 | route LLM 지침: 견적/품셈상담/범위 밖 구분, 이전 대화와 재계산, 수량만 있는 경우, 경계 예시를 제공 | 이전 대화와 질문 → LLM route·근거·검색어 | 예시·규칙의 해석이 `route.py` 정규식과 다를 수 있음 |
| [backend/agent/tools/llm/prompts/agent.md:1](backend/agent/tools/llm/prompts/agent.md:1)–31 | Dialogue agent 지침: 여러 tool 중 하나 선택, `evidence`를 붙인 조건값·물량, pending 답변과 조회/변경 판단을 언어로 지시 | 현재 상태·사용자 문장 → action/tool/args 또는 reply | LLM이 규칙 경로와 다른 tool을 선택하거나, 의미상 근거가 충분치 않은 값을 제안할 수 있음 |

`_rule_changes`는 표에 따로 넣지 않았지만 중요한 중간 판단입니다. `_answers_pending`, `_rule_actions`와 tool 실행 경로에서 조건·물량 변경 후보를 뽑고, Dialogue 코드가 그 결과를 이용합니다. 해당 함수는 [dialogue.py:약 300–370](backend/agent/estimate/dialogue.py:300) 부근에 있습니다. LLM 경로에는 별도로 tool 인자·근거를 검증하는 `_values_arg`와 실행기가 있습니다([dialogue.py:471–488](backend/agent/estimate/dialogue.py:471)).

## 2. 중복·모순 가능 지점

- **API 경로 선택과 대화 내부 라우팅이 서로 다른 횟수로 판단합니다.** `_uses_dialogue`는 legacy 대화에서 `_rule_route`와 별도 `explicit_new` 정규식을 적용합니다([main.py:565–570](backend/api/main.py:565)). 이후 Dialogue에 들어가도 `run_turn` 초반의 새 견적 정규식과 `_rule_route`를 다시 봅니다([dialogue.py:860–865](backend/agent/estimate/dialogue.py:860)). 예를 들어 **“새로 페인트 견적”**은 `explicit_new` 정규식의 표기 범위와 작업명 인식, route 결과가 모두 맞아야 원하는 새 Dialogue 흐름으로 갈 수 있습니다.

- **Dialogue의 LLM agent와 규칙 경로가 같은 문장에 다른 결정을 내릴 수 있습니다.** `run_turn`은 LLM 사용 설정에 따라 `_agent_loop` 또는 `_rule_actions`를 선택합니다([dialogue.py:934–944](backend/agent/estimate/dialogue.py:934)). `agent.md`는 pending 질문이 있어도 새 값·요청을 처리하라고 하지만([agent.md:28](backend/agent/tools/llm/prompts/agent.md:28)), 규칙 경로는 `_answers_pending`과 `_is_lookup` 정규식 판정에 의존합니다. **“높이를 6m로 정정해줘”** 같은 말은 LLM이 명세 조건 변경으로 알아차려도 규칙 경로가 필드명·변경 표현을 추출하지 못하면 대기 질문 답으로 처리되지 않을 수 있습니다.

- **조회와 pending 답변이 어휘·상태 규칙에 중첩됩니다.** `_lookup_only`는 “몇/얼마/어떻게/알려/?”처럼 넓은 조회 단서를 찾고 변경 단서가 없으면 조회로 봅니다([dialogue.py:81–86](backend/agent/estimate/dialogue.py:81)). `_answers_pending`이 별도로 값을 추출해 예외 처리합니다([dialogue.py:89–108](backend/agent/estimate/dialogue.py:89)). **“물량 30m면 몇 명이야?”**는 조회형 문장인 동시에 물량 변경/답변일 수 있어, pending 필드와 추출된 단위에 따라 분류가 바뀝니다.

- **경로 라우터의 ‘범위 밖’과 진행 중 견적의 상태 변경이 다르게 해석됩니다.** `_rule_route`는 `OUTSIDE` 단서가 먼저면 `out_of_scope`로 반환합니다([route.py:47–50](backend/agent/nodes/route.py:47)). `_rule_actions`는 그 결과만으로 끝내지 않고 pending 답변인지 확인하여 예외를 둡니다([dialogue.py:504–506](backend/agent/estimate/dialogue.py:504)). 따라서 **“현재 공종은 그대로 두고 자동문 3개소도 계산해줘”**처럼 범위 밖 표현과 새 견적 요청이 함께 있는 문장은 API 선택, route, 대상 판정 결과가 갈라질 수 있습니다.

- **현재 견적/새 견적 판정이 `_cost_target`과 `_rule_actions`의 route로 나뉩니다.** `_cost_target`은 작업 어휘집과 현재 견적의 어휘를 비교([dialogue.py:149–160](backend/agent/estimate/dialogue.py:149)); `_rule_actions`는 이 결과와 route를 조합해 새 세션·확인 질문·현재 견적 변경을 결정합니다([dialogue.py:511–534](backend/agent/estimate/dialogue.py:511)). 예를 들어 현재가 콘크리트 견적일 때 **“철근도 2톤, 콘크리트는 그대로 두고 비용 알려줘”**는 새 작업과 기존 작업을 한꺼번에 말합니다. `_cost_target`의 단어 포함 방식이 “새 견적”만 선택하거나 모호로 처리할 수 있지만, agent LLM은 다중 작업으로 해석할 수도 있습니다.

- **`scope.analyze_request`는 전체 의도 라우터가 아닙니다.** `run_turn`에서 `_rule_route == estimate`일 때만 호출되고([dialogue.py:860–865](backend/agent/estimate/dialogue.py:860)), 그 안에서는 작업 표현 사전·구절 패턴으로 범위를 분석합니다([scope.py:94–155](backend/agent/estimate/scope.py:94)). **“콘크리트 타설 100㎥ 비용”**의 route와 **“콘크리트 타설 100㎥, 철근은 제외”**의 작업·제외 구절 분석은 각기 다른 규칙 체계입니다.

## 3. 라우팅 평가·검사

- **`evals/check_router.py`**는 외부 호출 없는 라우터 회귀검사로 설명되어 있습니다([check_router.py:1](evals/check_router.py:1)). `AGENT_LLM=off`에서 LLM 미호출, 규칙 route 사례 13개, `router_testset.jsonl` 정확도 기준(90% 이상)을 검사합니다([check_router.py:208–238](evals/check_router.py:208)). 파일에 직접 열거된 route 회귀 예는 13개이고, 별도 테스트셋은 `eval_router.py`가 46문항 및 ID 고유성을 검사하도록 되어 있습니다([eval_router.py:86–93](evals/eval_router.py:86)).

- **`evals/eval_router.py`**는 규칙 또는 LLM 모드의 46문항 평가 도구입니다. 기준은 전체 정확도 ≥90%, 경계 정확도 ≥80%, 견적을 범위 밖으로 오분류 0건, 평균 지연 ≤1500ms입니다([eval_router.py:22–25](evals/eval_router.py:22)). 파일을 실행하면 `evals/results/router_<날짜>.json`에 기록하므로 이번 조사에서는 실행하지 않았습니다([eval_router.py:99–105](evals/eval_router.py:99)).

- **실행 결과:** `check_router.py`는 `ModuleNotFoundError: No module named 'langgraph'`로 테스트 시작 전에 중단됐습니다. 따라서 현재 통과 여부는 **확인 불가**입니다. 기록된 과거 결과 파일은 `evals/results/router_2026-10-03.json`, `router_2026-10-04.json`, `router_2026-10-05.json`이 있지만, 이번 응답에서는 그 내용을 대조하지 않았으므로 현재 코드 통과 근거로 보지 않습니다.

- `AGENT_OFFLINE=1`은 `check_router.py`의 보이는 검사 코드에서 직접 참조되지 않습니다. 이번 실행은 해당 환경변수도 설정했지만, 외부 호출 여부를 보장하는 코드는 `AGENT_LLM=off`와 LLM 호출을 실패시키는 mock에 있습니다([check_router.py:208–238](evals/check_router.py:208)).

## 4. 핫픽스 diff 영향

지정된 `hotfix_backend.diff`는 **라우터 통합 작업은 아닙니다.** 아래 관련 지점은 변경하지만, 판단 체계를 하나로 모으거나 `route.py`의 경로 선택을 구조화 출력으로 대체하지 않습니다.

- **Dialogue `_rule_actions`:** `out_of_scope`로 분류돼도 진행 중 확정 견적이 있고, 검증된 조건 변경이면 이를 허용하도록 보완합니다. “조회·보존절·다른 공종 요청은 `_rule_changes`의 grounded 검사로 걸러진다”는 주석이 추가돼 있습니다. 이는 진행 중 견적 처리에 대한 규칙 예외이며 `_rule_route` 자체 변경은 아닙니다. diff의 첫 hunk([hotfix_backend.diff:1–17](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/hotfix_backend.diff:1)).

- **Scope 분석·조건 처리:** `scope.py`에 수량 앞 라벨 추출, 같은 단위의 조건 수량 구분을 추가합니다. 높이 8m·폭 1.5m 같은 구분된 값을 다루고, 라벨이 없거나 중복되면 모호하게 둡니다([hotfix_backend.diff:40–89](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/hotfix_backend.diff:40)).

- **단일 견적 값 채움:** `fill.py`에도 라벨 기반 수량 해석과 반복·모호 값 검사를 추가합니다([hotfix_backend.diff:234–301](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/hotfix_backend.diff:234)). 이는 입력 추출·검증을 개선하지만 intent·대상·작업 목록을 한 번에 정하는 변경은 아닙니다.

- **적용 범위 차단과 결과 노출:** `tools.py`, `gate.py`, `dialogue_service.py`, `main.py` 등에서 명세 적용범위 평가, 차단·오류 상태 구분, 화면 상태/사유 전달을 손봅니다([hotfix_backend.diff:112–230](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/hotfix_backend.diff:112), [diff:305–416](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/hotfix_backend.diff:305)).

**정리:** 핫픽스는 `scope.py`, `dialogue.py`, 입력 추출과 계산 적용 범위를 직접 건드리므로 새 라우터의 작업 목록·조건 값 추출과 중복될 여지가 있습니다. 반면 `_uses_dialogue`, `_rule_route`, LLM 라우터 prompt/schema에는 직접적인 통합 변화가 보이지 않습니다.

## 5. 개선안 초안: 구조화 해석 1회 + 코드 검증

한 번의 자연어 해석 결과를 **라우팅 및 값 추출 후보**로 삼고, 적용 가능성과 안전성은 기존 코드가 결정하는 방식이 적합합니다. 스키마의 `evidence`는 원문에서 그대로 발췌한 구절이어야 하며, 코드에서 실제 원문 포함 여부와 수치·단위를 확인합니다.

```json
{
  "intent": "estimate",
  "target": "current",
  "operations": [
    {
      "kind": "change_condition",
      "work": "현재 견적",
      "field": "height",
      "value": "6",
      "unit": "m",
      "evidence": "높이를 6m로 정정해줘"
    },
    {
      "kind": "calculate_cost",
      "work": "현재 견적",
      "evidence": "비용 다시 계산해줘"
    }
  ],
  "conditions": [
    {
      "field": "height",
      "value": "6",
      "unit": "m",
      "evidence": "높이를 6m"
    }
  ],
  "ambiguities": [],
  "confidence": 0.94
}
```

권장 enum 예: `intent`: `estimate | qa | out_of_scope | clarify`; `target`: `current | new | none | ambiguous`; 작업 종류: `find_work | set_condition | calculate_labor | calculate_cost | lookup_basis | search_standard`. `operations`는 순서를 유지합니다. 질문·요청 하나에 작업이 여럿이면 각 작업의 대상·근거를 분리합니다.

**코드에 남길 검증**

1. JSON schema/enum/필수 키·타입·길이, 유효하지 않은 출력 및 LLM 장애 fallback.
2. 근거 구절이 사용자 원문에 실제로 있는지, 숫자와 단위가 근거와 일치하는지.
3. 공종별 필드·허용값, 단위 호환성, 0 이하 값, 중복·모순 값과 같은 필드에 대한 상충 후보.
4. 작업·필드 지원 여부와 실제 계산기·명세 연결 가능성.
5. pending 질문의 ID/ref/version 및 사용자가 실제로 선택한 대상·범위 확인.
6. 현재/새 견적 선택이 모호할 때는 session을 변경하지 않고 확인 카드 제공.
7. `scope.confirm_analysis`, `tools.set_conditions`, 적용범위 차단 규칙 등 기존 도메인 검증과 실행 권한 확인.

**단계별 이행 순서**

1. 평가 기준 추가: 기존 46개 route 문항을 유지하고, 현재/새 견적, pending 답변, 조회/변경, 다중 작업, 부정·모순을 포함하는 Dialogue 케이스를 보강합니다. LLM 없이 규칙 결과를 고정해 비교할 수 있어야 합니다.
2. 신규 schema와 검증기를 별도 경로로 도입합니다. 기존 tool 실행·검증기를 재사용하고, 우선 로그/비교 모드로 차이를 기록합니다.
3. API 선택 판단을 Dialogue 내부와 일치시키되, 저장된 checkpoint 및 legacy 호환 분기는 별도 회귀 테스트 후 변경합니다.
4. Dialogue의 초반 scope 진입, `_rule_actions`, `_cost_target`, `_lookup_only` 판단을 단계적으로 구조화 결과를 소비하도록 바꿉니다. 모호한 경우 기존 확인 흐름을 유지합니다.
5. 기존 그래프 LLM 라우터와 `router.md`를 새 구조와 맞추고, 신·구 경로의 분류·작업 차이를 로그와 오프라인 평가로 검토합니다.
6. 비교 결과가 기준을 만족한 뒤에만 기존 정규식 분기를 제거합니다. 검증 규칙과 안전 fallback은 끝까지 유지합니다.

**주요 위험:** LLM이 구조적으로 유효한 JSON을 내도 의미·근거·대상은 틀릴 수 있습니다. 작업 분리 오류는 여러 견적에 잘못 적용될 수 있고, 상태가 있는 대화에서는 중복 실행이나 과거 답변 오적용으로 이어질 수 있습니다. 한 번의 넓은 schema 호출은 비용·지연·실패 영향이 커질 수 있으므로, 근거 검증 실패 시 보수적으로 확인을 요구해야 합니다.

## 6. 핫픽스와 충돌이 적은 순서

핫픽스 계획 문서([APPLICABILITY-HOTFIX-PLAN.md](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/APPLICABILITY-HOTFIX-PLAN.md))와 상담 문서([CONSULTATION-COMMON-PATH-2026-11-03.md](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/CONSULTATION-COMMON-PATH-2026-11-03.md), [CONSULTATION-STRUCTURE-TASK-2026-11-03.md](C:/Users/user/AppData/Local/Temp/claude/661324a6238258b6/8d24d360-eb28-4919-88a2-77aba3e53696/scratchpad/router_ctx/CONSULTATION-STRUCTURE-TASK-2026-11-03.md))를 참고하면, 이 핫픽스는 조건 해석·scope 분석·적용범위 차단·응답 노출에 걸쳐 있습니다. **권장 순서**는 다음과 같습니다.

1. 진행 중인 핫픽스의 의도와 영향 범위를 먼저 확정하고, 해당 조건·적용범위 경계 사례의 평가를 보강합니다.
2. 핫픽스 변경을 반영한 기준선에서 구조화 라우팅 평가 문항을 추가합니다.
3. 새 해석기의 schema·원문 근거 검증기만 별도로 도입해 비교 결과를 수집합니다. 핫픽스와 겹치는 `scope.py`·조건 추출은 한 번에 교체하지 않습니다.
4. 그 다음 API 경로 선택 및 Dialogue의 대상·액션 판단 연결을 순차 변경합니다.
5. 새 경로가 안정된 후 사용되지 않는 기존 판단 코드를 제거합니다.

이 순서는 핫픽스가 조정 중인 조건 추출·scope 규칙을 구조화 라우터가 먼저 덮어써 충돌하는 것을 줄입니다. **추측:** 새 라우터를 핫픽스와 동시에 scope 분석에 연결하면 같은 문장의 분할·조건 귀속 결과가 달라져 핫픽스의 기대 동작과 구분하기 어려운 회귀가 생길 수 있습니다.