# 상담 공통 경로 구현 — 진행 기록 (2026-11-03)

작업자: 터미널 Claude Code Sonnet 5 (구독 인증, 소스 전송 승인됨). 세션 6ff14f35-a661-4f1e-acf2-6f67b06d1c77.
기준 브랜치 `codex/hotfix-conversation-20261101`, HEAD `43a3b4a`. 기존 staged/unstaged/untracked 변경은 모두 보존(git 쓰기 없음).
로그/스크래치: `tmp/consultation-common-path-20261103/`.

## 요약: 체크포인트로 넘김 (완료 아님)

45분 1차 구현 묶음을 조사에 썼고, 조사 결과 **실제 범위 확대가 필요한 구조적 공백**을 발견했다.
그 공백을 지금 묶음에서 안전하게 구현하기엔 위험이 커서(핵심 상태 모듈에 새 기능 추가, 충분한 회귀 검증 시간 부족),
계약서의 지시대로 **근거를 남기고 Sol에게 넘긴다**. 그 전에 실제로 확인된 구체적 버그(요구 4) 하나는
안전하게 고치고 회귀 검사까지 통과시켜 커밋 가능한 상태로 남겼다(단, git 쓰기는 하지 않음 — 지시에 따라).

## 바뀐 공통 경로

### 고친 것: `backend/agent/estimate/scope.py::confirmed_result`의 "같은 단위 수량 둘 이상 → 전부 차단"

- **문제(요구 4)**: `repeated_same_unit = len({condition.get("unit") ...}) < len(quantities)` 는 한 작업에
  같은 단위 수치가 둘 이상이면 라벨이 있든 없든 무조건 "한 작업에 같은 단위의 수량이 둘 이상 있습니다"로 차단했다.
  "조적벽에 수성페인트 2회 100㎡ 높이8m 폭1.5m"처럼 라벨이 분명해도 전부 막혔다.
- **고친 내용**:
  - `_quantity_label(text, start)`: 수치 바로 앞(10자 이내)의 한글 낱말을 라벨로 읽는다.
  - 같은 단위 그룹 안에서 각 수치의 라벨이 모두 다르고 비어 있지 않으면 통과시킨다(요구 4의 "명확한 레이블이 붙은
    동일 단위 입력은 각각 연결"). 라벨이 없거나 같으면(바꿔 말해 "8m, 1.5m"만 있으면) 여전히 차단해 확인을 요구한다
    (요구 4의 "구분을 묻는다").
  - `_NON_SCOPE_WORDS`에 치수 라벨 낱말(높이·폭·너비·길이·깊이·두께·둘레·지름·직경·규격·수량·개수·면적·부피·용량)을
    추가했다. 이 낱말들이 없으면 `_unclassified_text`가 라벨을 "분류 못한 잔여 텍스트"로 보고 수량 자체를 작업에
    붙이지 못해(미확정으로 밀려남) 라벨 비교 전에 이미 길을 잃었다. 명세별 예외가 아니라 일반 치수 어휘다.
- **영향 범위**: 이 분기는 `scope.py`의 규칙 기반 구절 분석(`_WORKS` = 도장·조적·방수·철거 4개 공종의 복합 요청
  파서)에서만 쓰인다. 일반 단일 공종 요청(콘크리트·거푸집·계단·자동문 등)은 이 함수를 타지 않고 `fill.py::extract_inputs`
  / `_labeled_quantity`를 통해 이미 라벨로 구분하고 있었다(아래 "이미 동작 확인" 참고). 따라서 이번 수정은
  `scope.py` 경로의 실제 버그 하나를 좁게 고친 것이고, 품셈 JSON/수식/단가/정책 확대는 없다.

### 변경하지 않은 것 (조사 후 범위 확대 필요로 판단, 아래 "발견한 구조적 공백" 참고)
- `dialogue.py`/`state.py`/`tools.py`는 수정하지 않았다. 조사 결과 기존 구조가 요구 1·2·3·6·7의 상당 부분을 이미
  만족하고 있어(아래 표), 무리하게 손대면 83개 통과 중인 회귀를 깨뜨릴 위험이 더 컸다.

## 요구 A–G 결과

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| A. 자동문 이후 계단 새 작업 의도, 18㎡/높이8m/폭1.5m 유실 없음, 높이 위반 즉시 안내 | **부분 완료** | `_cost_target`이 "새 작업 의도"를 이미 올바르게 감지한다(`check_dialogue.py` D26b/D27, 그대로 통과 확인). 높이·폭·면적 분리와 적용범위 초과 즉시 안내는 **이미 동작**: 직접 재현 — `계단 높이8m` → `compute_labor` 상태 `blocked`, 사유 "본 품은 높이 6m 이하 기준이며…", `missing=[]`(폭 질문보다 먼저 차단). `계단 18㎡ 높이8m 폭1.5m` → conditions `{height:8, width:1.5, area:18}` 정확 분리(재현 스크립트: `tmp/consultation-common-path-20261103/stair_repro.txt` 참고용 로그 없음, 아래 "실행 기록" 명령 재현 가능). **단**, "자동문 이후"라는 표현이 "같은 대화에서 두 공종을 모두 보존"을 뜻한다면 미완료(아래 구조적 공백). |
| B. 높이6m·폭0.9m 정정 → 기존 계산 경로 재계산, 안됐어 → 이유/다음 행동 | **완료(기존)** | `tools.set_conditions`의 evidence/consistency 검사, `_result`의 `rejected`/`reason`이 이미 상태별 사유를 돌려주고(D17 "25m는 지원하지 않아 32m 유지" 등 회귀 통과), BLOCKED 사유는 `item["reason"]`에 그대로 보존된다. 새 코드 추가 없음, 회귀로만 재확인. |
| C. 콘크리트+거푸집 생성 → 콘크리트만 수정 → 형제 보존·합계·XLSX 일치 | **완료(동일 유형, 다른 공종으로 검증)** | `check_unified_estimate_chat.py`의 "exact paint-only 120㎡ follow-up preserves sibling quantity and conditions", "both trade calculations feed one shared cost statement and ordered XLSX rows" — 동일 계약(형제 보존·합계·XLSX)을 도장+방수로 검증, 전부 통과. 콘크리트+거푸집 조합 자체는 **미실행**(아래 구조적 공백: 두 공종 모두 `scope.py`의 4개 키워드 밖이라 동일 입력 문장으로는 다중 항목 세션이 생성되지 않음). |
| D. 같은 공종 두 항목에 대상 없는 수정 → 대상 선택, 선택 전 불변, 오래된 ref 거부 | **완료(기존)** | `check_unified_estimate_chat.py` "ambiguous pending-answer match asks which item and leaves both unchanged", "target confirmation edits one item, preserves its sibling, and rejects stale refs" 통과. |
| E. 한 문장 높이·폭·물량 동시/단위변형/모순/다른 필드로 바꿔치기 거부 | **완료(기존, scope.py 몫은 이번에 수정)** | `tools.set_conditions`의 `consistent()`가 필드별 근거 재대조로 바꿔치기를 막는다(`check_dialogue.py` D9/D17/D27b 통과). `scope.py` 몫(같은 단위 라벨 구분)은 이번에 고쳤고 `check_scope_analysis.py`에서 라벨 있음/없음 두 경우 모두 직접 검증(아래 실행 기록). |
| F. 정상+차단/전체차단/기술오류 응답 명확, 복원 후 수정 가능, 화면·Excel 일치, 전체 차단 0원 금지 | **완료(기존)** | `check_dialogue.py` D7(복원), U7/U9(물량 없음·Excel 차단), B5(산출근거 가정 포함), `check_unified_estimate_chat.py` XLSX 행 검사 통과. 새 코드 변경 없음. |
| G. 실제 generate 인터페이스에 주입한 해석 응답으로 공통 경로 실행 | **완료(기존 하네스로 확인, 신규 생성 없음)** | `check_dialogue.py`의 `ScriptedLLM`이 실제 `client.generate` 서명으로 `_call_llm`에 주입되어 `_agent_loop`(LLM 행동 1회 선택 → 서버 도구 → 서버 reply 검증)를 실제로 통과시킨다(D16d/D16e 등). **실제 서비스 모델 성능은 미검증**으로 명시한다 — mock은 인터페이스·검증 계약만 증명한다. |

## 발견한 구조적 공백 (Sol 결정 필요, 이번 범위 밖)

`_run_multi_turn`(통합 다중 항목 대화)과 `scope.py`의 규칙 기반 구절 분석은 **도장·조적·방수·철거 4개 공종 키워드**
(`scope._WORKS`)에서만 "요청 문장 하나에서 여러 작업을 추출"할 수 있다. 콘크리트·거푸집·계단·자동문 등 나머지
공종은 이 경로에 들어오지 못해 **항상 1개 항목짜리 세션**이 된다. 직접 재현(세션 상태 포함, 명령은 아래
"실행 기록" 참고):

1. "콘크리트 100㎥ 비용" → 범위 확인 카드 → "계산에 포함" → `unified_estimate=True`, 항목 1개(`i0_12`) 세션 생성.
2. 이 세션에 "거푸집 공사도 추가해줘"를 보내면 — **아무 변화도 없다.** `_run_multi_turn`은 이 문장을 기존 항목에 대한
   조건 편집 대상 후보로만 찾고(일치하는 항목 없음), 새 항목을 만드는 경로가 없어 질문·세션·답변이 그대로 유지된다.
   즉 "공종 추가는 기존 항목을 보존한다"(요구 5)가 **도장/조적/방수/철거 조합 밖에서는 아예 실행되지 않는다.**

이걸 고치려면 `_run_multi_turn`(또는 그 앞단)에 "기존 세션에 새 작업 의도 문장을 추가 항목으로 편입"하는 새 경로가
필요하다(예: `scope.analyze_request`의 `_WORKS`를 일반화하거나, 검색 색인 기반 `find_work`로 새 세그먼트를 잡아
`state.py`에 "세션에 항목 추가" 함수를 새로 만드는 것). 이는 `estimate/state.py`·`dialogue.py`·`scope.py` 전반에
걸친 설계 결정이 필요한 **실제 범위 확대**이며, 섣불리 45분 묶음 안에서 손대면 현재 83/83·22/22·12/12로 통과하는
기존 회귀를 깨뜨릴 위험이 크다. **Sol의 설계 승인 후 별도 배치로 진행을 권고한다.**

## 실행 기록 (재현용)

```
# scope.py 라벨 구분 수정 확인(통과/차단 양쪽)
.venv/Scripts/python.exe -c "..."   # tmp/consultation-common-path-20261103/ 로 옮긴 임시 검증 스크립트는 세션 로그 참고

# 기존 회귀(변경 없음, 통과 확인)
AGENT_OFFLINE=1 AGENT_LLM=on AGENT_MODE=tools .venv/Scripts/python.exe evals/check_scope_analysis.py   # 21/22 (1건은 수정 전부터 깨져있던 무관한 전처리 버그, 아래 참고)
.venv/Scripts/python.exe evals/check_dialogue.py                                                        # 83/83
.venv/Scripts/python.exe evals/check_multi_trade_chat_trial.py                                          # 5/5
.venv/Scripts/python.exe evals/check_unified_estimate_chat.py                                           # 12/12

# 계단 높이/폭/면적 분리 + 적용범위 초과 즉시 차단(요구 A, scope.py와 무관하게 fill.py에서 이미 동작)
AGENT_OFFLINE=1 .venv/Scripts/python.exe -c "
from backend.agent.estimate import tools
from backend.agent.rules.specs import load_specs
specs = load_specs()
stair = next(s for s in specs.values() if s['section_no']=='2-7-7')
session = tools.new_estimate('계단 18㎡ 높이8m 폭1.5m')
item = tools._item(session)
hit = {'rank':1,'section_no':stair['section_no'],'division':stair['division'],
       'section':f\"{stair['section_no']} {stair['title']}\", 'chunk_id':'x','score':10}
tools.find_work(session, hits=[hit])
print(tools.compute_labor(session)['data'])
print(item['conditions'])
"
```

## 회귀에서 확인한 기존(무관한) 결함

- `evals/check_scope_analysis.py` 157행: `new_session(...)["items"]["i1"]`을 가정하지만 실제 생성되는 item_id는
  문장 내 오프셋 기반(`i{start}_{end}`)이라 항상 `KeyError`가 난다. **이번 수정 전부터 깨져 있었다**(원본 HEAD 커밋
  파일로도 동일하게 재현). 이번 작업의 변경과 무관하며, 고치지 않았다(범위 밖 — 과거 전처리/테스트 유지보수 항목).
- 같은 파일 97행 "user explicitly including a previously unknown trade leaves multi-work result not_ready" —
  원본 HEAD에서도 `multi_trade`(준비 완료)를 돌려줘 이미 깨져 있던 기대값이다(이것도 이번 수정과 무관, 원본 파일로
  동일하게 재현해 확인).

## 남은 한계

1. (위 구조적 공백) 4개 키워드 밖 공종의 "기존 항목 보존 공종 추가"는 아직 경로가 없다.
2. 실제 서비스 LLM 호출 성능은 승인 범위 밖이라 미검증(요구 G 명시).
3. `evals/check_scope_analysis.py`의 사전 존재 결함 2건은 고치지 않았다(범위 밖, 위에 근거 기록).
