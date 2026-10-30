# 품셈이 — 전체 품셈 자동계산 출시 기준 계획

> 작업 위치 고정(2026-10-23): 통합 폴더의 `codex/calculation-integration-20261023` 브랜치에서 이어간다. 보존·분류 기록은 `docs/handoffs/WORKSPACE-CURRENT.md`를 먼저 확인한다.

기준일: 2026-10-21. 최우선 목표: 오늘 가능한 한 전체 견적 기능 구현과 필수 검증을 완료한다. 2026-11-03(KST)은 최종 상한이며, 14일을 모두 쓰도록 작업을 배분하지 않는다.
계획 상태: 현재 코드·저장 기록을 검토해 정리한 실행 기준. 일정은 목표이며 완료 보증이나 실행·유료 호출·배포의 신규 승인이 아니다.

## 1. 이 문서의 우선순위와 변경 규칙

이 문서의 2026-10-21 기준 계획을 현재 작업 기준으로 사용한다. 아래 `과거 계획 및 실행 이력` 이후 내용과 기존 인계 문서의 “오늘 범위”, “다음 작업”, “끝까지 계속”은 당시 기록이다. 현재 범위·우선순위·실행 제한과 충돌하면 이 기준 계획을 따른다. 사용자의 최신 명시적 지시는 항상 우선한다.

목표를 다시 정하는 문서를 만들지 않는다. 새 결함은 아래 작업 묶음의 결함 목록에 넣는다. 목표·출시 기준·실행 구조 변경은 문제 재현, 기존 구조로 해결되지 않는 이유, 일정·비용 영향과 사용자 결정을 기록한 뒤에만 반영한다. 작업 중 인계는 현재 위치·완료 증거·미완료만 갱신한다.

## 2. 해결할 문제와 고정된 제품 범위

사용자가 현장 사실을 입력하면 2026 정오표 1차 반영 표준품셈 전체의 적용 조건을 확인하고, 표·비고·참조 규칙에 따라 자원량과 견적을 계산하며, 다중 항목 수정·합계·복원·Excel까지 일치시키는 것이 최소 목표다. 일부 공종 공개를 전체 완료로 대체하지 않는다.

사용자는 물량·공법·높이·장비·재료 공급 방식 같은 현장 사실과 계약상 단가를 제공할 수 있다. 산식·감산률·누적 방식·근거 ID를 대신 정하게 하지 않는다. 공식 규정과 시스템 산정 정책을 구분한다.

두 결과를 함께 추적한다.
- 제품 계산: 모든 실제 계산 대상과 적용 규칙이 등록된 실행 경로로 동작한다.
- 명세 작성 자동화: 원문→후보→검사→제한 수정→검토 가능한 산출물 경로가 실제 생성 응답으로 검증된다. 제품에서 재사용 가능한 기존 명세를 전부 재생성하지 않는다. 에이전트가 직접 고친 명세를 이 경로의 자동 생성 성공으로 세지 않는다.

질문 이해·공종 선택·조건 수집·금액·출처·사용 가능한 화면을 포함한다. 전체 UI 재디자인, 모델 비교 연구, 신규 구독/결제 상품 개발은 이번 자동계산 출시 작업에 추가하지 않는다. 유료 서비스 출시에는 결제·보안·운영 기준이 별도로 필요하며 이 문서 통과만으로 그까지 완료라고 하지 않는다.

## 3. 확인한 기준선과 미확인 사항

실제 작업 위치는 `C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\tmp\integration-main-168d80a`, HEAD `168d80a426d5a348f666a9d2f03153b818e0fec7`이다. 원본 폴더는 이전 브랜치이므로 구현 기준으로 돌아가지 않는다. 미커밋·미추적 변경을 보존한다.

2026-10-21 읽기 검토:
- `data/drafts/executable.json`: 초안 1,058개, 기본 실행 924 / 실패 6 / 미지원 126 / 제외 2. 증분 기록이며 최신 전체 정확성 검사 결과가 아니다.
- 계산기별 통과 소계는 923으로 총수와 다르다. 미지원 분류 JSON은 149개, Markdown은 163개로 최신 126개와 다르다. 이 숫자로 제품 완성률을 계산하지 않는다.
- 기존 1,095개 공식 목차 3단계 절과 초안의 연결 차이도 남아 있다. 1,058개를 공식 전체 계산 대상이라고 확정하지 않는다.
- `lookup_only`, `formula`는 현재 runtime loader에 포함돼 있다. 미연결이라는 과거 결론을 반복하지 않는다.
- 거푸집 높이 입력과 실제 로컬 등록 파일의 7→10m 재계산은 §50에서 오프라인 통과했다. UI 및 실제 모델 재검증은 남아 있다.
- A–F 실사용 기록: A 수량 부분 확인, B 조건 반영에서 차단, E 대화 복원 부분 확인, C/D/F 미완료. Excel HTTP 200은 내용 일치 증거가 아니다.
- 기존 전체 규칙 검증 집계는 완성되지 않았다. 일부 원문·셀·규칙 검증 기록은 재사용하되 중복을 제거한다.
- 실제 명세 자동 생성의 검증 성공은 기록상 아직 없다. 원문 규칙의 애매함·단가 누락·파싱 손실을 모두 “모델 성능 문제”로 묶지 않는다.

## 4. 구현 구조는 유지한다

원문/표 추출 → 명세/규칙 데이터 → 기존 `per_unit`, `daily_crew`, `lookup`, `formula` 및 정책 → 상담 상태/계산 → 단가/집계 → Excel 구조를 사용한다.

같은 구조의 표 복구는 공통 변환과 데이터 매핑으로 처리한다. 공통 연산 부족은 기존 실행기를 확장한다. 격리 Python은 기존 실행기로 표현할 수 없다는 재현이 있을 때만 사용하며, 로컬 Docker 통과와 실제 배포 환경 실행 가능성을 별도로 검증한다.

기존 표를 사람이 확인해 복구하는 예외는 허용하지만, 그 비용과 이유를 기록하고 같은 형태는 일괄 처리한다. 공종 ID별 산식 하드코딩과 무제한 한 항목씩 수정하는 방식은 채택하지 않는다. `-`와 빈 셀은 원문상 의미에 따라 처리하며 일괄 0으로 치환하지 않는다.

## 5. 고정 작업 묶음과 완료 증거

| ID | 작업 | 완료 증거 |
|---|---|---|
| W0 | 기준선·환경·작업 목록 확정 | 전체 항목 ID/역할/참조 연결, 상태 합계 일치, 누락·중복 목록, 코드·명세·검사 해시, 재현 가능한 로컬 실행 방법 |
| W1 | 실행 경로 누락과 파싱·매핑 복구 | 실패 6·미지원 126 및 목차 누락의 현재 ID별 처리, 공통 원인별 수정, 원문 기반 기대값 및 영향을 받는 기존 항목 회귀 |
| W2 | 전체 규칙·정책·금액 완성 | 각 표·비고·참조 규칙의 실행/근거/시험 연결, 조건 분기·단위·반올림·적용 순서 검사, 정책 결정 기록, 비용 포함/제외·단가 연결 |
| W3 | 사용자 흐름 검증·수정 | A–F 실제 브라우저/서비스 모델 검증, 숫자 조건 입력, 다중 수정·복원, Excel 셀/합계 일치, D16 적용 질문의 의미·근거 확인 |
| W4 | 자동 명세 생성 경로 검증 | 현재 필요한 계산 유형을 대상으로 실제 생성→검사→제한 수정→최종 평가, 후보/기대값 격리, 결과·실패·사용량 기록 |
| W5 | 출시 후보 동결·검토 | 동일 코드/명세 해시에서 오프라인 전수 검사와 제품 회귀, 데이터/의존성 번들 누락 없음, 알려진 출시 차단 결함 0, 배포·복구 절차 |

W0는 구현 재시작이나 대형 재설계 과제가 아니다. 기존 저장 결과와 스크립트를 연결하고 한 번 현재 기준을 재현한다. W1~W4는 한 작업자가 의존성 순서에 따라 진행하며 매 묶음마다 사용자에게 목표를 다시 묻지 않는다.

정책·설명·기계 가격 참조 문서는 원문상 역할을 근거로 분류한다. 자체 물량을 계산하지 않는다는 이유로 미지원 실패와 혼합하지 않지만, 참조 소비 경로가 없다면 해당 기능은 미완료다.

## 6. 검증 방식과 출시 통과 기준

1. 모든 공식 대상은 계산 작업/공통 정책/참조 데이터 등 역할과 연결 근거가 있다. 실제 계산 대상 누락·미분류가 0이다. 목차 제외는 ID와 원문 근거를 기록한다.
2. 계산 작업마다 모든 적용 규칙이 실행 코드 또는 버전 있는 정책으로 연결된다. 메모에만 남은 계산 규칙·사용자 수식 입력 요구·유효 조건에서 미지원 차단은 0이어야 한다.
3. 기대값은 원문에서 별도로 산출하고 후보 출력을 정답으로 쓰지 않는다. 유한한 표 선택은 유효 셀 경로를, 연속 입력은 경계·대표값·단위 변환을, 조건 조합은 각 분기 및 상호작용을 검사한다. 무한 입력을 전수 시험했다는 주장을 하지 않는다.
4. 규칙 검증 manifest는 `항목 ID / 원문 위치 / 규칙 ID / 실행 위치 / 사례 ID / 기대값 근거 / 결과 / 코드·명세 해시`를 가진다. 기존 89절·303사례 등은 이 목록에 연결해 재사용한다. 공통 코드가 바뀌면 영향을 받는 증거를 미검증으로 돌린다.
5. 견적 총액은 자원량·단가·포함 비용·제외 비용과 대조한다. 미구현 비용을 “별도 계상”으로 돌려 통과하지 않는다. 고객 계약단가나 외부 공급가격이 원문에 없으면 필요한 단가만 명시하고 부분 견적으로 표시한다. 부분 금액과 계산 로직 미지원은 별개이며, 금액 검증에는 모든 필요한 단가가 주어진 사례를 포함한다.
6. 공식 자료가 율/결합을 정하지 않으면 Sol이 근거·대안·수량/금액 영향을 검토하고 정책안을 제시한다. 승인된 시스템 정책은 자동 적용하고 화면·Excel에 표시한다. 미결정 정책을 숨기거나 무기한 보류한 채 전체 완료라고 하지 않는다.
7. A–F는 정상 조건뿐 아니라 잘못된 단위·모호한 항목·누락 조건·모델/검색 실패도 확인한다. 미완료 상태를 성공으로 보이지 않게 한다. 신규 숫자 입력 기능은 모든 숫자 필드에 대한 영향도 확인한다.
8. 최종 출시 후보의 해시가 검사된 것과 일치한다. 전체 코드·명세 변경 후에는 최종 전수 검사를 한 번 실행한다. 이후 변경은 영향 검사와 후보 해시 갱신을 거친다.

## 7. 최단 완료 실행 순서 — 날짜별 대기 없음

| 순서 | 수행 내용 | 다음 작업으로 넘어가는 조건 |
|---|---|---|
| 즉시 | W0 최소 확인과 동시에 W1 시작 | 기존 기록에서 실제 대상과 원인 그룹을 식별하면 곧바로 수정한다. 완벽한 현황 문서 작성까지 기다리지 않는다. |
| 연속 처리 | W1·W2 공통 기능, 명세, 정책, 금액 | 수정한 그룹을 즉시 원문 기대값과 대조하고 영향 항목에 일괄 적용한다. 날짜별로 나누지 않는다. |
| 연결되는 즉시 | W3 사용자 흐름 | 계산 경로가 준비되면 같은 실행에서 상담·집계·Excel을 확인한다. 환경 준비를 마지막으로 미루지 않는다. |
| 필요한 경우 함께 | W4 명세 생성 | 남은 기능 구현에 필요한 생성만 수행한다. 이미 작동하는 기능을 다시 생성하거나 별도 연구로 제품 완성을 지연시키지 않는다. 작성 자동화 자체의 미검증 상태는 별도로 기록한다. |
| 구현 직후 | W5 최종 확인 | 전체 대상의 누락·규칙·제품 경로와 같은 코드 기준 검사를 마치면 즉시 검토한다. 기한을 채우기 위해 기다리지 않는다. |

오늘 완료를 최우선으로 시도하되, 실제 미검증 규칙과 실행 결함이 남아 있으면 완료로 선언하지 않는다. 126개가 모두 같은 난이도라고 가정하지 않는다. 기존 924개의 검증 증거는 재사용하고 부족한 규칙만 추가 확인한다. 처리량·남은 공통 결함·사용량을 실행 중 기록하며 별도 추정 과제로 구현을 멈추지 않는다.

실제 차단이나 예상 초과가 드러나면 즉시 구체적인 항목·원인·필요한 조치를 보고한다. 목표 축소나 기한 연장은 자동으로 하지 않는다. “2주 이내”는 최대 허용 기간이며 최소 작업 기간이 아니다.

## 8. 비용과 역할 — 무제한 실행 금지

- Sol: 단일 계획 유지, 결과 검토, 정책안·출시 판단. 사용자가 직접 작업자를 실행한다. 임의로 서브에이전트나 동시 작업을 생성하지 않는다.
- Luna 또는 Sonnet 한 명: 현재 묶음 구현·시험. 모델 교체 시 최신 짧은 인계와 영향 코드만 읽는다.
- 작업 묶음은 기본 45분 또는 동일 원인 수정 실패 2회 중 먼저 도달하면 저장·보고하고 종료한다. 한 묶음의 완료 조건과 대상 ID를 시작 때 명시한다. “전체가 될 때까지 종료 금지” 지시는 사용하지 않는다.
- 시간 제한은 크레딧 상한 보장이 아니다. 도구가 실제 토큰 한도를 제공하면 사용자 승인 범위 안에서 설정한다. 사용량 확인이 안 되면 미상으로 보고하고 임의 추정하지 않는다.
- 테스트/일괄 스크립트는 전체를 처리하되 모델에는 요약·변경 ID·대표 실패만 전달한다. 무의미한 폴링, 전체 PDF·명세·로그 반복 읽기, 변경 없는 전체 회귀를 하지 않는다.
- 매일 보고는 대상/규칙 분모, 검증 완료, 실패·미지원·미검증, 사용자 흐름 결과, 누적 비용, 다음 묶음만 담는다. 서로 다른 검증 범위를 합쳐 백분율을 만들지 않는다.
- 기존 A–F 예산은 총 20회/$2이며 9회·추정 $0.00552211 사용 보고가 있다. 잔여 승인 사용 여부는 최신 지시와 장부를 확인한다. 새 명세 대량 생성 예산으로 전용하지 않는다. 현재 새 대량 호출 승인 없음.
- W4/대량 생성이 필요하면 원문·요청 크기·최대 수정 횟수·단가·총 토큰을 바탕으로 상한을 먼저 제시한다. 구독 코딩 크레딧과 서비스 API 비용을 분리한다. 모델 변경·무료 프록시 탐색은 이번 일정의 기본 경로가 아니다.
- 운영 DB 변경·푸시·머지·배포 권한은 이 문서로 생기지 않는다. 로컬 검토·개발은 기존 권한을 따르고 운영 반영은 검증된 구체적 후보에 대해 승인받는다.

## 9. 바로 다음 작업과 멈춤 조건

다음 실행은 W1 구현 묶음이다. 기존 index의 924/6/126/2와 원인 목록은 필요한 부분만 확인하고 곧바로 가장 많은 항목을 해결하는 공통 결함을 수정한다. ID 정합화와 검증 증거 연결은 실행 결과로 함께 갱신한다. 첫 묶음의 산출물은 실제 코드·명세 수정과 영향 항목의 검사 결과여야 한다. 대형 문서나 새 프레임워크, 현황표만 만드는 준비 단계로 돌아가지 않는다.

이 기획 작성에서는 구현·테스트·외부 호출·에이전트 실행을 시작하지 않았다. 다음 묶음 역시 사용자가 실행하는 기존 방식으로 진행한다. 검토 후 프롬프트는 작업 ID와 이 문서를 참조하며 전체 계획을 다시 작성하지 않는다.

## 10. 고정 결정 및 변경 이력

2026-10-21: 서비스 명칭을 품셈이로 명시. 전체 자동계산 목표 유지. 제품 계산과 명세 작성 자동화를 별도 증거로 관리. 기존 구조 재사용. 준비 문서·개별 통과 수를 완료로 보고하지 않음. 과거 무제한 실행 지시 폐기. 14일 목표와 조기 일정 판단, 45분 실행 묶음 도입. 이는 코드 구조 변경이 아니다.

2026-10-21 사용자 정정 반영: 14일은 최종 상한이다. 날짜별 할당을 폐기하고 오늘 최대한 완료하는 연속 구현 순서로 바로잡았다. 제품 범위·정확성 기준은 유지한다. 첫 작업을 별도 현황 정리에서 실제 공통 결함 구현으로 변경한다. 크레딧 보호를 위한 실행 묶음 제한은 유지하되 작업을 다음 날짜로 미루는 근거로 사용하지 않는다.

---

# 과거 계획 및 실행 이력 — 아래의 기간별 지시는 현재 실행 지시가 아님

# Calculation Automation Master Plan

Date: 2026-10-18. This is the governing plan for complete construction-standard calculation automation. Preserve all pre-existing working-tree changes and evaluation records. A new owner starts by reading this plan, the current git diff, and the evidence for the stage being continued.

## Goal and current design mismatch

A user supplies site facts. CivilAI must check applicability, use the source tables, notes, and referenced provisions, calculate each work item, aggregate the estimate, and generate Excel. The minimum scope is every construction-standard item. Completing one manually authored trade is not completion of the full automation goal. Missing executor capabilities are common expression gaps to solve; they are not a reason to shrink scope or add repeated trade-specific patches.

The repository currently has overlapping designs: the older `SPEC_FORMAT.md` draft schema, an additive calculation contract, a constrained JSON interpreter, existing `adjusted_daily_crew` and `per_unit` calculators, policy references, and an isolated Python path. A draft or registered module is not proof that all its rules execute. Reuse existing calculators and estimate flows where possible, but make the executable contract preserve every applicable table cell, note, reference, condition, target, unit, order, and source locator.

## End-to-end structure

1. **Source capture:** pin edition and PDF hash; preserve PDF and printed-page mapping, section/work boundaries, table structure, labeled table notes, prose notes, and referenced provisions.
2. **Specification generation:** the model proposes the meaning of source conditions, formulas, targets/units, order, exceptions, and explicit table/note/reference mappings. Program code assembles deterministic IDs, source hashes/locators, executor metadata, and trusted evaluation-case metadata. Expected values are hidden from generation.
3. **Contract assembly and checks:** verify source completeness, units and targets, field declarations, policy scope/version, rule order, and structural contract. Classify results as source error, format error, execution failure, calculation mismatch, or pass.
4. **Execution:** reuse existing exact-rational calculator operations. Add a general shared operation only when a reproducible expression gap is established. Generated Python runs only in the existing isolated execution path.
5. **Verification and bounded repair:** run independent authoring cases and disjoint withheld cases with boundary, unit, rounding, and order checks. Feed classified failures back for bounded automatic repair. Never bypass failure by adding `blocked`, deleting a source rule, or asking the user to decide a system policy.
6. **Registration:** register only after the same candidate hash passes authoring and withheld evaluation and a reviewer approves its interpretation. Today no registration is performed.
7. **Consultation execution:** collect site facts, ask for missing site facts only, calculate each item, aggregate cost and quantity, and create Excel. Do not make the user choose a system calculation convention.

## Responsibilities

- **Program:** stable source IDs and hashes, input schema, contract assembly, unit/format checks, policy authorization, safe execution, expected-value comparison, trace, aggregate, Excel, versioning, and audit records.
- **LLM:** interpret source conditions, formulas, targets, exceptions, application order, and mappings to source cells/notes/references. Do not invent engineering decisions absent from the source.
- **Reviewer:** approve source interpretation, resolve genuinely unspecified policies, review boundaries and withheld cases, and authorize registration. Review shared rules rather than repeatedly writing code per trade.

Official source wording is an attributed rule with an exact scope and locator. A system policy is a separate, versioned operational choice for what the source leaves unspecified. Example: common section 6-3-1 says above 7 m, without lifting equipment, reduce output by up to 9% every 3 m. Counting started intervals, choosing the maximum rate, and compounding are system assumptions, not an official formula.

## Existing code to reuse and incomplete work

Reuse candidates: `backend/agent/tools/calc/daily_crew.py`, existing `per_unit.py` and price/aggregate calculators, `backend/agent/tools/calc/generated.py`, `backend/agent/tools/calc/policies.py`, `pipeline/calculation_contract.py`, `pipeline/calculation_modules.py`, `pipeline/python_sandbox.py`, and current consultation/Excel flow.

Known limits: `generated.py` mainly adjusts daily output; it does not cover every existing labor, equipment-time, material, price, and indirect-cost operation. Some `SPEC_FORMAT.md` notes are stale compared with active calculators. The table-note evidence fix and stable locator contract are recent; the old approved formwork module does not satisfy the new locator check. The isolated Python Cloud Run worker is not deployed or verified. Real model generation has not produced a valid candidate. Formwork is one narrow case, not the whole product.

## Verified and unverified facts

The 2026-10-18 record shows all 9 authorized Gemini generation/repair calls recorded and no valid model candidate. Historical OpenAPIs evidence is HTTP 503. No external model call is allowed today. Saved Gemini response replay diagnoses prior source-anchor and semantic failures, but historical source-bundle/schema hashes differ from current ones. A direct Luna-authored candidate is contaminated by prior exposure; it passed a bounded set of offline cases after manual repairs, but it is not model-generation evidence. `formwork-adjustments-v1` has a legacy `chunk-10` anchor. Its migration candidate can be evaluated but must not be registered today.

## Complete inventory and progress accounting

Keep three denominators separate: (A) source sections, (B) calculation work items within each section, and (C) individual table/note/reference calculation rules. Never combine them. Establish the source population from the official contents/page map, then link parsed sections, work items, rules, specs, and runtime artifacts. Track each state independently: source/parse confirmed; executable specification exists; representable in current executor; calculation verified; real automatic generation verified. Also track defects: source/parse, shared specification/executor capability, evidence/system policy, and not investigated.

An upper state never implies a lower state passed. A file in an execution list does not prove every condition is supported. Only report a rate for a verified denominator, with missing, duplicate, and uninvestigated counts. A hand-authored trade is separate from automatic-generation progress.

Expansion order: reconcile source/parse inventory; enumerate work items and rules; classify existing calculator coverage; cluster common expression gaps; prove generation and execution across representative complexity classes; run disjoint withheld evaluation; extend shared capabilities; then verify consultation, aggregate, and Excel integration across the inventory.

## Fixed release criteria

- **Calculation accuracy:** every source rule has a locator; no table/note/reference mapping omissions; site facts are separate from system policy; all work items pass independent authoring and withheld boundary/unit/rounding/order evaluation; aggregate totals reconcile; unresolved items are explicitly partial rather than called successful.
- **Chat UX:** required for launch but excluded from today's implementation. Validate concise fact collection, no repeated questions, source-backed question reasons, clear partial/unpriced output, trace, and Excel delivery with users.
- **Operational reliability:** candidate/registration separation, same-hash verification, constrained isolated execution, fail-closed behavior, reproducible trace/logs, and verified service plus Excel path. Code presence alone is not deployment verification.

## Today's scope and completion criteria

1. Write this governing plan from current code and records.
2. Reconcile source evidence and authoring/final fixtures. Preserve originals; store corrected versions and reasons. Replace positional indices with explicit values where possible. Classify already-diagnosed finals as regression cases. Keep new final inputs disjoint from authoring and disclose exposure. Verify the approved-module evidence migration candidate without registration.
3. Pin current source, policy, input, and checker hashes. Assemble program-owned metadata. Replay mocks and saved responses offline through available common paths. Separate mock, saved response, manual Luna, and real API results. Do not call an external model today.
4. Reconcile source list, parsed inventory, specs, and execution index. Publish counts at A/B/C granularity and common defects. No full regeneration or manual trade implementations.
5. Run only focused checks and record all outcomes.

If work departs from this sequence, record why and the impact here. A major architecture change requires reproducible evidence that existing paths cannot solve the shared gap plus an impact analysis; do not make it silently.

## Repeated-failure diagnosis and direction change

For repeated failures, build a minimal reproduction and inspect in this order: source/parse loss; locator/contract; input and independent expectation; expression/type/unit capability; executor; model semantic error. Record exact hashes, raw response, and status class. Do not disguise execution failure as a mismatch-only result. After two repetitions of one cause, write a common fix proposal and affected-item list, then compare reuse of existing calculators, a shared JSON operation, or isolated Python. Model failure alone is not grounds for manual per-trade implementation.

## Short rules for the next owner

Read this plan, the relevant validation report, and current git diff first. Never overwrite historical evidence; create a corrected version with its reason. Pin denominator and inputs before the stage. Do not invent source conditions or present policy as official text. Record real executions. Do not turn spec presence or schema pass into calculation success. Do not make external calls or operating registrations without new authorization.

## 2026-10-18 execution notes

No architecture change was made. Source evidence confirmed the policy anchor belongs to the labeled table note on PDF page 193 / printed page 137, not `chunk-10`. The original final fixture had an index/expectation mismatch; a Unicode-safe v3 regression fixture fixes the input without changing expected values. A v2 encoding-corrupted intermediate and its execution failure are preserved. Manual candidate and migration candidate results are in `docs/reviews/calculation-validation-2026-10-18.md`; the migration candidate remains unregistered. The inventory is 1,120 parsed section identities versus 1,058 draft work entries; rule-level denominator remains unknown. The prior semantic repeated-error test's zero callbacks were caused by its invalid dummy source bundle/spec; fail-closed policy preflight behaved correctly. The corrected PDF-backed mock regression now exercises bounded semantic repair; it does not prove real model quality. No external calls were made.

## 2026-10-18 offline generation-path addendum

The common `author_semantic_candidate` path was retained. It now returns `model_calls`, a structured attempt log with delivered sanitized feedback, and an exit reason; this makes callback-zero preflight stops distinguishable from generation and bounded-repair outcomes. The misleading legacy authoring docstring was corrected: expected outputs remain evaluator-only and repair feedback exposes case/field labels only. The focused mocked callback sequence proved calculation-mismatch feedback and repair, identical semantic failure suppression at two callbacks, and source-provenance rejection at zero callbacks. These are offline path checks, not model-generation success or independent accuracy evidence. See the validation review and its JSON record for hashes and callback details.

The v3 nine-case set remains exposed regression only. A new final evaluation may be authored by the same operator, provided each expected value is derived from pinned source evidence and a separately written calculation, is frozen and hashed before candidate creation/review, and is never included in generation or repair requests. Record the author's exposure to prior fixtures and candidates; do not claim a second-person review unless one occurred. If a final evaluation failure is used to modify that same candidate, retire that evaluation from future withheld-performance totals. Keep final evaluation callbacks disconnected from repair.


## 2026-10-18 cross-calculator path addendum

The same-operator final-evaluation rule above is confirmed: source-derived arithmetic, pre-generation freeze/hash, prompt isolation, exposure disclosure, no false claim of second-person review, and retirement after repair from that final set. Existing authoring 4 and v3 final 9 remain exposed regression/diagnostic only. Formwork v4 is a new 3-case source-derived final set with zero exact input-signature overlap against either formwork authoring or v3.

## 2026-10-18 integrated replay continuation

Use `evals/runtime_validation/integration-main-execution-replay-2026-10-18.json` as the exact-ID replay and evidence record; `data/drafts/executable.json` is its latest materialized runner output. The follow-up replay after source-cell diagnostic handling remained 475 pass / 249 fail / 332 unsupported-calculator skips / 2 exclusions over 1,058 draft proxies. The original 339 failures and 337 unassessed rows were both crosswalked against current code; the latter did not become 337 successful calculations. A common per-unit basis parser change raised the replay from 413 to 475 basic passes (+62) with no immediate pass-to-fail regressions. It is a basic synthetic-input execution check only.

Two daily-crew failures selected source cells containing `-` (maintenance pruning p915-t0 and flow-meter replacement p981-t0). The shared executor now returns a cited `unresolvable` result containing the selected cell instead of leaking a numeric-parser exception. The source does not establish zero or a calculable amount; both stay failures. A full supported-axis comparison found zero unique matches recoverable only by conservative NFKC/space/unit/punctuation normalization, so no generic fuzzy-axis selector was justified. The replay found no global axis patch that is safe to apply; most axis failures require correcting explicit source row/column mappings or parser structure. This is diagnostic normalization, not a full source-rule audit. Full rule accuracy remains zero verified; the official calculation-work and rule denominators are still unresolved.

Offline mock-response tests now exercise `per_unit` (1-2-2, p628-t5 steel labor per ton, with top-down/fabrication/delivery source preconditions) and `adjusted_daily_crew` (2-4-1, p97-t2 steel prop workdays and excavator deployment, with 2.0 m spacing precondition) through program-owned assembly of source/hash/page/input/executor/verification metadata, contract validation, actual pinned isolated execution, authoring mismatch feedback, one bounded repair, and separated final evaluation. Both pass 3/3 authoring after repair and 3/3 final; callback count 2 each. This verifies shared path mechanics only. It does not verify real model generation, all conditions within either section, consultation, aggregation, Excel, or all standards. See validation review and machine record. The 2-4-1 applicability omission was corrected with source-backed 2.0 m spacing input and block. No executor architecture change was made.

Next trial is sequential per-unit, adjusted-daily-crew, then formwork, each max 3 calls and $0.36 configured-rate reservation, total estimated ceiling $1.08; SDK retries are disabled. Fresh authorization, exact CountTokens, current SKU/rates, and cumulative reservation are required before call 1. If any type fails authoring, stop before the next type.

## 2026-10-18 full-scope continuation: inventory and product path

The user's goal remains all construction-standard calculations through consultation, aggregation, and Excel. This continuation does not mark the work complete. `evals/reconcile_calculation_inventory.py` reads the pinned official PDF contents and creates a machine-readable queue; the previous 1,120 parsed identity count was not an official calculation-work denominator. The ToC has 222 parent and 1,095 third-level section identities. Of those, 1,044 have an exact current draft row, 51 do not; 14 draft rows do not exactly match a ToC third-level identity. Parsed data has 1,120 identities, with 15 null/empty divisions, 9 ToC third-level identities absent from parse, 34 parse identities outside the ToC third-level set, and 204 section numbers repeated across divisions. Contents entries still need classification as calculation work, policy/reference, lookup, or other, and source page ranges need parent/continuation review. Therefore the authoritative calculation-work and rule denominators remain unresolved.

The queue now records source-rule mapping, existing-spec presence, calculator-family reuse candidate, representability, basic legacy execution state, all-condition validation, real generation, consultation, multi-item aggregation, and Excel separately for each of the 1,058 draft proxies. Current complete-condition calculation and real model-generation counts remain zero. The 382 legacy passes, 339 failures, and 337 unassessed rows are retained as basic observations only.

Focused local product evidence on the original `codex/single-trade-conditions` worktree (4b93836) covered one item only. That worktree did not contain PR #46. The prior observation that multi-item orchestration was missing was therefore branch-local and was incorrectly generalized to the whole project.

### 2026-10-18 integration correction: PR #46 and current main

The integration baseline is `origin/main` 168d80a426d5a348f666a9d2f03153b818e0fec7, which contains PR #46 implementation `a0fb3f2126e5aacff226df4c240c75d82bb7010b` and later main changes. The preserved original worktree remains at 4b93836. Automation changes were brought into a separate worktree through 3-way patch application and selected untracked automation assets were copied without collisions or wholesale file replacement.

On the integrated baseline, `evals/check_unified_estimate_chat.py` passed its offline production-path checks: two-item scope/session, pricing, aggregate, checkpoint restore, item-targeted edits, sibling preservation, and ordered multi-line XLSX. Thus multi-item estimate orchestration exists in the project and is now regression-verified against the local integrated candidate. API/UI/export behavior is verified only for this focused fixture, not across all standards or every product path. Per-item automation coverage, source-rule completeness, and inventory coverage remain the project-wide gaps. No multi-item implementation was added. Details are recorded in the validation and coverage reviews.

This is a branch-integration correction, not a new architecture. Source-page classification and common calculation failure repair remain open. The next external-model stage remains blocked pending new explicit shared budget approval; prior Gemini authorization and the $1.08 three-trial estimate are not new authorization. Keep independent inventory reconciliation and existing-calculator validation moving while approval is absent.


## 2026-10-18 integrated execution replay and shared unit fix

On the integrated main worktree, the existing legacy runner was inspected before replay. `evals/check_draft_executability.py` uses only `adjusted_daily_crew` and `per_unit`, builds synthetic spec-derived inputs (`_values`), tests at most 64 cartesian combinations, and labels an item basic executable when sampled outcomes stay in computed/blocked states and the first combination computes without a question. It is not a site-input replay or accuracy test. The original `data/drafts/executable.json` was preserved before output replacement.

The replay covered 1,058 draft proxies: 475 basic passes; 186 calculator execution/rule-gate failures; 52 format/citation preflight failures; 11 source-table-alignment preflight failures; 332 records without a compatible existing calculator; and 2 misfiled exclusions. Partition is exact. 661 unique items reached a calculator function. Of the legacy 339 failed entries, 94 now pass the basic check, 243 still fail, and 2 are `not_calculable` with no compatible calculator. Of 337 historically unassessed entries, 5 fail source-alignment preflight, 330 have no matching calculator (271 `not_calculable`, 55 `lookup_only`, 4 `rate`), and 2 are listed as misfiled. Of 382 legacy passes, 381 still pass and one fails current source-alignment preflight.

A reproduced common cause was denominator parsing in shared `per_unit.parse_basis`: the old reason group contained 173 entries. The shared parser now accepts an explicit unfamiliar denominator only as an opaque unit and permits identity conversion only when normalized input and table units match; incompatible units and numerator-only table units fail closed. This made 62 additional entries pass compared with the immediately preceding integrated replay, with no pass-to-fail regression in that comparison. In the full old unit-error group, 94 pass, 35 still fail parsing, and 44 proceed past parsing but fail a later condition. Null/non-string unit inputs also now return unresolved instead of raising `TypeError`. This does not resolve full source semantics or accuracy.

Current failure classes and source evidence remain open; see the versioned machine replay record. Recomputed draft validation found 957/1,058 entries with no format/citation error, 1 format issue, 100 entries with citation issues, and stale `meta.chunks_sha256` on all 1,058 against the current chunk file. That hash mismatch is a provenance warning; the basic runner's 475 passes are synthetic smoke results, not source-derived expected-value validation. Full note/reference rule verification remains zero.

## 2026-10-19 continuation verification

See `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §9 and `evals/runtime_validation/focused-continuation-2026-10-19.json` for the focused continuation evidence and file hashes. This continuation deliberately did not replay the full draft inventory and makes no current total claim. It verified the saved G1 quantity-unit path, lookup/formula runtime dispatch and promoted-spec consultation/pricing/API path, formula mixed-item aggregation/XLSX, price/equipment offline changes, and PDF-backed promoted cases. The 2-1-6 roller-count interpretation remains open; unresolved source policies remain held. The next calculation work remains source-backed expansion of remaining candidate rules and repair of failure clusters, while keeping source accuracy, basic execution, and integration coverage as separate states.

## 2026-10-19 targeted failure-cluster continuation

`evals/runtime_validation/incremental-unit-cluster-2026-10-19.json` pins the latest saved full-run artifacts, current 1,058-spec content manifest, and attributable status delta. A shared `ton`/`톤` unit alias fix moved exactly two of 48 ton-family per-unit candidates to basic pass; 46 statuses were unchanged. The reconciled proxy partition is 687 basic pass, 195 fail, 174 unsupported-calculator skips, and 2 inventory exclusions. Partial source-derived checks cover 84 sections / 181 cases, while all-rule verification remains zero and the authoritative rule denominator is unknown. Source-range and combined-adjustment decisions are enumerated without choosing policy in `docs/reviews/calculation-policy-review-list-2026-10-19.md`. Continue with distinct selector, basis, mixed-quantity, and source-cell failures; do not treat remaining `unresolvable` as one cause.

### 2026-10-19 continuation: dependent lookup choices and updated incremental status

The `lookup_only` calculator now derives dependent enum choices from source table axes before asking for the next value. `evals/check_lookup_dependent_domains.py` independently transcribed PDF p.573 and confirmed all eight 1-2-3 equipment/building cells, units, and citations; the existing lookup cell suite passed 36/36. The affected estimate-flow regression passed lookup/formula API conversion and pricing as well as mixed-item aggregation and XLSX export.

The 59-item lookup slice was traversed through the actual sequential questions instead of the legacy runner's full Cartesian product. Five false failures became reachable-path basic passes; 45 remain failed. Combined with the prior two ton-unit changes, the updated incremental basic partition is 692 pass / 190 fail / 174 unsupported / 2 excluded (1,058 proxies). Four newly passable lookup records remain out of the active executable gate pending full independent source-cell review; their execution delta is not a source-accuracy claim. One section/eight PDF cells were added, for partial evidence of 85 sections/189 cases; all-rule verification is still zero, source-rule denominator unknown.

Hash caveat: the preceding incremental record stored an aggregate spec hash without its recipe or component hashes, and the digest could not be reproduced. The new record documents a deterministic byte-level manifest recipe and digest. All current spec file write times predate the saved full-run report; the prior run remains an observed baseline with focused deltas, not a cryptographically confirmed identical spec snapshot. Keep policy items P1–P11 unresolved and continue the distinct source-table, denominator, and mixed-quantity failure clusters.


## 2026-10-19 incremental continuation after lookup source review

Current evidence and restart instructions are in `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §13 and `evals/runtime_validation/incremental-lookup-cluster-2026-10-19.json`. The former pending lookup promotion is resolved: five candidates were independently transcribed (122 cells across five additional source sections, with one blank source cell retained as unresolved) and promoted alongside two prior source-checked ton cases. Current status is an incremental 692/190/174/2 proxy partition, not a new full replay. Consultation, reference-only aggregation behavior and Excel visibility for lookup/formula are now focused-integration verified. The remaining 45 lookup failures split into 39 unresolved source table mappings and six citation/source-preflight cases; common 8-3-4 demonstrates table reconstruction/axis loss and remains failed. Continue source-backed candidate repair and formula gaps without weakening citation or source-cell checks. Keep the roller-count and open-rate/combination review list unresolved.

## 2026-10-19 checkpoint: table linking and estimate path

Follow-up evidence is in `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §14 and `evals/runtime_validation/incremental-lookup-cluster-2026-10-19-followup.json`. Three shared causes were addressed: merged source rows in 8-3-7, exact table selection by machine category in 8-4-9, and explicit machine-code-to-row-suffix resolution for 2104-0010. The 59-path lookup slice now reports 36 executable paths and 23 unresolved failures; root causes are 2 split axes, 18 absent axes, 2 ambiguous matches, and 1 missing declared intersection. 8-4-9's nine routes work but only p342-t0's 33 values were independently checked, so it remains outside the active gate pending source review of its other eight tables. The exact machine code rows in 2104-0010 (8 rows /32 values) and reconstructed 8-3-7 rows (2 rows /20 values) were source-checked and promoted.

The current source-reviewed incremental gate is 713 basic pass /169 failed /174 unsupported by the legacy runner /2 excluded; it derives from the saved full replay and attributable promotions, not a new full replay. Added PDF-backed evidence: 3 sections /85 value cells, yielding partial coverage of 111 sections /1,040 sampled cells; all-rule coverage remains zero and the complete source-rule denominator is unknown. The lookup/formula estimate path re-passed its affected integration: 146 API-output cases, 7 formula +35 lookup specs, and mixed-item aggregation/XLSX flows. Maintenance 2-1-6 roller count and unresolved rates/combined adjustments remain unselected in the policy review list.

### 2026-10-19 continued selector-cluster checkpoint

The current saved checkpoint in handoff §14 supersedes the 713/169 interim values above. The active incremental basic gate is 714 pass /168 failed /174 unsupported /2 excluded; no full replay was run. In the 59-path lookup slice, 37 execute and 22 remain unresolved. Source-backed exact category routing in 8-3-9 added four verified table routes (40 cells); 8-3-7, 2104-0010, and 8-3-9 are promoted after independent source checks. The 8-4-9 category routing works for all nine tables, but only p342-t0's 33 cells are independently checked; keep it outside the active gate pending eight table audits. Cumulative partial PDF evidence is 112 sections /1,080 sampled cells, with all-rule verification still zero. The affected estimate flow passes 146 API-output checks, 7 formula and 36 lookup specs, plus mixed estimate/XLSX scenarios. The current 22 failure clusters and exact hashes are in `evals/runtime_validation/incremental-lookup-cluster-2026-10-19-followup.json`.


### 2026-10-19 incremental exact-source table continuation

The saved current checkpoint is documented in handoff §15 and `evals/runtime_validation/incremental-lookup-cluster-2026-10-19-followup.json`. A generic exact table selector now handles one-to-many continuation matrices and exact source-row choices; branch-specific inputs use the existing `when` mechanism. Five PDF-backed groups (8-3-3, 8-3-5, 8-3-6, 8-3-10, 9010-0003) were restored or routed, independently checked across 1,946 source cells, preflighted, integrated, and promoted. The 59-path lookup slice is 44 basic passes / 15 failures; the incremental gate is 719/163/174/2, not a new full inventory replay. Partial source coverage is 117 sections / 3,026 cells; complete rule verification remains zero. Keep 8-3-1, the remaining eight 8-4-9 tables, and incomplete 5203-1800 matrices outside promotion until source values are independently checked. Continue the 15 failure clusters, while keeping roller count and rate/combined-adjustment questions unresolved.

## 2026-10-19 incremental source-repair status

The current resumable evidence is `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §16 and `evals/runtime_validation/incremental-lookup-cluster-2026-10-19-followup2.json`. The active gate is an incremental saved-run reconciliation: 741 basic executable / 141 failed / 174 unsupported by the legacy runner / 2 inventory exclusions across 1,058 proxies. It is not a fresh full replay, and full source-rule verification remains zero with the official rule denominator unknown.

Source-backed repairs completed four additional executable cases: 토목 1-6-1 and 기계설비 1-6-3 had omitted row labels; 공통 2-6-1 and 유지관리 1-2-11 lacked signed percentage-change/no-change declarations. Their exact source tables and relevant calculation paths passed focused checks. The mower source's 8%/7% conditional equipment rates are now represented and offline priced. The lookup slice reuses 57 results and reruns only two changed routes; it is 59 path passes / 0 failures. Other extraction cases remain unpromoted when the spec/calculator lacks required input contracts, including 기계설비 13-5-4; this is tracked as failed, not source-complete.

The 2-6-1 material-cost 5% note is not calculated because the shared price rule currently takes labor subtotal as its basis. Maintenance 2-1-6 roller count, open-ended rates, and combined adjustments remain unresolved in the policy-review list. Continue active failure clustering; no whole-inventory regression is required unless a shared runtime component changes.


### 2026-10-19 continuation checkpoint: source axes and table linkage

See `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §17 and `evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json`. Incremental active gate is 753/129/174/2; no full replay. Common source-axis repair in mechanical 8-1-3 restored three continuation tables (390 independently compared PDF cells; 195 exact runtime routes). Four citation failures also promoted after targeted source/calc checks. `per_unit` now supports a fail-closed exact source table route by input; only 8-1-3 uses it, and focused affected checks reran. Its `인/대` basis remains inferred/open. All-rule verification remains zero. Continue the 39-item table-link diagnosis and six remaining source-preflight failures, preserving 6-6-3's known source mismatch and the open roller/rate/combination policy list.


## 2026-10-19 incremental continuation: sparse cells and exact source axes

The latest active gate has **769 executable / 113 failed / 174 legacy-runner unsupported / 2 excluded** out of 1,058 entries (107 calculator/rule failures, 6 source preflight). This reconciles saved outcomes plus five focused promotions; no full inventory replay occurred. The active source-link analyzer now has 25 table-link candidates plus 8 separate diagnostics. These are not a complete failure or rule-coverage count. Full rule verification remains 0 and the official rule denominator is unknown.

Since the prior checkpoint, source-backed focused work repaired/promoted five items: sparse dash cells in 토목 7-2-4 수상고르기; resource-row selector, two dash exclusions and exact applicability block in 토목 7-2-3 육상투하; two-page exact diameter route in 기계설비 11-2-1; single-column resource table axes in 기계설비 7-2-4 씽크수전; and exact total-row selector in 토목 9-18-5. Independent original-PDF comparison adds 68 cells over five section items, with 100 calculated routes, 208 exact rate outputs, and four out-of-scope paths explicitly blocked across these focused audits. The previous 443-cell/9-item evidence was reused; current checkpoint-series cumulative evidence is 511 cells/14 items. Exact per-target results and hashes are recorded in the resume handoff and `evals/runtime_validation/incremental-table-root-cause-checkpoint-2026-10-19.json`.

Open policy items remain separate: Maintenance 2-1-6 roller count, open rates and combined adjustments; Mechanical 13-3-2 fixed lagging-sheet deductions/addition interaction and other unresolved source rates; and Mechanical 13-1-3 table-specific valve pressure ranges. Continue the remaining active failure groups; do not count a source route as full-rule verification or reuse the old 683/197/176/2 checkpoint as current.


## 2026-10-19 table-specific pressure domains

Mechanical 13-1-3 is no longer held under the earlier axis-diagnosis note. Its three valve tables have materially distinct pressure bands and diameter labels, now represented by conditional per-type input domains and exact table routes. The opt-in runtime `column_input_by_table` branch is declared by this one spec only; 32 cells and all three heading groups were checked against the original PDF, 170 diameter/pressure pairs and 16 quantity-3 paths produced 372 exact cited rates, and the focused per-unit suite passed 44/44. The active incremental partition is now 770 executable / 112 failed / 174 legacy-runner unsupported / 2 excluded; 24 table-link candidates and 8 separate diagnostics remain. Full rule verification remains 0. This result checks the direct quantity path; separate equipment charges and the remaining failure groups continue.
## 2026-10-19 incremental continuation: exact daily-crew columns

The restart detail is in `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §20. The current incremental partition is **774 executable / 108 failed / 174 unsupported / 2 excluded**; full-rule verification remains 0. The 6-2-3 common field assembly case was repaired by adding an opt-in, exact trade-to-column selector to the existing daily-crew runner, then naming its source output column. The branch is used by one spec, which failed before the change; no previously passing execution depends on this new branch. Original PDF p.190 (printed p.134) visually supports the seven work-type rows and 21 checked cells. Seven exact routes were verified; all 49 non-default combinations of three source-uncertain flags fail closed with citations. The independent cell-audit series increases from 18 sections/585 cells to 19/606. The separate 89 sections/303 broad source-derived cases have an unquantified overlap with cell audits; do not sum those scopes. Remaining table-link candidates: 22; other diagnostics: 6. Continue with exact-axis-zero-match failures and do not rerun this completed slice unless its spec or runner path changes.
## 2026-10-19 incremental continuation: exact coating axes

The restart record is `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §21. Current active partition is **775/107/174/2**; full-rule verification remains 0. The common/6-2-3 daily-crew issue and civil 6-3-3 coating-axis issue are now source-checked and indexed. The latter maps the exact coating header, preserves 14 source dash cells as `-`, and blocks the seven unsupported inside-coating diameter routes with citations; all 76 table cells and 38 routes were checked against original PDF p.424. This is a spec-only change using existing per-unit selection behavior. Independent source cell coverage is 20 sections/682 cells. Broad source-derived coverage remains 89 sections/303 cases and overlap is unknown. Remaining active analyzer queues are 22 table-link candidates and 5 other diagnostics. Continue with shared selector families and unresolved calculations; do not repeat the two completed slices without relevant code/spec changes.
## 2026-10-19 incremental continuation: transposed resource table

The restart evidence is in `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md` §22. Current active partition is **776/106/174/2**; full-rule verification remains 0. 토목/8-1-2 is source-checked across 56 unique cells and eight exact soil/BX-NX routes. It uses the existing compound column selector plus opt-in exact row-by-trade and resource-kind mappings; its source dashes remain explicit excluded resource citations. The 20m/5% adjustment and separate costs were proven to belong to adjacent 8-1-3 and were removed from 8-1-2 while preserving those 8-1-3 references and restoring its missing inclined-drilling note. The source audit series is 21 sections/738 unique cells; the distinct broad source-derived audit remains 89/303 with unknown overlap. Active table-link/other diagnostics: 21/5. Continue on 8-1-3 and other transposed tables without claiming whole-section verification.
## Incremental checkpoint: source-linked continuation tables

As of 2026-10-19, the saved incremental basic-execution partition is 777 executable / 105 failed / 174 unsupported / 2 excluded. The 692/190 baseline reconciles to 84 same-ID fail-to-executable transitions plus one normalized 3-2-2 ID crosswalk; this is not a full replay. Full-rule verification remains 0.

Civil 8-1-3 was repaired across its printed p.397-398 continuation: 70 distinct source cells, ten exact rock/hole routes, and 280 preflight combinations (80 computed; 200 policy-blocked). The depth-over-20m range, inclined drilling, and separate over-water costs remain unresolved as stated by the source. Runtime branch impact and focused regressions are in the resume handoff §23.

Coverage counts retain separate denominators: broad source-derived checks remain 89 sections / 303 cases; independent source-cell audits total 22 sections / 808 cells, including and superseding the earlier 17 / 555 cell checkpoint. Overlap between broad cases and cell audits is unknown, so do not sum these figures. The latest active failure analyzer identifies 20 table-link candidates and five other lookup diagnostics; continue shared failure causes and retain the source-policy review items without blocking unrelated work.
## Incremental checkpoint: sparse-cell recovery

Current incremental basic execution is 778 executable / 104 failed / 174 unsupported / 2 excluded, reconciled from 692/190 by 85 same-ID transitions and one normalized ID crosswalk. Mechanical 6-1-1 had eight source dashes omitted from the extraction; all 28 source cells, 14 item/size routes and 56 preflight combinations now match the printed page. The absent protection labor is explicitly cited and excluded; flowmeter rates remain available. This repaired one failure without modifying the runtime.

The failure-only table analyzer now has 19 candidates plus five other lookup diagnostics. Cell audits total 23 sections / 836 cells, including the prior 17/555 checkpoint. Broad source-derived evidence remains 89 sections / 303 cases; the overlap is unknown and these counts must stay separate. Full-rule verification remains zero; continue source-backed common-cause work and keep uncertain policies open.

## Incremental checkpoint: compound axes and resource columns

Current incremental partition is **782 executable / 100 failed / 174 unsupported / 2 excluded** from the saved index plus source-backed promotions; there was no whole-inventory replay. The saved 692/190 baseline reconciles to 89 exact-ID fail→executable changes plus one 3-2-2 identity crosswalk (net +90/-90). Broad source evidence remains 89 sections/303 cases, distinct from and not additive to the current 27-section/1,024-cell audit set; earlier 17/555 cells are included. Complete rule coverage remains 0.

Added three independently checked source routes: 3-3-9 exact parenthetical-rate selection (18 cells; four base combinations computed, 12 depth-policy cases blocked), maintenance 2-2-6 block-time/site compound columns (32 cells/16 routes), and maintenance 4-1-1 grouped pipe-type/resource columns (58 cells/29 routes/58 rates; three blank copper-size routes blocked). Added an opt-in `trade_in_columns` executioner branch used only by the previously failed 4-1-1 case. `check_per_unit.py` passed 44/44 and all affected focused selector audits passed after the change; no saved baseline pass used the new branch. The active failure-only table analyzer now has 16 table-link candidates plus four distinct table diagnostics. Resume with those clusters and remaining unsupported classes; keep policy questions, including maintenance 2-1-6, open.

## Current continuation checkpoint (2026-10-19)

The latest saved active index is **788/96/172/2**. Reconciliation from the durable 692/190 baseline shows 93 same-ID failure promotions and two unsupported promotions, plus one separately crosswalked 3-2-2 ID normalization. The intermediate 772/110/174/2 checkpoint has no saved ID manifest in the inspected evidence, so its transition set remains unverified. Source scopes remain broad 89 sections/303 cases and distinct audits 33 sections/1,214 cells (17/555 included; overlap unquantified). The 8-3-6 radiator and 1-5-6 water repairs remain source-backed with their range policy blocked. Mechanical 12-1-1 now routes its 14 exact row-dependent `대`/`면` units; all 42 unit/rate cells and 14 routes passed, including the live `면` quantity prompt. Mechanical 10-7-2 now uses its exact `면`/`개` item units; 12 source cells and four routes passed, with four omitted helper dashes restored and cited. Ditto labels in the 12-1-1 table remain linked through exact source-line signatures and original page visual; full note adjustments remain outside the focused audit. There are 15 table-link candidates and four other diagnostics; the root-cause groups, saved index/spec/runtime/validator hashes, and per-ID evidence are in `evals/runtime_validation/execution-id-and-evidence-scope-reconciliation-2026-10-19.json` and `evals/runtime_validation/active-table-link-root-causes-2026-10-19.json`. Full-rule verification remains zero; continue source-backed table routing and unsupported formula support without using this checkpoint as a stopping point.

Latest incremental continuation (2026-10-19): **790/94/172/2**, reconciled by ID against the durable 692/190 baseline as 95 failed→executable, two unsupported→executable, zero reversals, and one separately crosswalked 3-2-2 normalized ID. The user-reported 772/110 checkpoint remains ID-unverified. Source evidence scopes are broad 89/303 cases and independent 35/1,310 cells (17/555 included, overlap unknown; do not sum). Mechanical 12-2-1 passed exact original p.719 checks for 21 rows/42 unit and rate cells, 21 calculated routes, and live estimate flows for 개/조/면. Its source small-transport note was recorded; note adjustments and full-rule coverage remain unverified. Following the opt-in selector/citation runtime edits, focused per-unit regression passed 44/44 plus seven affected audit scripts; the 692 cached executable baseline IDs declare neither new branch. Active table-link queue is 15 candidates plus four other diagnostics. See the resume handoff and current reconciliation artifacts for remaining common-cause work; full-rule verification remains zero.


### Continuation checkpoint (2026-10-19, current index reconciliation)

The saved active index is 793/91/172/2. Durable 692/190/174/2 ID reconciliation shows 98 exact failed→executable moves, two unsupported→executable moves, zero reversals, and one separately crosswalked 3-2-2 ID; the reported 772/110 checkpoint has no ID manifest and cannot be reconciled by exact ID. Broad evidence remains 89/303 cases; independent audits are 38/1,770 cells including 17/555, with unknown overlap and nonadditive counts. Maintenance 2-2-6 passed 14 original cells and two live estimate flows. Active table queue is 13 candidates plus three diagnostics. This is a saved basic-execution index; historical outcomes outside focused current regressions are not full-rule verified. Continue shared failure groups and unsupported types; keep the 2-1-6 roller and unresolved rate/combination questions open. See handoff §29 and the current reconciliation/analyzer JSON artifacts.

### Continuation checkpoint (2026-10-19; current saved basic index)

Current partition is **802 executable / 84 failed / 170 unsupported / 2 excluded**. Exact reconciliation against saved 692/190/174/2 IDs gives 105 fail→executable, four unsupported→executable, no reversals, and one crosswalked 3-2-2 label. The 772/110 user checkpoint lacks an ID manifest and remains unverified at ID level. Broad source evidence remains 89 sections/303 cases; independent source-cell audits are 47 sections/2,894 cells, including 17/555. Scopes are not additive and overlap is unknown. Two focused sections currently report complete modeled-rule coverage; the authoritative inventory rule denominator is unknown.

Connected 13-7-22's cited 0.04kg/m³ note coefficient through an opt-in per-unit material route; focused audit and per-unit regression passed, with material pricing and a wage mapping still open. Repaired 8-4-2's exact four-stratum table routing and four activity rows with m/hour quantity inputs; 40 original cells and eight calculation routes were audited, while complete primary-matrix and price coverage remain open. Failure-only table analysis now has 11 candidates plus three other lookup diagnostics. Keep 2-1-6 roller count and unresolved rate/combination rules separate; proceed with other source-backed failure and unsupported groups without replaying unchanged inventory.

### Continuation checkpoint (2026-10-19; executor impact and active failure groups)

Saved basic partition: **803/83/170/2**. Exact reconciliation against 692/190/174/2: 106 failed→executable, four unsupported→executable, no reversals, plus one separately crosswalked 3-2-2 ID normalization (+111 net executable). The 772/110 checkpoint has no ID manifest. Broad coverage is 89 sections/303 cases; source-cell audits are 48/2,910, including prior 17/555 and 47/2,894. Scopes overlap by an unknown amount and are not additive. Runtime changes for explicit secondary quantity totals received focused 10-1-1 and 13-4-7 checks; per-unit regression 44/44 and cost-statement check 8/8 passed. Historical outcomes outside focused affected-route rechecks are not considered currently rule-verified. Two sections report all modeled rules covered; the authoritative rule denominator is unknown.

Refreshed failure-only analyzer reports 10 table-link candidates and three other lookup diagnostics. Remaining group counts: 36 calculator/rule gates, 28 unit/basis failures, six source preflights, plus table/axis/cell cases. Continue the exact-selector and source-extraction groups, then unsupported calculation types. Keep source ranges and 2-1-6 roller/rate/combination policies explicitly unresolved. See handoff §32 and the reconciliation and analyzer artifacts.

## Incremental checkpoint: source-row and per-unit restoration (2026-10-19)

Current saved basic index is 809 executable / 77 failed / 170 unsupported / 2 excluded, reconciled to saved 692/190/174/2 IDs through 112 exact fail→executable transitions, four unsupported promotions, no reversals, and a separate 3-2-2 ID crosswalk. This is not a whole-inventory replay. The 772/110 checkpoint has no ID manifest.

Four original-table repairs added independent cell and calculation audits: mechanical 13-8-5 (28 labor cells, 14 task/resource routes, source 10%); 13-5-1 (49 labor cells, 15 task routes, six quantity units, high-capacity references and a corrected Chain block row); 13-6-13 (21 rates plus 7% rule); and 13-6-16 (41 labor and five material cells with cited gas-cylinder basis). Offline prices are PARTIAL where catalogs lack exact rates; no aliases were inferred.

Cell-audit scope is now 53 sections/3,068 cells. Broad source-derived scope remains 89 sections/303 cases; overlap is unknown and the scopes are not additive. The two baseline-pass executor paths found by the feature scan (10-1-1 secondary quantities and 1-9-3 work-dependent units) were rechecked. `check_per_unit.py` passed 44/44. Failure-only analysis leaves six table-link candidates plus one diagnostic; all-rule inventory coverage remains zero. Continue source-backed common-cause repairs and unsupported calculations, preserving the unresolved range policies and maintenance 2-1-6 roller count/rates/combination.

### §34 incremental checkpoint — mechanical 9-2-1 source mapping (2026-10-19)

Basic execution is 820/66/170/2, reconciled by ID to the 692/190 baseline. Mechanical 9-2-1's extraction had merged-row alignment loss and omitted two original dash cells. The reconstructed source chunk and exact task/material-unit mapping were checked against the p.702 original; 14 numeric/dash cells, eight method/small-section calculations, and draft validation passed. Its labor-only 50% rule is scoped; source-dependent abrasive consumption changes and separate-cost notes remain open. Focused evidence is in `evals/runtime_validation/per-unit-9-2-1-source-audit-2026-10-19.json`. Cell-audit scope is 65/3,250, while broad source evidence remains 89/303 and is nonadditive. Failure-only analyzer reports 66 failures (37 executor/rule gate, 20 unit/basis, six source preflight, three range parses). No full-rule inventory validation is implied. Continue on independent failure and unsupported-calculator groups; preserve the 2-1-6 roller/rate/combination review item.

### §35 incremental checkpoint — mechanical 13-4-3 task units (2026-10-19)

Basic execution is 821/65/170/2, reconciled by ID against the 692/190 baseline. Mechanical 13-4-3 now selects among exact source tables by work type and asks for `매` on plate rolling versus `ton` for the other tasks. Original p.765–766 verification covered 116 numeric cells and 22 task/rate routes; 64 preflight combinations and a live quantity-unit consultation passed. Explicit special-material range (40–50%) and weld-length adjustment without a formula remain conditionally blocked. Runtime changes add per-table resource-axis/row selection, an explicit activity basis, and `매` parsing. `check_per_unit.py` passed 44/44; 31 executable per-unit specs with a `매` source unit received focused current preflight checks. The 9-2-1 audit was rerun after the runtime change. Cell audits now cover 66 sections/3,366 cells, separate from and nonadditive to broad 89/303 evidence. There are 65 failures remaining (37 executor/rule, 19 unit/basis, six source preflight, three source-range parses), 170 unsupported and two excluded; no all-rule completion claim is made. Continue on the preflight and independent failure groups, with the 2-1-6 policy review open.

### Current continuation checkpoint — 2026-10-19

Saved basic execution: **840 executable / 45 failed / 171 unsupported / 2 excluded**. New source-backed work connected the 9-5-2 40-point basis and exact distance factors, repaired the maintenance 2-4-3 rust-grid row shift from the visually checked source page, and routed 13-7-17/18 day, ㎡ and ton work bases separately through calculation and offline pricing. The p.744 13-2-2/3 rates remain blocked because the original provides ranges without a selection rule and an empty exact cell. Source-cell evidence is 75 sections/3,404 cells; broad source-derived evidence remains 89/303 cases, with unknown overlap. Full-rule verification remains zero; continue the remaining failure and unsupported groups and preserve unresolved maintenance 2-1-6 roller/rate/combination policies.

### §37 continuation — split quantities and exact resource deduction (2026-10-19)

Current saved basic partition is **863 executable / 22 failed / 171 unsupported / 2 excluded** (1,058 inventory IDs). Exact reconciliation against saved 692/190/174/2 IDs records 166 same-ID failure→executable transitions, four unsupported→executable transitions, no reversals, and one distinct 3-2-2 label crosswalk. This is an incrementally maintained execution index, not an inventory-wide rerun or full-rule claim.

Common quantity-root repair: common 6-7-2’s table is per piece and separates base+top from vertical body. The runtime model now routes the two user quantity inputs independently; original physical p.212 / printed p.156 was visually checked, 24 labor/equipment cells and four sizes were reconciled, four independent totals, citations, offline price and validator passed. 6-2-5 promotes only its source-defined D35 base and exact height rates; the >D35 5%-per-3mm cumulative rule remains blocked. Mechanical 13-3-2 now supports an exact-cited per-resource deduction for the isolated boiler/Blanket route; surcharge combinations with unspecified ordering remain blocked. The opt-in adjustment branch is used only by a baseline-failed spec; `check_adjustments.py` passed 20/20 after the runtime change.

Independent cell evidence is **78 sections / 3,440 cells**, including the accepted 17/555 checkpoint. Broad source evidence remains **89 sections / 303 cases**. Their overlap is unmeasured and counts must not be added. Refreshed failure-only analysis has 22 failures: 11 calculator/rule gates, eight unit/basis cases, and three table-cell range cases. All three current table-link candidates (civil 7-3-1/7-3-2 and mechanical 13-2-2) require explicit source policy; do not fuzzy-select their rates. Full-rule verification remains zero and the authoritative rule denominator remains unknown. Keep maintenance 2-1-6 roller count, rates and combination order in the separate review list. Continue on the remaining failure groups and unsupported calculations.

### §38 continuation — exact two-axis coefficients and condition-scoped rates (2026-10-19)

The refreshed saved basic partition is **865 executable / 20 failed / 171 unsupported / 2 excluded**. Exact reconciliation to the 692/190 baseline shows 168 same-ID failed→executable transitions, four unsupported→executable transitions, zero reversals, and one distinct 3-2-2 normalized-label crosswalk. The user’s earlier 772/110 checkpoint still has no ID manifest and cannot be reconstructed transition-by-transition.

Two more common causes were repaired. Civil 4-4-1 now resolves coefficient matrices with exact declared row and column inputs, then multiplies all five source resources; the original p.348 page and all 17 base/factor cells, 12 rail/type cases and 60 resource outputs were checked. Mechanical 13-7-13 now selects exact source-rate evidence when two separate conditions share a 15% value; seven thicknesses × five surface/scaffold scenarios (35 calculations) passed, while >9m is still blocked because the 5%-per-3m boundary rule is ambiguous. `check_per_unit.py` passed 44/44 and `check_adjustments.py` 20/20 after the shared executor changes.

Independent source-cell audits now cover **80 sections / 3,471 cells**; broad source evidence remains **89 sections / 303 cases**. These scopes overlap by an unknown amount and are not additive. Latest failure-only analysis shows 20 failures: nine execution/rule gates, eight unit/basis cases, and three range-policy table cases. The remaining table candidates are 7-3-1, 7-3-2 and 13-2-2; their numeric ranges still lack a source selection rule. Full-rule verification remains zero. Keep 2-1-6 roller count/rate/combination and other source-policy questions separate while working remaining executable routes and unsupported calculation types. See the current reconciliation and active-table root-cause artifacts for hashes and exact ID evidence.
