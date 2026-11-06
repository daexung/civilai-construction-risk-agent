# 적용 범위 안내·조기 검증·결과 전달 핫픽스 — 최종 구현 보고 (Sonnet)

대상 계획: `../plans/APPLICABILITY-HOTFIX-PLAN.md`. 병행 문서: `./applicability-hotfix-sol-review-2026-11-01.md`
(Sol의 재현·검토). 이 문서는 구현 측 최종 상태이며, 이전 라운드의 중간 보고(일부 서술 오류 포함)를
대체한다. 과거 체크박스를 그대로 복사하지 않고 이번 라운드까지의 실제 결과만 기록한다.

브랜치 `codex/hotfix-conversation-20261101`, 기준 HEAD `43a3b4acf4238681df40408cbe644dd9fc6e3a8c`.
커밋·푸시·머지·배포·운영DB·외부 모델/임베딩 호출 없음. 계산 확대 브랜치(8593269)는 섞지 않았다.
계산식과 6m/0.9m 등 기존 수치 기준은 변경하지 않았다.

## 1. 구현 내용

**공통 적용 범위 경로** (`backend/agent/estimate/tools.py`)
- `applicability_scope(spec)`: 선택된 명세의 `blocked`(수치/선택 비교식이 있는 구조화 규칙만 —
  `blocked_if`/`blocked_if_all`이 없는 설명형 선언은 제외) + `not_calculated`(별도 계상)를 그대로
  구조화해 반환한다. 승인 모듈의 `handled_conditions`가 해소한 제한은 제외한다. 창작된 값·새 정책 없음.
- `compute_labor()`에서 spec이 정해지면 **질문 단계 진입 여부와 무관하게** 매 호출마다 현재 spec으로
  다시 만들어 `item["applicability_scope"]`에 저장한다 — 즉시 BLOCKED되거나 질문 없이 바로 계산되는
  요청에서도 노출되고, 캐시하지 않으므로 공종 재선택 시 낡은 안내가 남지 않는다.
- `state.py:_bump()`(조건·공종이 바뀌는 모든 경로가 지나가는 공통 지점)에서도 이 값을 지워 과거
  명세의 안내가 섞이지 않게 한다.
- `check_registered_blocked`가 조기에(아직 다른 필수 질문이 남아도) 범위 초과를 판정할 수 있으면
  무관한 질문(단위 불일치·할증 포함)을 더 하지 않는다. `check_blocked`의 반환이 실제 차단(BLOCKED)인지
  규칙 평가 오류(`status=="unresolvable"` → ERROR)인지 `gate.py`/`tools.py` 양쪽에서 구분한다.

**조건 정정 복구** (`backend/agent/nodes/fill.py`, `backend/agent/estimate/dialogue.py`)
- `_labeled_quantity()`: 같은 단위(예: m)를 쓰는 필드가 여럿일 때, 명세 질문문(`ask`)에 있는 라벨
  ("높이"/"폭")이 수치 바로 앞에 있을 때만 그 필드로 읽는다. 라벨 없는 숫자나 같은 라벨에 서로 다른
  값이 반복되면 비워 둔다(ambiguous) — 임의 배정하지 않는다.
- `_rule_actions()`의 `route=="out_of_scope"` 조기 반환이 이미 선택된 명세에 대한 **명시적·검증된**
  조건 변경(`_rule_changes`가 grounded하게 뽑은 값)까지 버리던 결함을 고쳤다. 조회/보존절/다른 공종
  요청은 `_rule_changes`가 그대로 비워 걸러낸다. 실제 재현: "가설 계단 18㎡ → height=8 BLOCKED →
  '높이를 6m로 정정해줘' → width만 재질문 → width=0.9 → PARTIAL 계산 도달"을 실 서비스 경로로 확인.

**상태 전달** (`backend/api/dialogue_service.py`, `backend/api/main.py`, `backend/agent/state.py`)
- `legacy_state()`가 죽은 `turn.last_status=="blocked"` 비교 대신 `item["status"]`를 직접 보고
  BLOCKED/UNSUPPORTED/NOT_FOUND/ERROR 사유·근거(`result.citations`/`result.input`)를 보존한다.
- `RATE_VERSION_CONFLICT`(가격 버전 충돌)는 `ERROR`로, 산정 대상이 없는 `NO_RESULT`(조회 전용 포함
  가능)는 별도 `NO_RESULT` 상태로 분리했다 — 둘 다 더는 BLOCKED/"공식 범위 밖"으로 뭉뚱그리지 않는다.
- 다중 공종의 `multi_trade_items`에도 BLOCKED 항목의 reason/citations/input이 실제로 내려가게
  `raw_item_state["result"]`를 채운다. 정상 형제 항목·부분합계·Excel은 그대로 보존(계산 경로 미변경).

**프런트** (`frontend/src/types.ts`, `frontend/src/components/ChatArea.tsx`)
- `ApplicabilityScopeCard`: 상태와 무관하게 `response.applicability_scope`/각 `multi_trade_items[i]`가
  있으면 표시(질문 단계 전용 아님). 핵심 limits + 별도 계상만 간단히 나열, 설명형 규칙은 애초에 목록에
  들어오지 않으므로 "전부 공식 불가"로 단정하는 문구를 만들지 않았다(펼쳐보기 등 추가 레이아웃은 없음 —
  목록이 아직 길지 않아 요약 수준 정리만 했다. 긴 목록에 대한 "요약+펼쳐보기" UI는 미구현).
- `BlockedCard`: 사유·기준(source)·근거를 표시하고 "값을 바꾸면 계산될 수 있습니다" 같은 유도 문구를
  제거했다. 연결되지 않았던 `onEditConditions` prop/버튼은 **제거**했다 — 조건 정정은 이미 실제로
  동작하는 채팅 메시지 경로("높이를 6m로 정정해줘")로 안내 문구에서 바로 알려준다(새 버튼 프레임워크
  없음).

## 2. 실행한 검사와 실제 결과

모두 검색만 결정적 fixture로 고정한 실제 dialogue 그래프/`estimate/tools.py`/API 변환 경로다
(모델·임베딩·HTTP TestClient 미사용).

| 명령 | 결과 |
|---|---|
| `evals/check_applicability_hotfix.py` | **5/5**. 높이8m 조기차단(무관 질문 중단)·사유 유지, 경계값(6m/0.9m) 정상 진행, "안됐어" 반복 시 동일 사유 유지, "높이를 6m로 정정해줘"→width만 재질문→PARTIAL 계산 도달, 라벨 없는 "6m" 미배정. |
| `evals/check_applicability_representatives.py`(신규) | **7/7**. `compute_labor`/`gate` 공통 경로로 formula(1-1-2)·lookup_only(1-2-3) 실행, AND 복합조건(건축10-3-1 창호유리)의 부분입력(한쪽만 참)·완전위반(둘다 참)·거짓절 비위반·단일조건 즉시차단 4가지, malformed 규칙(숫자 아닌 기준값)이 ERROR 분류(unresolvable)로 가는지 확인. |
| `evals/check_multi_formwork_height.py` | **4/4** (기존, 영향 범위라 재확인). 승인 모듈 handled_conditions 해소 유지. |
| `evals/check_unified_estimate_chat.py` | **12/12** (기존, 영향 범위라 재확인). 다중 공종 혼합·형제 보존·복원·Excel 공통 회귀. |
| `frontend ChatArea.test.js` | **14/14** (기존12 + scope 요약 표시·BlockedCard 사유/근거 표시 신규 2개). |
| `npm run build` | 통과(무관한 posthog 소스맵 경고만, 오류 없음) — 이번 라운드의 최종 UI 변경 이후 재실행. |
| `check_estimate_tools.py`의 `_quantity_dependent` `TypeError: unhashable list` | **이번 핫픽스와 무관함을 확인**: `git diff HEAD -- backend/agent/estimate/tools.py`의 모든 변경 구간(24-25줄, 414-533줄)이 실패 지점(109/111/114줄)과 겹치지 않음을 직접 diff로 확인했고, 그 상태로 재실행해도 동일하게 재현된다. 즉 해당 함수는 HEAD와 바이트 단위로 동일한 코드이며 이 핫픽스의 범위 밖 기존 결함이다. **고치지 않았다.** |

**브라우저 검증용 서버**: `evals/serve_applicability_browser.py` 신규. 로그인/DB/usage 과금과 분리된
loopback 전용, in-memory(LangGraph MemorySaver) 서버다.

```
PYTHONPATH=. AGENT_OFFLINE=1 AGENT_LLM=off AGENT_MODE=tools .venv/Scripts/python.exe evals/serve_applicability_browser.py
```
- 포트: `127.0.0.1:8765` (환경변수 `APPLICABILITY_BROWSER_PORT`로 변경 가능)
- `GET /api/health` → `{"status":"ok"}`, `GET /__meta` → 어떤 부분이 모의인지 명시
- 모의: 검색(`retrieve`)만 "가설/계단/거푸집/레미콘" 키워드 → 해당 spec 고정 반환. 그 외 전부 실제
  `dialogue_service.respond/restore/export_response` + `build_xlsx`.
- 모의 아님(실제 그대로): dialogue 그래프, `estimate/tools.py`, API 응답 변환, XLSX 내보내기.
- 다루지 않음: 인증, 운영 Postgres 대화 저장소, `usage_limits` 과금 로직(`/api/usage`는 고정 샘플값).
- 테스트 계정 불필요(로그인 없음). `frontend/build`가 있으면 `/`에서 실제 화면을 서빙한다(이번
  라운드에 재빌드 완료).
- **직접 실행해 확인함**: `/api/chat`에 "가설 계단 견적"→scope 포함 질문→"계산에 포함" 답변 →
  응답에 `applicability_scope.limits`(높이6m/폭0.9m 두 조건)가 실제로 내려오는 것을 curl로 확인 후
  서버를 종료했다(상시 구동 아님, Sol이 재시작해 브라우저로 이어서 확인).

## 3. 정적 규칙 점검 (Sol 수행)

Sol이 `tmp/claude-applicability-hotfix-20261101/static-rule-review.json`에 기록. 로드 925명세 663선언
= 구조화 598 + 설명형 65. 구조화 조건의 미선언 입력·미지원 연산·기대값 누락·잘못된 멤버십 리스트 형식은
0건. **원문 의미 정확성이나 전수 계산 정확성의 보증이 아니다.**

## 4. 미검증/미완료 — 완료로 표시하지 않음

- 실제 브라우저(Chrome 등)로의 수동 확인: 서버만 준비했고 브라우저 자체 확인은 Sol 담당(§2의 curl
  확인은 브라우저 검증을 대체하지 않음).
- 설명형(문장형) 65개 선언에 대한 전용 "확인사항" 화면/펼쳐보기 UI: scope 목록에서 제외만 했고,
  별도로 보여주는 화면은 만들지 않았다(미표현으로 보고).
- 조건 정정은 기존 채팅 메시지로 실제 동작하지만, 전용 "정정하기" 버튼·공종 재선택 버튼의 UX는
  의도적으로 만들지 않았다(불필요한 프레임워크 추가 대신 기존 경로 사용을 선택).
- 다중 공종 "전체 차단"(모든 항목이 BLOCKED) 전용 신규 회귀는 없다. 단일 항목 BLOCKED·혼합(PARTIAL)
  경로는 `check_applicability_hotfix.py`/`check_unified_estimate_chat.py`로 확인했다.
- `check_estimate_tools.py`의 `unhashable list` 결함 자체의 수정: 이번 핫픽스 범위 밖으로 판단해
  남겨뒀다(§2 근거 참고).
- 전체 품셈 원문 규칙의 의미적 완전성, 전수 계산 정확도: 검증 대상이 아니다(계획 범위 밖).

## 5. 변경 파일

`backend/agent/{state.py,nodes/fill.py,nodes/gate.py,estimate/{tools.py,state.py,dialogue.py}}`,
`backend/api/{dialogue_service.py,main.py}`, `frontend/src/{types.ts,components/{ChatArea.tsx,ChatArea.test.js}}`,
신규 `evals/{check_applicability_hotfix.py,check_applicability_representatives.py,serve_applicability_browser.py}`.

커밋·푸시·머지·배포 없음. Sol이 브라우저 검증·최종 코드 리뷰·PR 준비를 이어간다.
