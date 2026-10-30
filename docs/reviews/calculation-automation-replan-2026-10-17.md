# 품셈 계산 자동화 재기획

작성: Sol / 2026-10-17. 현재 코드, 기존 미구현 감사, Gemini 실호출 후보를 직접 재검토했다. 이번 작업은 조사·기획이며 모델 추가 호출이나 제품 구현·배포를 하지 않았다.

## 1. 목표와 결론

목표는 원문에 계산 근거가 있고 현장 입력이 갖춰진 견적이 소프트웨어 미지원으로 중단되지 않게 하는 것이다. 공종별 계산법은 필요하지만, 사람이 공종마다 새 계산기를 작성하는 작업을 자동화한다.

추천: 품셈을 사전에 읽는 LLM이 **공종별 실행 가능한 계산 모듈과 입력 정의·근거를 생성하고, 격리된 시험에서 오류를 고친 뒤 등록**한다. 상담 시에는 등록된 모듈에 현장 입력을 넣어 실행한다. 검증을 최종 목적이 아닌 자동 수정 과정의 피드백으로 사용한다.

기존 두 계산기는 정상 공종에 유지한다. 기존 틀로 표현할 수 없는 공종에는 공통 인터페이스를 따르는 생성 모듈 경로를 추가한다. Python 기반 프로젝트에 맞춰 작은 순수 계산 함수로 시작하며 별도의 대규모 수식 언어 또는 워크플로 플랫폼을 먼저 도입하지 않는다.

원문에 결정되지 않은 기준은 코드 생성 능력과 다른 문제다. 관련 공통기준·정오표·공식 설명을 찾아 먼저 해결한다. 그래도 정해지지 않는 기준은 근거와 선택 주체를 기록한 산정 정책으로 관리한다. 사용자에게 소프트웨어 오류나 임의의 수학 선택을 떠넘기지 않는다. 확정되지 않은 가정을 품셈의 확정 규칙처럼 제시하지 않는다.

## 2. 현재 병목을 확인한 근거

| 파일 | 확인한 사실 | 영향 |
|---|---|---|
| backend/agent/nodes/compute.py | 계산기 등록은 adjusted_daily_crew, per_unit 두 가지 | 새로운 산식을 문자열로 써도 실행되지 않음 |
| backend/agent/tools/calc/daily_crew.py | 기준 시공량×계수표를 중심으로 계산. blocked_if는 단일 입력 비교 | 복합 조건과 임의 시공량 보정을 그대로 담기 어려움 |
| backend/agent/tools/calc/adjustments.py | 범위 비율, 반복/누적 문구는 계산 전 차단. 주된 보정 대상은 인력·장비 품 | 하루 시공량 감소와 단위당 품 감소를 같은 보정으로 다룰 수 없음 |
| docs/SPEC_FORMAT.md | 모델이 여기 없는 필드를 만들지 말라고 지시 | 모델의 자유로운 계산식 생성이 기존 형식에 제한됨 |
| pipeline/draft_specs.py | 미지원 계산형은 params를 비우고, 해석이 불명확하면 blocked로 옮기도록 지시 | 실행 범위 확장 대신 보류 후보가 누적됨 |
| pipeline/refine_spec_rules.py | 기존 SPEC_FORMAT과 draft 구조를 재사용 | 정제해도 계산기 표현 범위는 그대로임 |
| evals/check_draft_executability.py | 기본 계산 외 조건에서 blocked도 허용하는 경로 존재 | executable 목록이 모든 조건의 계산 완료를 뜻하지 않음 |

최근 Gemini 후보는 높이 보정 설명에 양중장비 미사용·최대 9%를 추가했으나 blocked_if를 삭제했다. 현재 check_blocked는 이 필드가 없으면 건너뛰므로, 설명상 보류가 실행상 보류로 이어지지 않는다. 이는 후보가 원문 해석과 실행 형식을 동시에 완성하지 못했다는 직접적인 증거다.

기존 감사의 22조건/20공종/6유형은 명시적으로 구현 부족을 밝힌 부분 집합이다. 전체 미지원 개수로 확대 해석하지 않는다. 모든 제외·미산정 항목을 같은 분모로 합치지 않는다.

## 3. 조사한 대안과 선택

| 대안 | 장점 | 이 프로젝트에서의 판단 |
|---|---|---|
| 기존 JSON 형식만 정제 | 변경이 작고 기존 계산기 재사용 | 현재 표현 범위를 넘어가지 못하므로 단독 해법으로 부족 |
| 별도 수식 언어·규칙 엔진 구축 | 조건·수식·추적을 일관되게 처리 | 유용하지만 새 언어·호환성 개발이 선행돼 범위가 커짐 |
| 사전에 LLM이 계산 모듈 생성·시험·수정 | Python 조건문·수식으로 다양한 규칙 표현, 기존 코드·검사 활용 | 추천. 공통 입력·출력·산술·출처 규약을 강제 |
| 견적 요청마다 LLM이 코드 생성 | 미등록 요청에 유연 | 비용·지연·결과 변동과 실행 검토가 요청마다 발생. 주 운영 경로로 채택하지 않음 |

OpenFisca는 규칙을 변수·파라미터·Python 수식으로 표현하고 입력/기대 출력 및 경계값으로 시험한다. 이는 공종마다 달라도 공통 실행 구조 아래 계산법을 둘 수 있다는 참고다. OpenFisca 자체를 도입하거나 해당 프로젝트가 LLM 생성 방식을 쓴다고 주장하는 것은 아니다.

Camunda는 DMN/FEEL로 조건과 동적 표현식을 실행한다. 규칙을 실행 가능한 형태로 저장하는 다른 실무 방식이다. Anthropic은 코드 실행과 평가 피드백을 활용하는 에이전트 패턴을 설명한다. 이들을 결합한 본 설계는 CivilAI에 대한 설계 제안이며, 건설 품셈 전체에서 이미 검증된 제품을 그대로 적용하는 것은 아니다.

## 4. 사전 규칙 작성 과정

1. **원문 묶음:** 해당 절 전체 PDF·파싱 표·비고·참조 공통기준·정오표를 수집한다. PDF 실제 페이지와 인쇄 쪽을 모두 보존한다. MD는 보조 자료다.
2. **근거 정리:** 표의 수치, 적용 조건, 예외, 보정 대상, 산정 순서, 단위, 미확정 사항을 추출한다. 각 규칙에 원문 위치와 인용을 연결한다.
3. **모듈 생성:** Gemini가 계산 함수와 필요한 현장 입력 정의를 만든다. 표 조회·단위 변환·정확한 산술·반올림·결과 작성은 공통 라이브러리를 호출한다. 특수 조건과 수식은 함수 안에서 표현한다.
4. **시험:** 승인된 기준 예제, 원문 대조, 단위·경계값·예외·무관 항목 보존을 검사한다. LLM이 만든 테스트만으로 정답을 판정하지 않는다.
5. **자동 수정:** 문법 오류·필드 누락·예제 불일치를 LLM에 돌려주고 수정한다. 초기에는 최대 3회와 별도 비용 상한을 둔다. 반복 실패는 원인별 개발 항목으로 회수한다. 임의로 blocked를 추가해 시험을 통과시키지 못하게 한다.
6. **등록:** 시험과 의미 검토를 통과한 모듈의 버전·원문 해시·모델·프롬프트·검사 결과를 저장한다. 상담 서버는 등록된 버전만 호출한다.

모든 공종을 하나의 거대한 함수로 만들지 않는다. 작업 단위 모듈이 공통 계산 기능을 공유하도록 구성한다. 동일한 산식이 반복되면 재사용 함수로 묶는다.

## 5. 실행 계약과 안전한 작성 환경

입력은 현장 사실, 확인된 산정 정책, 단가를 구분한다. 출력은 필요한 질문 또는 계산 결과이며, 계산 결과에는 물량·품량·적용 보정·단위·산식·출처·제외 범위가 포함된다. 프로그램 기능 부족은 사용자 답변으로 처리하지 않고 사전 작성 과정에서 해결한다.

생성 코드는 즉시 서버에서 실행하지 않는다. 자격증명·네트워크·운영 파일이 없는 격리된 시험 환경에서 시간과 자원을 제한하고, 금지된 I/O·동적 실행·임의 import를 검사한다. 구문 검사만으로 격리를 대신하지 않는다. 검토·버전 고정 후 정상 애플리케이션 코드로 등록한다.

정확한 산술은 기존 Fraction 기반 기능을 재사용한다. float 오차나 공종별 임의 반올림을 만들지 않는다. 각 중간값의 단위를 유지해 하루 시공량과 총물량을 혼동하지 않도록 한다. 적용 순서와 중복 보정도 명시한다.

단일·복수 공종은 같은 결과 인터페이스를 사용한다. 공종 모듈은 항목별 직접비 산출에 필요한 품량 등을 반환하며, 공통 간접비·전체 합계는 기존 집계 계층에서 한 번 적용한다. 화면·엑셀·새로고침 복원은 동일 결과 및 규칙 버전을 참조한다.

## 6. 사용자 상담 흐름

사용자가 “거푸집 100㎡ 견적”을 묻는다. 상담은 규격·높이·시공 방식 등 계산에 필요한 현장 사실만 묻는다. 입력이 갖춰지면 등록된 계산 함수가 결과를 반환한다. 조건이 바뀌면 해당 항목과 전체 집계를 갱신한다.

예: 표에서 하루 기준 시공량 30㎡를 선택했고, 경사 20도 미만의 지붕 슬래브로 확인됐으며 다른 보정은 없다는 설명용 조건에서는 17% 감산 후 24.9㎡/일, 작업일수 100/24.9일을 계산한다. 100㎡라는 총물량은 변하지 않는다. 이는 품량 계산 예시이며 전체 금액·장비·자재 포함 견적을 검증한 값은 아니다.

높이 보정은 별도의 경로다. 높이와 양중장비 사용 여부로 적용 여부를 판단하고, 적용률·구간 계산에 필요한 근거를 사전에 확정한다. 원문만으로 확정되지 않은 누적·잔여 방식을 임의로 floor/ceil 또는 단리/복리로 선택하지 않는다. 현장 재량인 수치는 근거를 보여주며 담당자가 확인하도록 한다. 일반 사용자에게 “단리/복리 중 고르세요”라고 질문하는 UX는 채택하지 않는다.

크레인 사용에 따른 시공량 비감산과 크레인 비용 산정은 별개다. 장비 규격·단가가 필요한데 없으면 이를 확인하며, 비감산이라고 장비 비용을 누락하지 않는다.

## 7. 실행 순서와 완료 기준

### 1차: 서로 다른 3유형을 실제 흐름까지 연결

- 확정 비율 시공량 보정: 거푸집 지붕 슬래브 17% 사례.
- 산술 보정: 강재거더 일당 가설 개수 증감 사례. 정확한 조건은 원문 재검증 후 기준 예제로 고정.
- 복합 조건·현장 선택: 거푸집 높이 및 장비 사용 사례. 산정 정책의 미확정은 별도 추적.

산출물: 공통 계산 모듈 인터페이스, 생성·시험·수정 파이프라인, 3유형의 실행 가능한 모듈, 상담 입력 연결, 근거와 산정 결과. 현재 refine_spec_rules의 PDF 준비·원시 응답·해시·차이 저장은 재사용한다. 기존 형식만 고치는 프롬프트와 특정 9% 문구에 의존하는 판정은 주된 검증 수단에서 제외한다.

1차 완료는 문법/JSON 통과가 아니다. 기준 예제와 경계값을 통과하고, 사용자 답변 후 계산→화면→엑셀까지 이어져야 한다. 복수 공종 중 한 항목 수정 시 다른 항목을 보존하고 공통비를 중복 적용하지 않아야 한다. 입력이 충분하고 산정 근거가 확정된 사례에서 소프트웨어 미지원으로 중단되는 건수는 0이어야 한다.

### 2차: 확인된 22조건을 원문 기준으로 재분류하고 변환

6개 유형의 모든 조건을 원문과 대조한다. 각 조건을 실행 완료, 필요한 현장 입력을 받으면 실행, 추가 근거 결정 필요로 추적한다. 세 상태를 하나의 성공률로 합쳐 완료했다고 하지 않는다. 계산 대상 밖인 자재·별도 작업 제외는 별도 범위로 표시한다.

### 3차: 전체 카탈로그 확대

현재 실행 목록 외 항목은 표 연결 오류, 단위/형식 오류, 산식 누락, 실제 자료 부족으로 구분해 자동 수정 과정을 적용한다. 전수 재생성부터 시작하지 않는다. 예비 3유형에서 확인한 수정 비용·자동 완료율을 보고 배치 크기와 비용을 정한다.

## 8. 모델과 평가

첫 구현은 기존 Gemini API를 사용하되 실제 사용 가능한 모델과 가격을 실행 전에 확인한다. Sol은 근거·기준 예제·최종 변경을 검토하고 Luna는 구현·오프라인 검사를 담당한다. 대규모 모델 교체나 추가 구독을 선행 조건으로 삼지 않는다.

지난 1회는 정답 조건을 프롬프트로 알려준 guided 시험이므로 독립 추출 성능의 근거가 아니다. 후속 평가에서는 규칙 정답을 지시문에서 제거하고 공통 형식·원문·개발 규약만 제공한다. 고정된 독립 기준 예제로 첫 생성 성공률, 수정 후 계산 완료율, 의미 오류, 필요한 질문의 정확성, 비용을 측정한다. 모델이 작성한 코드와 같은 모델이 작성한 기대값만 일치하는 시험을 정답 근거로 삼지 않는다.

모든 원문이 단일한 금액을 정의한다는 보장은 없다. 이 한계와 소프트웨어가 표현하지 못하는 문제를 분리한다. 지원 범위 안의 확정된 계산법은 구현으로 해결하고, 근거 부족은 공식 자료/담당자 결정으로 해소한다.

## 참고한 1차 자료

- OpenFisca, Coding a formula: https://openfisca.org/doc/coding-the-legislation/10_basic_example.html
- OpenFisca, Writing YAML tests: https://openfisca.org/doc/coding-the-legislation/writing_yaml_tests.html
- Camunda, Expressions: https://docs.camunda.io/docs/components/concepts/expressions/
- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Code execution with MCP: https://www.anthropic.com/engineering/code-execution-with-mcp
- PAL 연구: https://proceedings.mlr.press/v202/gao23f.html

위 자료는 설계 패턴의 근거다. CivilAI 품셈 해석·정확도·자동완료율을 보증하는 외부 평가가 아니다.



## 9. Follow-up implementation record (2026-10-17)

- The 2026 Standard Construction Estimate note was checked against public CAK/CODIL excerpts. The location is common section 6-3-1, PDF page 193 (printed page 137). Continuous crane use means adding the equipment to the crew without reducing output. The no-lifting-equipment height condition is separate. Roof slab slope under 20 degrees has its own 17% daily-output reduction.
- The official note says "up to 9% every 3 m" above 7 m without defining a partial-interval rule, an exact rate, or the accumulation method. For automatic estimates the module assumes each started 3 m interval counts, uses the stated maximum rate of 9% successively (`daily output × 0.91^intervals`), then applies the independent 0.83 roof factor. These are system assumptions, not an official formula. Successive application preserves positive output beyond 40 m without an arbitrary cap or minimum.
- Removed user inputs for total height deduction, interval count, accumulation method, and deduction source document. The user supplies field facts such as height and lifting equipment use.
- The calculation trace and workbook keep the unchanged table cell, daily-output adjustments, work days, and adjustment source separate. Focused test results are in the task completion report.
