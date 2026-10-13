# 검색 1b단계 결과: 길어깨 세 절의 제목과 소속 보완

작성일: 2026-10-12(지시서 날짜 2026-10-11). 원문 대조 교정 자료를 **원문 저장·검색 단계(`experiments/retrieval-v1`)에 적용한 결과**다. 파싱 원본 출력(`experiments/parsing-final`)은 바꾸지 않았다. 청킹·임베딩·원격 Supabase 연결·배포·커밋·푸시는 하지 않았다.

## 먼저 알아야 할 것

### 이번에 완료한 것

- **빠진 제목 3개를 보완했다**: 토목 `1-2-2`·`1-3-2`·`1-4-2 기계포설(길어깨)`(PDF 364·365·366쪽, 책 308·309·310쪽).
- **함께 빠져 있던 기준 줄 3개도 보완했다**: 각 제목 바로 아래 `(일당)`. 원시 ODL 출력에는 제목 줄과 이 기준 줄 모두 노드가 없었다.
- **잘못 붙어 있던 15개 항목을 옮겼다**: 표 3개와 설명 12개(쪽마다 표 1개와 `[주]` ①~④). 앞의 인력 작업 절(`1-2-1`·`1-3-1`·`1-4-1 인력식 소규모장비 포설`) 아래에 있던 것을 새 절로 옮겼다.
  - 레코드로는 30개다: 표 레코드 18개, 설명 레코드 12개.
  - 이 30개는 다음 청킹이 읽을 검색용 글 앞의 절 제목도 `1-2-1 인력식 소규모장비 포설 | …`에서 `1-2-2 기계포설(길어깨) | …`로 바꿨다. 나머지 글(값·칸)은 원본과 같다.
- 절은 1,359개에서 **1,362개**가 됐다. 목차 1,362줄이 모두 본문 절과 부문·번호·제목까지 맞는다(이전에는 3줄이 맞지 않았다).
- 새 릴리스 `rk-complete-82c206c61e21-37f81b5cfb1b`를 로컬 검증 DB `civilai_rag_verify`에 적재하고 검증했다. 이전 릴리스 `rk-complete-82c206c61e21-0aaa02185ae9`와 그 결과 파일은 그대로 남겼다. 활성 릴리스는 지정하지 않았다.

### 남은 것

- **이번 범위의 미해결: 없다.** 세 절의 제목·기준·소속 경계가 PDF와 맞는다.
- **기존 참조 미확정 22개는 그대로다**: 부분 확인 15, 모호함 6, 대상 없음 1. 이번 교정과 관계없고 억지로 확정하지 않았다. 참조 232건의 상태(확인 210 / 부분 15 / 모호 6 / 없음 1)와 새 후보 9건은 수정 전과 완전히 같다.

### 새로 발견한 것

- **원본 관계 15건이 교정 소속과 맞지 않는다.** 원본은 보존했고, 근거와 함께 기록만 했다.
  - 쪽마다 5건씩 세 종류다.
  - **표 관계 1건**: 원본 파싱이 길어깨 표를 앞 절 표의 "주석 아래에 붙은 표"(`note_table_of`, 예: `full-p364-o49622 → full-p363-o49569`)로 연결했다.
  - **설명 관계 4건**: 표 아래 `[주]` ②~④는 앞 절 제목 문자열(`1-2-1 인력식 소규모장비 포설`)에 연결돼 있다(`note_of_section`). `[주]` ①은 소속 미확정(`note_of_unknown`)이다.
  - 영향: 다음 청킹이 원본 관계의 "주석 표"를 그대로 따르면 길어깨 표가 다시 인력 작업 표 쪽에 붙을 수 있다.
  - 기록 위치: `corrections.data.superseded_relations`와 `correction_ledger.json`. 청킹은 교정 소속(`search_records`)을 따라야 한다.
- 원인: ODL이 이 세 쪽 맨 위의 제목 줄과 `(일당)` 줄을 추출하지 않았다. 같은 현상이 다른 쪽에도 있는지는 이번 범위가 아니어서 찾지 않았다. 다만 목차 1,362줄이 모두 본문 절과 맞으므로, 번호 있는 절 제목이 빠진 곳은 더 없다.

### 다음 한 가지

**청킹을 시작할 수 있다.** 입력 경로는 다음과 같다.

- 입력: 로컬 검증 DB의 `rag_knowledge.search_records`(릴리스 `rk-complete-82c206c61e21-37f81b5cfb1b`, 23,484행).
- 같은 내용의 파일: `experiments/retrieval-v1/out/rk-complete-82c206c61e21-37f81b5cfb1b/search_records.jsonl`.
- 원문 추적: `source_records`(원본 23,481)·`nodes`·`sections`를 함께 쓴다.

## 원문 대조

수정 결과를 보기 전에 PDF 세 쪽의 그림(`experiments/retrieval-v1/corrections/review/page364~366.png`)과 PyMuPDF 글자 줄 위치를 보고 `corrections/expected_shoulder.json`을 먼저 썼다. 여기에는 기대 제목, 옮길 항목, 바뀌면 안 되는 이웃 절 항목을 적었다.

| PDF 쪽 | 제목 줄(왼쪽 위 원점 y) | 기준 | 옮긴 항목 | 다음 제목 |
|---|---|---|---|---|
| 364 | `1-2-2 기계포설(길어깨)`(68.6~80.6, 12pt) | `(일당)` | `full-p364-o49622`, `n49658`, `n49660`, `n49661`, `n49662` | `1-2-3 기계포설(본선)`(y 303.6) |
| 365 | `1-3-2 기계포설(길어깨)` | `(일당)` | `full-p365-o49759`, `n49795`, `n49797`, `n49798`, `n49799` | `1-3-3 기계포설(본선)`(y 299.6) |
| 366 | `1-4-2 기계포설(길어깨)` | `(일당)` | `full-p366-o49896`, `n49932`, `n49934`, `n49935`, `n49936` | `1-4-3 기계포설(본선)`(y 306.0) |

- 표 아래 `[주]` ①이 "굴착기를 사용한 소로구간"이라고 적고 있다. 앞 절의 "소형 다짐장비 … 소규모구간"이나 다음 절의 "모터그레이더 … 본선구간"과 다른 작업이라는 원문 근거다.
- 364쪽 표의 값을 그림과 대조했다: 포설공 2, 보통인부 2, 굴착기 1.0㎥ 1, 진동롤러 12ton 1, 살수차 16,000ℓ 0.5, 시공량 250㎥. 검색용 글의 값이 이와 같다.
- 같은 쪽의 본선 작업 절(`1-2-3`·`1-3-3`·`1-4-3`)과 앞 인력 작업 절의 기준·표·`[주]`는 기존 소속 그대로다. 예상한 이웃 36개 항목 모두 그대로다.

## 적용 방식

| 파일 | 내용 |
|---|---|
| `corrections/shoulder_sections.json` | 교정 자료. PDF 해시, 입력 3개 해시, 제목·기준 원문과 PDF 위치, 쪽·책 쪽, 대상 원문 식별자, 다음 제목, 기존 소속, 대조 근거 |
| `src/corrections.py` | 적용 전 확인과 교정 노드 생성 |
| `src/build_index.py` | 교정 전 소속을 먼저 구해 확인한 뒤 절 등록, 검색 입력 생성 |
| `sql/20261011000200_rag_search_records.sql` | 새 마이그레이션. `corrections`, `search_records` 테이블 |

- 적용 전에 다음을 다시 확인한다. 하나라도 다르면 적용 전체를 거부한다(`CorrectionRejected`).
  - PDF 해시와 입력 해시가 교정 자료와 같은지
  - PDF 위치에서 다시 읽은 제목·기준 글자가 같은지
  - 원시 출력에 같은 제목 노드가 없는지
  - 첫 대상부터 다음 제목 전까지의 노드가 대상 목록과 정확히 같은지
  - 각 대상의 기존 소속이 기대값과 같은지
  - 목차 항목의 제목과 책 쪽이 같은지
- 새 제목·기준 노드는 `corr:civil-1-2-2:heading`처럼 교정 식별자를 쓴다. ODL 항목 번호(`odl_id`)와 문서 순서 번호는 비워 두었다. 존재하지 않는 ODL 번호를 만들지 않았다.
- 새 절은 첫 소속 항목(표)의 기존 순서 번호에서 시작한다. 다른 항목의 순서 번호는 하나도 바꾸지 않았다.
- `source_records`(원본 레코드 글과 연결 정보)는 그대로다. 검색용 글은 `search_records`에만 있다.
  - `origin=original` 23,451개
  - `section_corrected` 30개: 이전 절 제목도 `previous_section_text`로 보관
  - `added_from_pdf` 3개: `(일당)`
- 교정 자료·교정 코드·새 마이그레이션의 해시는 릴리스 ID 계산(`input_manifest.json`)과 `import_manifest.json`에 들어간다.

## 수정 전후 비교

`checks/compare_releases.py`로 두 릴리스를 DB에서 직접 비교했다. 결과 파일은 `out/rk-complete-82c206c61e21-37f81b5cfb1b/compare_with_previous_release.json`이다.

| 테이블 | 이전 | 새 | 추가 | 삭제 | 변경 | 변경 내용 |
|---|---|---|---|---|---|---|
| nodes | 106,819 | 106,825 | 6 | 0 | 0 | 교정 제목 3·기준 3 |
| sections | 1,359 | 1,362 | 3 | 0 | 3 | 앞 절 1-2-1·1-3-1·1-4-1의 끝 범위(`end_order`, `last_page`)만 |
| toc_entries | 1,362 | 1,362 | 0 | 0 | 3 | 길어깨 목차 3줄이 본문 절과 대조됨 |
| source_records | 23,481 | 23,481 | 0 | 0 | 30 | 대상 레코드의 `section_id`만(글·원래 JSON·연결 정보 같음) |
| record_cells, source_relations, edges, edge_candidates | — | — | 0 | 0 | 0 | 같음 |

- 대상 밖의 내용과 소속 차이는 0이다.
- 실행 정보 차이는 릴리스 ID 하나다. 입력 해시는 같고, 교정 자료·교정 코드·새 마이그레이션 해시가 더해졌다.
- 표 2,328개와 칸 82,232개, 칸 연결 70,158개, 758쪽 보류 표의 `0.215 0.415`는 변화가 없다(검증 항목으로도 확인).

## 검증

- `checks/verify_db.py --reload`: 51개 항목 통과, 실패 0.
  - 기존 데이터 보존 검사(레코드 23,481, 표 2,328, 관계 11,823, 참조 232, 외래 키·중복, 기대 참조 사례)는 그대로 다시 실행했다.
  - 이번에 더한 검사:
    - 교정 기대 3건(새 절 등록, 이동 항목, 이웃 절 유지)
    - 절 1,362와 교정 3
    - 목차 1,362 대조
    - 교정 노드에 ODL 번호 없음
    - 검색 입력 구성 23,451 + 30 + 3
    - 교정 밖 검색 글 = 원본 글
    - 교정 대상의 절 제목이 새 소속과 같고 앞 절 제목(`인력식 소규모장비 포설`)이 남지 않음
    - 절 제목 뒤 글은 원본과 같음
    - `(일당)`이 표 앞에 놓임
    - 맞지 않는 원본 관계 15건을 빠짐없이 기록
  - 적재 도중 일부러 실패시키자 전부 되돌아갔다. 이전 정상 릴리스와 새 릴리스 모두 `complete` 그대로였다.
  - 같은 입력으로 다시 적재하자 행 수·내용 해시·식별자가 같았다.
- `checks/correction_guard.py`(가상 입력): 교정 자료를 일부러 틀리게 바꾼 7가지가 모두 거부됐다. 바꾼 항목은 PDF 해시, 입력 해시, 제목 글자, 제목 위치, 기존 소속, 대상 목록, 목차 쪽이다.
- `checks/virtual_cases.py`: 기존 가상 검사 10개 통과.
- 기존 검사 중 세 제목 누락을 전제로 한 것은 없었다. 목차 대조는 정보로만 기록했었는데, 이전 기록은 `no_body_section` 3이었고 이번에는 0이다. 이번에 "목차 1,362줄 모두 대조됨"을 검사 항목으로 추가했다.
- 검사 수는 정확도 점수가 아니다. 의미 판단은 위 원문 대조로 했다.

## 재현 명령

저장소 루트에서, 로컬 Supabase가 켜진 상태로 실행한다.

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/db.py migrate
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/db.py load
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/compare_releases.py rk-complete-82c206c61e21-0aaa02185ae9 rk-complete-82c206c61e21-37f81b5cfb1b
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_db.py --reload
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/correction_guard.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/virtual_cases.py
```

## 보관 위치

`experiments/retrieval-v1/`:

- 교정 자료와 원문 대조 근거: `corrections/shoulder_sections.json`, `corrections/expected_shoulder.json`, `corrections/review/page364~366.png`
- 수정 전 보관: `baseline/before-01b/`
  - 코드·SQL·검사 복사본과 코드 해시
  - 이전 릴리스 장부: `release_out/`. 현재 `out/rk-…0aaa02185ae9/`와 내용이 같음을 확인했다.
  - 대상 주변 소속: `membership_p363_367.tsv`
- 새 릴리스 출력: `out/rk-complete-82c206c61e21-37f81b5cfb1b/`
  - `search_records.jsonl`, `correction_ledger.json`, `compare_with_previous_release.json`
  - `verification.json`, `section_registry.json`, `reference_ledger.json` 등
- 실행 기록: `checks/verify_db_last_run.txt`, `checks/compare_last_run.json`, `checks/correction_guard_result.json`, `checks/virtual_cases_result.json`

작업 중 만든 중간 릴리스 하나(`…1f8c056e046f`)는 검증 DB에서 지웠다. 맞지 않는 원본 관계를 기록하는 기능을 추가하기 전의 것이다. 검증 DB에는 이전 정상 릴리스와 이번 릴리스 두 개만 남아 있다.
