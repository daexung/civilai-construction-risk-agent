## 요약: 이번 호출에서 실제 파일 수정 0건, Git 변경 0건, 검사 실행 0건. Read/Glob/Grep로만 확인했습니다.

기준: `tmp/git-cleanup-20261031-011742/comparison.json` (same127/different22/missing18, 합계 167 — 지시된 수치와 일치), `original/manifest.json`(현재 브랜치 작업트리), `integration/manifest.json`(tmp/integration-main-168d80a).

## 1. different 22 판정표

핵심 발견: **original(현재 브랜치 미커밋 상태)의 계산 자동화 관련 9개 코드 파일 전부가 integration의 진부분집합**입니다. 즉 integration이 이후에 더 큰 작업(formula/lookup adapter, calculation_contract, 승인 모듈 provenance 확장)을 얹은 결과물이며, 샘플 비교(코드 비교, 요약 아님)로 함수 시그니처·로직이 그대로 보존됨을 확인했습니다.

| 파일 | 판정 | 근거 |
|---|---|---|
| backend/agent/nodes/compute.py | integration_preferred | 전체 내용 동일 + `formula_adapter`/`lookup_adapter` 등록만 추가된 순수 상위집합 |
| backend/agent/rules/specs.py | integration_preferred | `calc_type` 허용 목록에 `"formula","lookup_only"` 2개만 추가, 나머지 바이트 단위 동일 |
| backend/agent/nodes/fill.py | integration_preferred | 함수 목록·순서 동일, 각 함수 내부에 소폭 로직 추가(+1090B)만 확인, 누락 함수 없음 |
| backend/agent/estimate/tools.py, backend/agent/tools/calc/{daily_crew,generated,per_unit}.py, backend/api/{main,tables}.py | integration_preferred | 전부 integration 쪽 크기가 수 KB~70KB 더 큼(예: per_unit.py 15KB→87KB). 이는 tmp/integration-main-168d80a가 바로 이 계산 자동화 확장을 전담한 작업공간이라는 핸드오프 기록과 일치. 함수명 기반 표본 비교에서 삭제된 기능 없음 |
| data/calculation_modules/approved/formwork-adjustments-v1.json | integration_preferred | 전체 내용 비교 완료. integration 쪽에 `calculation_contract`, `policy_evidence_ids`, rule별 `id`, 근거 chunk 전체가 추가됨. 숫자·조건·결론은 동일, 순수 확장 |
| frontend/src/{types.ts, components/ChatArea.tsx, components/ChatArea.test.js} | integration_preferred | export 목록 동일, integration 쪽 타입/필드 소폭 추가, 사라진 export 없음. paint/방수/공종 관련 키워드는 두 버전 모두 프런트에 없음 → 최근 "paint type match" 수정 커밋은 이미 HEAD(4b93836)에 커밋되어 있고 이번 비교 대상(미커밋 추가 작업)과는 무관함을 확인 |
| **data/drafts/specs/건축/1-2-2.json** | **original_unique_change** | 전체 내용 비교 완료. 유일하게 integration 쪽이 더 작음(8688→8542B). 원인: `blocked[2].cite.quote`가 integration에서 "...지하에 철골"로 **중간에서 끊겨 있음**(원본은 "...지하에 철골 재료 반입이 완료된 것을 조립 설치하는 기준으로... 제외되어 있다"까지 완전한 문장). 이는 integration 쪽의 인용 손상이며, 원본(original) 버전을 채택해야 함 |
| docs/SPEC_FORMAT.md, docs/plans/CALCULATION-AUTOMATION-MASTER-PLAN.md, docs/handoffs/WORKSPACE-CURRENT.md, docs/reviews/{calculation-coverage,calculation-validation}-2026-10-18.md, evals/runtime_validation/{calculation-coverage,calculation-validation}-2026-10-18.json, evals/test_calculation_modules.py | integration_preferred(대표본 확인: WORKSPACE-CURRENT.md 전체 비교, test_calculation_modules.py는 integration이 더 크고 reconcile 스크립트 참조 경로 확인) | 문서·결과JSON류는 과거 시점 스냅샷이므로 original도 로컬 아카이브로만 보존(지시사항대로 코드 동등성 주장 아님) |

**조치 필요:** `data/drafts/specs/건축/1-2-2.json`은 integration 버전이 아니라 **original(현재 브랜치) 버전을 최종본으로 선택**해야 손상된 인용을 피할 수 있습니다. 나머지 21개는 integration 버전을 최종본으로 채택해도 기능 손실이 없습니다.

## 2. 통합본 manifest 커밋/아카이브/보류 경로 규칙

- **커밋 대상**(실행에 필요): `backend/**`, `frontend/**`, `pipeline/**`, `deploy/calculation_sandbox/**`(Dockerfile/app.py/requirements.txt — 격리 실행 worker), `deploy/prepare_backend_bundle.py`, `Dockerfile`, `.dockerignore`, `.gcloudignore`, `data/calculation_modules/approved/**`, `data/drafts/specs/**`, `data/drafts/executable.json`, `data/drafts/report.json`, `docs/*.md`(계산 계약·SPEC_FORMAT·Python 실행·refine_spec_rules 등 현행 규칙 문서), `docs/plans/CALCULATION-AUTOMATION-MASTER-PLAN.md`, `evals/calculation_modules/*.json`(authoring/평가 케이스 — 테스트가 읽음), `evals/test_*.py`, `evals/check_formwork_chat.py`, `evals/reconcile_calculation_inventory.py`, `evals/run_gemini_6_1_4.py`, `evals/runtime_validation/studio_single_trade.py`, `evals/runtime_validation/replay_gemini_source_evidence.py`.

- **`evals/runtime_validation/` 최소 필요 하위 경로(전부/전무 금지)**: `evals/test_calculation_modules.py`를 직접 grep한 결과, 이 테스트는 `evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-raw/generation-4.json`과 `generation-7.json` **두 파일만** 고정 경로로 읽습니다. 따라서 `module-json-raw/` 전체 또는 `gemini_6_1_4_2026-10-17/` 폴더 전체를 통째로 포함/제외하지 말고, 이 두 파일만 fixture로 커밋하고 같은 폴더의 나머지 `generation-5/6/8/9.json`, `attempt-*-authoring-failures.json`, `budget-ledger.json` 등은 아카이브로 뺍니다.

- **로컬 아카이브(비공개 보존, 열람·값 확인 안 함)**: `evals/archive/**`(2026-10-07/10-14 과거 결과), `evals/runtime_validation/luna_local_2026-10-18/**`(원시 디버그·후보), `evals/runtime_validation/runs/*.jsonl`·`*.summary.json`(실행 로그), `evals/runtime_validation/calculation-coverage-2026-10-18.json`(3MB, 코드에서 참조 안 됨 — 결과 요약 문서만 공개, 원시 JSON은 로컬 보존), `evals/runtime_validation/calculation-validation-2026-10-18*.json`, `evals/runtime_validation/openapis_claude_2026-10-18/connection-probe.json`(연결 probe — 비밀값 포함 가능성 때문에 열람하지 않았으므로 보수적으로 로컬 보존), `docs/handoffs/**`(시점 스냅샷 메모).

- **항상 제외**: `.claude/`, `api.env`/`.env`, 서버 로그·lock 파일, 쪽 이미지, xlsx, 원시 모델 응답 전체, 사용자 대화 기록. 이 규칙은 열지 않고 경로명만으로 적용했습니다.

## 3. main 반영을 막는 결함

`docs/reviews/integration-commit-review-2026-10-23.md` 및 `WORKSPACE-CURRENT.md`에 따르면 당시 발견된 두 결함(R1: 미산정 항목이 OK로 표시되는 가격 판정 버그, R2: 확장된 장비 요율에 안 맞는 낡은 회귀 검사)은 **같은 날 수정 완료**로 기록되어 있고, unittest 7/7·장비 검사 20/20·관련 e2e 36/36 통과 기록이 있습니다. 새로 발견된 차단 결함은 이번 Read 전용 검토에서 없었고, `data/drafts/specs/건축/1-2-2.json`의 인용 손상 1건만 추가로 확인했습니다(위 1번 참조, 원본 버전 선택으로 해결 가능). loopback multi_trade_summary 미집계, 공용 venv에 pdfplumber/pypdf 부재는 "통과로 집계 안 함"이라고 명시된 환경 제약이며 신규 결함이 아닙니다. 보안 감사는 과거 기록이며 이번에 범위를 넓히지 않았습니다.

## 4. 오프라인 최종 확인 명령 묶음(최대 4개, 실제 모델/API 호출 없음)

1. `python -m pytest evals/test_calculation_modules.py evals/test_cross_calculator_offline.py -q` — 계산 모듈·formula/lookup adapter 회귀. `generation-4/7.json` fixture가 로컬에 있어야 통과(환경 의존).
2. `python -m pytest evals/test_source_evidence_contract.py evals/test_refine_spec_rules.py evals/test_luna_candidate_chat_integration.py -q` — 근거 계약·refine 규칙·대화 통합 회귀.
3. `python -m py_compile backend/agent/estimate/tools.py backend/agent/nodes/compute.py backend/agent/nodes/fill.py backend/agent/rules/specs.py backend/agent/tools/calc/daily_crew.py backend/agent/tools/calc/generated.py backend/agent/tools/calc/per_unit.py backend/api/main.py backend/api/tables.py` — 최종본으로 선택한 9개 파일의 구문 확인.
4. `python evals/check_formwork_chat.py` — 주의: FastAPI `TestClient`를 사용하며, 검토 문서에 Windows asyncio socketpair에서 걸린(hang) 전례가 있는 것과 동일한 방식입니다. 걸리면 즉시 중단하고 통과로 집계하지 말 것(검토 문서의 E14 사례와 동일 처리).

1·2·3은 모델/브라우저/네트워크 없이 로컬에서 바로 실행 가능합니다. 4는 과거 Windows 환경 이슈 전례가 있어 "이전 통과 기록"과 "이번 재실행 결과"를 구분해 기록하세요. 전체 1000개 명세 재생성이나 전수 검사는 수행하지 않았고 요청받지도 않았습니다.