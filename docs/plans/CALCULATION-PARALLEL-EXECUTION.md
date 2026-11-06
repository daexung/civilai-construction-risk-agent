# 품셈이 병렬 실행 규약 — 2026-11-01

상위 제품 목표/출시 기준은 CALCULATION-AUTOMATION-MASTER-PLAN.md 그대로 유지한다. 사용자는 Sol이 Luna/medium 작업자 3명을 직접 운용하고 통합 검토하는 것을 승인했다. 이 문서는 실행 분담만 고정한다.

## 위치와 기준선

통합 소유자 Sol의 폴더는 C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent 이다. HEAD 43a3b4a에 기존 불도저 미커밋 변경 8개 경로를 적용한 상태를 공통 시작점으로 삼는다. 기준선 파일은 tmp/parallel-execution-20261101/baseline/manifest.json에 해시로 보존했다. 각 작업 폴더에 동일한 8개 파일을 복사하고 해시를 확인했다. 작업자가 git diff HEAD 전체를 자기 작업으로 보고하면 안 된다. 자기 변경은 이 시작점 대비 구분한다.

- A: tmp/parallel-execution-20261101/equipment, codex/parallel-equipment-20261101
- B: tmp/parallel-execution-20261101/coverage, codex/parallel-coverage-20261101
- C: tmp/parallel-execution-20261101/runtime, codex/parallel-runtime-20261101

원본과 다른 작업 폴더는 읽기만 가능하다. Git branch를 다른 폴더에서 전환하지 않는다. 커밋·푸시·머지·배포·운영 DB·모델/임베딩 호출 금지. .env 복사·출력 금지. Node24/보안 핀 보존. reset/clean/stash 및 다른 작업자 호출 금지.

## 소유권

| 담당 | 수정 소유권 | 산출물 |
|---|---|---|
| A | data/drafts/specs/공통/8-2-*.json, data/rates/equipment_rates.json, pipeline/equipment_rates_general.py, 장비 전용 검사·fixture | 기존 formula의 가격 연결 및 남은 장비 공식·시간·금액·Excel 확대 |
| B | A 영역을 제외한 data/drafts/specs 하위 명세, 새 비장비 전용 검사·fixture | 작업시간·측량 등 미지원 가족을 기존 공통 실행기로 일괄 연결 |
| C | backend 공통 실행기·API·집계 및 새 공통 회귀 검사 | A/B 공통 기능 요청 해결, 물량 배율·부분 견적·합계·수정·복원·Excel 계약 검증 |
| Sol | master plan/인계, 공유 chunks/index/report, 큐와 결과 통합 | 중복 없는 통합, 영향 검사, 완료 판정 |

A의 장비 e2e와 C의 공통 검사는 서로 다른 파일로 작성한다. B가 원문 파싱 자료를 복구해야 하면 자기 임시 파일에 정확한 JSON 레코드 delta를 쓰고 Sol에 전달한다. data/processed/chunks.all.jsonl을 각각 다른 사람이 덮어쓰지 않는다. 공통 연산 추가는 C에게 최소 재현과 원하는 계약을 전달한다. C는 새로운 입력/출력 계약을 적용 전에 A/B와 공유한다. 다른 작업 폴더에 직접 쓰지 않는다.

## 이번 묶음

각 작업자는 25분 이내 구현·집중 검사·인계를 마친다. Sol은 전체 45분 이내 1차 통합 결과를 정리한다. 사용자에게 반복 승인을 묻지 않는다. 동일 실패 2회는 원인을 기록하고 처리 가능한 다른 항목으로 이동한다. 시간 제한은 실패를 통과로 바꿀 이유가 아니다. 중간 상태를 반복 보고하지 않고 실제 차단·공통 계약 요청·최종 인계만 보낸다.

조회 값 생성은 견적 완료가 아니다. 원문 의미를 유지한 현장 입력→품량/장비시간→가격→집계→수정→복원→Excel 실제 셀을 확인한다. 물량100→200에 단가 유지와 총액 배율을 독립 기대값으로 확인해 중복곱을 잡는다. 원문 부재를 임의값·광범위 fuzzy 매칭·대시=0으로 메우지 않는다. 산식·감산률·누적방식·근거ID를 사용자에게 묻지 않는다. 현장 실측 L과 시스템 f는 구분한다.

원문·표·규칙 ID, 검증 사례와 기대값 근거를 남긴다. 등록 함수/lookup을 임시 패치하거나 검사 출력으로 기대값을 만들지 않는다. 기존 검사는 영향이 있는 것만 수행한다. 저장 실행 인덱스의 926/6/124/2는 증분 기본 실행 기록이며 견적 완성률이 아니다. 로컬 실제 모델 생성 성공으로 집계하지 않는다.

## 환경

Python은 원본 폴더 .venv/Scripts/python.exe 절대경로를 쓴다. PYTHONPATH는 각자 작업 폴더다. page_map.json은 각 폴더에 별도 복사했다. 모델·벡터 검색 없이 실제 dialogue graph/API 응답 변환을 검사한다. Windows TestClient/loopback가 멈추면 20초 넘게 기다리지 말고 해당 HTTP 검증은 미실행으로 남긴다. 공용 PDF 패키지 경로는 필요하면 load_workspace_dependencies로 확인하고 테스트 프로세스 sys.path에만 추가한다. frontend/node_modules나 .env를 작업 폴더에 복사하지 않는다.

## 결과 인계

자기 작업 폴더의 tmp/parallel-result.json과 짧은 Markdown에 다음을 기록한다: 시작/종료 시각, 공종 ID, 원문·규칙 근거, 구현 범위, 실제 견적 연결/조회/차단 구분, 실행 검사와 결과, 시작점 대비 변경 경로/해시, 다음 정확한 재개 지점. 전용 결과 파일은 자기 폴더 안에만 쓴다. 최종 응답에 해당 절대 경로와 요약을 루트에게 전달한다. 완료 뒤 프로세스를 남기지 않는다.
