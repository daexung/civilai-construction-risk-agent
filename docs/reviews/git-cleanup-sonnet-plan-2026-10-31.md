# 최종 검토 메모

Sonnet 원문 보고서의 폴더 차이 집계는 부정확하다. 실제 comparison.json 기준은 동일 127개, 다름 22개, 통합본에 없음 18개다. 합계는 비교 가능한 파일 167개이며 민감 경로 1개는 비교에서 제외했다. 원문 아래의 129개/16개 및 이를 전제로 한 표현을 사용하지 않는다. 아래 수량·분류 중 과거 문서 인용은 현재 실측과 구분한다. 실행은 성공했고 기록된 API 환산 비용은 $0.3048698, 11턴이다. 이 값은 구독의 실제 차감액이 아니다. 삭제·staging 변경·커밋은 하지 않았다.

---

# Git 정리 준비 검토 보고서

## 작업 범위 및 확인 사항

이번 검토는 읽기 전용이며, **실제 변경·삭제·staging·커밋은 0건**이다. 어떤 파일도 수정하거나 지우지 않았고, git add/commit/push도 수행하지 않았다.

보존 자료 폴더는 `tmp/git-cleanup-20261031-011742`이며, `original/`(브랜치 `codex/single-trade-conditions`, HEAD `4b93836`)과 `integration/`(브랜치 `codex/calculation-integration-20261023`, HEAD `168d80a`) 두 작업 폴더의 변경·미추적 파일을 각각 백업했다.

## 백업 범위와 백업되지 않은 범위

- **original**: 추적 변경 22개 + 미추적 146개 = 168개 대상 중 167개가 `copied_verified`(SHA-256 재확인 완료)이고, 1개(`.claude/launch.json`)는 `sensitive_kept_in_place`로 **복사되지 않고 원래 위치에만 남아 있다**.
- **integration**: 추적 변경 416개 + 미추적 1,316개 = 1,732개 대상 중 1,731개가 `copied_verified`, 1개(사용자 흐름 검증용 `api.env` 추정)가 `sensitive_kept_in_place`로 복사되지 않았다.
- 변경되지 않은 파일, Git 내부 객체, 무시된 환경 파일, 대용량 원문 자료는 이 스냅샷에 아예 포함되지 않았으므로, **"전부 백업됐다"고 볼 수 없다.** 원래 체크아웃 폴더가 여전히 1차 보관처다.
- `staged.patch`/`unstaged.patch`는 비공개 보존 파일이라 이번 검토에서는 열지 않았다.

## 두 작업 폴더의 차이 요약

원본(single-trade-conditions)과 통합본(calculation-integration-20261023)은 같은 시점에서 출발하지 않았고, 통합본 쪽 변경 범위가 훨씬 크다(추적 변경 22개 대 416개). 공통으로 존재하는 168개 경로 중:

- **동일(same)**: 약 129개
- **다름(different, 내용 비교 필요)**: 22개
- **통합본에 없음(missing_in_integration)**: 16개 — 원본에만 있는 자료

즉 공통 파일의 약 13%가 서로 다른 내용을 담고 있어, 둘 중 하나를 자동으로 "최신"이라 단정할 수 없다. 통합본은 원본보다 넓은 범위(backend/agent/estimate/aggregate.py, dialogue.py, nodes/compose.py 등)를 추가로 포함하고 있어 별도 설계·구현 결과로 보인다.

## 분류와 대략 수량

인계 문서(`WORKSPACE-CURRENT.md`)의 경로 기반 분류(통합본 기준, 총 약 1,725개)는 다음과 같다. 이는 코드 승인·삭제 판정이 아니라 경로 기준 분류다.

| 분류 | 경로 수 | 내용 |
|---|---:|---|
| 제품·파이프라인 (코드) | 44 | 상담, 계산기, 가격, API, UI, 배포 설정, 명세 생성기 |
| 명세·등록·요율·실행 인덱스 | 382 | 실행 코드와 함께 검토 필요, 통과 자체가 정확성을 뜻하지 않음 |
| 기타 별도 검토 필요 | 15 | 쪽 이미지, 원문 추출물, 재생성 가능성 미확인 자료 |
| 핵심 문서 | 18 | 계획·인계·검토 문서 |
| 검사·fixture (필수 검사) | 490 | 반복 실행에 필요한 테스트 소스·입력 |
| 평가 증거·실행 증거 | 776 | 과거 원시 응답, 실패 기록, 원문 대조, 해시 — 임시 파일 아님, 일괄 삭제 금지 |

## 원본에만 있는 자료 (missing_in_integration, 16개)

- `docs/handoffs/UNIFIED-ESTIMATE-RESUME-2026-10-16.md`
- `docs/reviews/codex-credit-usage-audit-2026-10-16.md`
- `docs/reviews/codex-credit-usage-followup-2026-10-16.md`
- `docs/reviews/follow-up-answer-quality-2026-10-17.md`
- `docs/reviews/public-estimate-comparison-2026-10-15.md`
- `docs/reviews/refine-spec-rules-live-trial-2026-10-17.md`
- `evals/archive/2026-10-07-worktree-results/` 하위 8개 파일(README, manifest, 평가 결과 JSON 등)
- `evals/archive/2026-10-14-planning-before-dashboard-merge/` 하위 2개 문서

전체 목록은 `tmp/git-cleanup-20261031-011742/comparison.json`의 `state: "missing_in_integration"` 항목에서 확인 가능하다.

## 내용이 서로 다른 핵심 제품 코드(different, 22개 중 주요 경로)

- `backend/agent/estimate/tools.py`
- `backend/agent/nodes/compute.py`, `backend/agent/nodes/fill.py`
- `backend/agent/rules/specs.py`
- `backend/agent/tools/calc/daily_crew.py`, `generated.py`, `per_unit.py`
- `backend/api/main.py`, `backend/api/tables.py`
- `data/calculation_modules/approved/formwork-adjustments-v1.json`
- `data/drafts/specs/건축/1-2-2.json`
- `docs/SPEC_FORMAT.md`
- `docs/handoffs/WORKSPACE-CURRENT.md`, `docs/plans/CALCULATION-AUTOMATION-MASTER-PLAN.md`
- `evals/test_calculation_modules.py`
- `frontend/src/components/ChatArea.test.js`, `ChatArea.tsx`
- `frontend/src/types.ts`

전체 목록은 `comparison.json`의 `state: "different"` 항목을 참조한다.

## 현실적인 커밋 묶음 제안 (최대 4개, 통합본 기준)

통합 작업 폴더(`tmp/integration-main-168d80a`)의 커밋 검토 문서(`integration-commit-review-2026-10-23.md`)가 이미 제시한 구성을 그대로 따르는 것이 합리적이다.

1. **C1. 공통 실행·상담·높이 UI 통합** — backend/frontend 전체, formula/lookup/generated/policies/quantity_units, 승인 모듈, 계산 계약·Python 실행 어댑터, 관련 상담·집계·Excel 검사. **C2와 묶어 하나의 통합 후보로 검증해야 한다** (formula가 generated를 import하고 compute/tools가 이를 선택하는 의존 관계 때문).
2. **C2. 원문·명세·요율 복구** — 수정된 명세, source chunks, 인덱스·검증 보고, 원문 조립/인용 검증, 요율 추출기·요율, 승격/변환 스크립트. C1에 의존.
3. **C3. 명세 생성·수정 및 배포 구성** — authoring 파이프라인·설정·후보/격리 검사, sandbox worker, Docker·번들 파일. C1의 실행 의존성과 연결돼 있어 분리 이력이 독립 배포 가능성을 뜻하지 않음.
4. **C4. 계획·인계·검토 기록** — 현재 기준 문서와 재현 결과 기록만. 다른 묶음에 의존하지 않고 가장 먼저 또는 가장 나중에 가능.

**의존 순서**: C1·C2 동시 검증 → C3 → C4. 공유 파일(backend/api/main.py, tables.py 등)은 경로 기준이 아니라 **hunk(내용) 단위로 검토**해야 한다는 점이 통합본 문서에서도 명시돼 있다.

원본 폴더(single-trade-conditions)의 missing_in_integration 16개 자료는 위 묶음과 별도로, 통합본에 반영할지 원본 전용으로 둘지부터 먼저 결정해야 한다.

## 오래된 staging을 그대로 커밋할 때의 위험

- 통합본 문서에 따르면 **기존 staged 22개 중 13개는 이후 unstaged 수정이 추가**됐다. 즉 현재 git index를 그대로 커밋하면 최신 완성 상태가 아니라 과거 중간 상태가 섞여 들어간다.
- R1(미산정 공사가 OK로 표시되는 가격 버그)과 R2(장비 요율 확장에 맞지 않는 회귀 검사)는 통합본에서 발견 당시 기록이 남아 있고, 이후 사용자 지시로 수정했다고 문서에 기록돼 있다. 다만 이는 통합본 쪽 기록이며, **이번 검토에서 코드 안정성이나 검사 통과를 재확인한 것은 아니다.**
- 민감 파일(`.claude/launch.json`, `api.env` 추정)이 작업 폴더에 존재하므로, 커밋 전에 `.gitignore` 반영 여부와 스테이징 대상에서 확실히 빠졌는지 다시 확인해야 한다.
- 정리 전 필요한 점검: (1) staged/unstaged 재검토로 최신 상태 재구성, (2) 공유 파일 hunk 단위 diff 확인, (3) R1/R2 외 유사한 "경로는 통과하지만 로직이 틀린" 사례가 더 있는지 재검사, (4) 의존성 패키지(예: pdfplumber, pypdf) 부재로 일부 검사가 건너뛰어진 이력이 있어 검사 커버리지 공백 확인.

## 삭제 후보 (후보일 뿐 삭제 가능 결론 아님)

- `evals/archive/2026-10-07-worktree-results/*`, `evals/archive/2026-10-14-planning-before-dashboard-merge/*` — 통합본에는 없지만(missing_in_integration), **squash 병합 여부나 다른 worktree의 고유 변경 포함 여부가 확인되지 않아** 삭제 가능하다고 결론 낼 수 없다.
- `evals/runtime_validation/` 하위 대량 평가 증거(776개 분류) — 인계 문서가 "임시 파일로 간주해 일괄 삭제하지 않는다"고 명시했으므로 이번에도 같은 입장을 유지한다.
- 그 외 16개 다른 16개 worktree(통합본 문서에 언급) — 이번 작업에서 전혀 건드리지 않았고 삭제 여부도 미확인 상태다.

## 요약

이번 검토는 자료 확인과 분류·커밋 묶음 제안까지만 수행했다. 실제 코드 비교, 테스트 실행, 파일 이동/삭제, git 작업은 전혀 하지 않았으며, 다음 단계는 (1) 원본에만 있는 16개 자료의 처리 방향 결정, (2) 공유 파일의 hunk 단위 diff 검토, (3) staging 재구성 후 사용자 승인 하에 C1~C4 순서로 커밋 진행이다.