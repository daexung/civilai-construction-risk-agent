# 현재 작업 기준

기준일: 2026-11-01

## 최신 브랜치 정리 및 핫픽스 분리

계산 확대 변경은 `codex/expand-equipment-estimates-20261101`에 로컬 체크포인트 커밋으로 보존한다. 이후 원본 작업 폴더는 최신 `origin/main`(확인한 기준 43a3b4a)에서 만든 `codex/hotfix-conversation-20261101`을 사용한다. 핫픽스에 미배포 계산 확대 변경을 섞지 않는다. 체크포인트 커밋은 배포·머지 승인이 아니며 푸시하지 않는다.

종료된 병렬 작업 브랜치 3개는 모두 같은 43a3b4a에서 갈라졌고 자체 커밋은 없다. 각 worktree의 미커밋·미추적·캐시를 제외한 로컬 산출물은 원본 `tmp/branch-cleanup-20261101/`의 ZIP·manifest·binary diff로 보존한 뒤 worktree와 해당 임시 브랜치를 정리한다. `tmp/parallel-execution-20261101/`의 공통 기준선·통합 결과·검사 로그는 계속 유지한다. 정리 실행 결과의 커밋·최종 브랜치는 Git과 `tmp/branch-cleanup-20261101/result.json`을 확인한다.

개발 기준 체크리스트는 `docs/plans/FOLLOW-UP-CHECKLIST.md`, 첫 병렬 통합 결과는 `docs/reviews/calculation-parallel-2026-11-01.md`다. 저장 증분 집계는 928/6/122/2이며 전체 정확성이나 견적 완성률은 아니다. 실제 배포 상태는 이번 정리로 바뀌지 않는다. 아래 내용은 이전 정리 이력이다.

## 이전 정리 이력 (2026-10-31)

정리 완료 후 실제 작업 위치는 C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent, 브랜치는 main이다. 이전 tmp/integration-main-168d80a의 계산 확장 작업을 이 위치의 main에 통합한다. 옛 작업 폴더로 돌아가 구현하지 않는다.

대목표는 품셈 근거에 따라 공종 1개부터 여러 개의 조건·수량·계산·집계·엑셀을 하나의 상담 흐름에서 처리하는 것이다. 기능·출시 기준은 docs/plans/CALCULATION-AUTOMATION-MASTER-PLAN.md를 따른다.

현재까지 단일·다중 상담 통합과 화면 로딩 개선이 원격 main에 반영돼 있다. 이후 계산 명세·공통 계산기·장비비·높이 입력·원문 근거 복구와 관련 검사를 로컬 main에 정리한다. 저장 인덱스의 기본 실행 분류 926 / 실패 6 / 미지원 124 / 제외 2는 과거 저장 집계다. 전체 조건 검증 완료 수나 이번 전수 검사 결과로 해석하지 않는다.

정리 시 가격 완성 상태, 통합 견적, 거푸집 높이·항목 수정, 장비 가동시간·금액·엑셀·복원의 오프라인 집중 검사와 프런트 운영 빌드가 통과했다. 실제 모델·운영 DB·브라우저·전체 명세 정확성을 이번에 검증한 것은 아니다. 과거 보안 검토의 후속 조치와 남은 계산 지원 확대는 별도 작업이다.

브랜치 이력과 과거 자료는 C:/Users/user/Desktop/PROJECTS/_civilai-archive-20261031에 비공개 보존한다. 이전 worktree는 active 작업 위치가 아니며, 과거 .git 연결을 그대로 사용하지 않는다. 이력 복구에는 archive의 Git bundle과 manifest를 사용한다. .env·인증 설정은 공개 커밋에 넣지 않는다.

원격 main 반영은 자동 배포를 유발하므로, 이 정리 단계의 로컬 통합과 운영 배포 확인을 구분한다. 최종 커밋·원격 상태는 git status와 git log로 확인한다.
