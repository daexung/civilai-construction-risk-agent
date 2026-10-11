# 최종 파싱 수정본

2026-10-11까지의 표·본문 개선 코드를 한 폴더로 정리했다. 운영 `pipeline`과 분리된 실행본이며, 청킹·임베딩·서비스 데이터 교체는 수행하지 않는다.

기준 결과는 982쪽, 표 2,328개, 청킹 전 레코드 23,481개다. 기존 보류 286표 중 285표를 교정했고 758쪽 한 표는 원문의 수량 조건이 모호해 보류했다. 하위 글 947개 중 933개를 복구하고 14개는 이미 표에 있거나 쪽 바닥 표시라 정상 제외했다.

## 폴더 구성

| 경로 | 용도 | 깃 저장 |
|---|---|---|
| `pipeline/` | 검증된 최종 파싱 코드 12개. 기존 파일의 바이트와 버전 유지 | 포함 |
| `corrections.json`, `row_mappings.json`, `completeness.json`, `reviewed_tables.json`, `diagram_tables.json` | 문서·원시 출력·엔진·교정 전 내용이 맞을 때만 적용하는 교정 자료 | 포함 |
| `page_map.json` | 같은 생성 결과의 부문 정보 | 포함 |
| `run.py`, 확인 스크립트 네 개 | 전체 재생성과 검증. 이전 실험 폴더를 읽지 않음 | 포함 |
| `evidence/` | 정리 전 최종 수치·버전·복구 목록·검증 결과와 60·65·72쪽 대조 그림 | 포함 |
| `local/raw.json`, `local/raw_run_info.json` | 보존한 전체 ODL 원시 출력과 추출 기록 | 제외, 로컬 보존 |
| `local/baseline/table-review/` | 보류 표 교정 직전의 비교 기준과 교정 자료 | 제외, 로컬 보존 |
| `local/baseline/body-text/` | 본문 누락 수정 직전의 비교 기준과 623개 목록 | 제외, 로컬 보존 |
| `local/prior-review-artifacts.zip` | 이전 코드·검토 그림·소규모 기록을 내용 해시별로 중복 제거한 보관본 | 제외, 로컬 보존 |
| `out/` | 현재 파싱 출력과 재생성 가능한 확인 결과 | 제외, 로컬 보존 |

필수 로컬 입력과 비교 기준은 이번 정리에서 실제 파일로 보존했다. 새로 복제한 저장소에는 `local/`과 `out/`이 없으므로 보관한 자료를 별도로 복원해야 한다. Git에 코드가 저장됐다는 사실과 대용량 로컬 자료까지 원격에 보관됐다는 사실을 혼동하지 않는다.

PDF는 저장소의 `data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf`를 사용한다. PDF와 원시 출력의 기대 해시는 `evidence/generation.json`에 있다. 다른 문서나 다른 엔진의 자료로 교정 자료를 억지 적용하지 않는다.

## 실행과 확인

Python 3.11과 `requirements.txt`의 PyMuPDF 1.28.2에서 이번 정리 후 검증했다. 기존 로컬 실행 환경을 사용하며, 아래 명령은 저장소 루트에서 실행한다. 새 ODL 추출이나 외부 API 호출은 없다.

```powershell
python -B experiments/parsing-final/run.py generate
python -B experiments/parsing-final/verify_resume.py
python -B experiments/parsing-final/source_window_audit.py
python -B experiments/parsing-final/body_text_audit.py
python -B experiments/parsing-final/check_guards.py
```

확인 스크립트는 검증 실패 시 0이 아닌 종료 코드를 반환한다. `body_text_audit.py`는 같은 쪽·상위 구조·문구가 반복될 때 목록 개수와 원시 항목 개수가 같아야 하며 원문 순서로 대응한다. 개수가 다르거나 같은 원시 항목이 중복 대응되면 실패한다. 이 변경은 확인 경로의 개선이며 파싱 규칙 변경이 아니다.

최신 입력은 `out/records.jsonl`, 원문 연결은 `out/links.json`, 실행 버전은 `out/generation.json`이다. `out/store.json`은 원문 표·칸·본문·위치와 제외 사유를 보관한다.

## 확인 범위와 남은 문제

- 원시 출력에서 최종 레코드까지 설명 없는 전달 누락 0개를 확인한다. PDF 최초 추출의 모든 손실이나 모든 계산 의미가 검증됐다는 뜻은 아니다.
- 수식 전용 부호가 있는 글 항목은 새 본문 129개, 기존 본문 137개다. 수식 개수가 아니며 일부 식은 조각으로 남는다.
- 설명 소속 미확정 관계 76개, 표 뒤 설명 후보 관계 142개는 확정 연결로 쓰지 않는다.
- 목차는 보존하며 근거 검색에서의 사용 여부는 청킹 단계에서 결정한다.
- 758쪽의 `0.215`와 `0.415`는 둘 다 보존한다. 원문에 없는 선택 조건을 만들지 않는다.

개발 순서와 지표는 [개발 이력](../../docs/handoffs/PARSING-DEVELOPMENT-HISTORY-2026-10-11.md), 정리와 검증 결과는 [정리 결과](../../docs/reviews/parsing-cleanup-result-2026-10-11.md)에 남긴다. 이전 보고서의 날짜별 폴더는 과거 작업 위치다. 현재 실행에는 이 폴더를 사용한다.
