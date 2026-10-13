# 검색 2b단계 결과: 검사 기록 복구와 해시 목록 수정

작성일: 2026-10-12. 검사 기록과 저장 순서만 고쳤다. 파싱·청킹 내용과 연결은 바꾸지 않았다. 기존 원문 릴리스와 청킹 묶음은 지우지 않았다. 근거 조회·임베딩·외부 API·원격 연결·배포·커밋·푸시는 하지 않았다.

## 먼저 알아야 할 것

### 실제로 복구한 과거 기록과 새로 실행한 기록

**1b 단계의 원문 검사 JSON(`verification.json`, `example_queries.json`, `manifest.json`)은 복구하지 못했다.** 저장소와 임시 폴더를 찾아봤지만 사본이 없었다. `baseline/before-01b/`의 사본은 이전 릴리스(`…0aaa02185ae9`)의 것이라 대신 쓸 수 없다. 원래 JSON을 다시 만들어 내지 않았다.

실제로 남아 있는 것만 바이트 그대로 실행 기록 폴더로 옮겼다(`record_kind = preserved_past_run`). 과거 기록이며 현재 통과 실행으로 세지 않는다.

| 대상 | 과거 실행 | 남은 것 | 상태 |
|---|---|---|---|
| 원문 릴리스 | `20261012T001743-verify_db`(1b, 재적재·중단 검사 포함) | 표준 출력 기록 `stdout.txt`뿐(검사 이름 51줄, 모두 PASS). 상세 결과 값은 없음 | `passed_text_log_only` |
| 원문 릴리스 | `20261012T004204-verify_db`(청킹 뒤, 재적재 없이) | `verification.json`(통과 49, 실패 0), `example_queries.json`, 표준 출력, 당시 쓴 `manifest.json` | `passed` |
| 청킹 묶음 | `20261012T004143-verify_chunks`(2단계, `--reload`) | `verification.json`(통과 34, 실패 0), 표준 출력, 당시 `manifest.json` | `passed` |

2단계 청킹 검사의 첫 실행(실패 2개, 검사 가정 오류) 결과 파일도 다음 실행이 덮어써서 남아 있지 않다. 이는 실행 기록의 메모에 적었다.

**새로 실행한 기록**(`record_kind = current_run`):

| 대상 | 새 실행 | 내용 |
|---|---|---|
| 원문 릴리스 | `20261012T005708-verify_db` | 재적재 없는 원문 검사, 통과 49 / 실패 0 |
| 원문·청킹 | `20261012T005610-isolated_tx` | 격리 DB에서 한 트랜잭션 검사. 원문 5개, 청킹 4개 항목 모두 통과 |
| 청킹 묶음 | `20261012T005630-verify_chunks`, `20261012T005651-verify_chunks` | 재적재 없는 청킹 검사 두 번, 각 통과 32 / 실패 0 |

1b의 "51개 통과"와 이번 실행은 섞지 않는다.

- 1b의 51개 = 이번 재적재 없는 검사 49개 + 1b의 트랜잭션 검사 2개.
- 그 트랜잭션 검사 2개는 이번에 **격리 DB에서 새로 실행해** 별도로 기록했다. 1b 결과를 복구한 것이 아니다.
- 청킹 검사도 같다. 이전 34개 중 트랜잭션 2개를 격리 실행으로 옮겨, 현재 실행은 32개와 격리 4개다.

### 불일치 원인과 수정

**원인**:

- `verify_chunks.py --reload`가 중간에 `chunking.py load`를 실행했다. 이 적재가 자료 폴더의 `manifest.json`을 다시 썼는데, 그때 폴더에 있던 **이전** `verification.json`의 해시가 들어갔다.
- 그 뒤 검사 스크립트가 새 `verification.json`을 저장하면서 해시 목록은 갱신하지 않았다.
- 원문 쪽도 검사 결과를 자료 폴더에 직접 써서, 재실행이 과거 기록을 덮어썼다.
- 추가로 발견한 점: 원문 릴리스 `manifest.json`이 `*.json`만 모아 청킹 입력 `search_records.jsonl`을 목록에 넣지 않았다.

**수정**:

- **검사 결과를 자료 폴더에 쓰지 않는다.** 실행마다 `out/verification_runs/<대상 ID>/<run_id>/`에 저장한다(`src/run_records.py`).
- **저장 순서**:
  1. 실행 폴더를 만들고 `running`으로 기록한다.
  2. 결과 파일을 저장한다.
  3. 검사한 자료 파일의 해시를 계산한다.
  4. `run_manifest.json`(결과 파일 해시와 상태)을 쓴다.
  5. 마지막에 `index.json`을 갱신한다.
- `run_manifest.json`은 자기 해시를 담지 않는다. `index.json`이 각 `run_manifest.json`의 해시를 담는다.
- 검사 실패는 `failed`, 저장 실패는 `error`로 남는다. 도중에 멈춘 실행은 `running`으로 남는다. 어느 경우든 마지막 통과 실행(`latest_passed_by_tool`)은 바뀌지 않는다.
- `verify_db.py`와 `verify_chunks.py`는 위 경로로만 저장한다. `--reload`는 쓰지 않는다(쓰면 안내하고 멈춘다).
- 재적재·중단 검사는 격리 DB `civilai_rag_tx`에서 한다(`checks/isolated_tx.py`). 적재 코드가 쓰는 파일도 임시 폴더로 돌렸다가 검사 후 지운다. **기존 검증 DB의 청킹 묶음이나 원문을 지우지 않는다.**
- 자료 폴더의 과거 검사 결과 3개를 실행 기록으로 옮겼다(`checks/archive_past_runs.py`, 한 번 실행). 두 자료 폴더의 `manifest.json`은 남은 자료 파일 전체로 다시 만들었다. 원문 쪽은 이제 `search_records.jsonl`도 포함한다.
- `src/chunking.py`, `src/db.py`, `src/build_index.py`, `src/corrections.py`와 마이그레이션은 **고치지 않았다.** 그래서 원문 릴리스 ID와 청킹 묶음 ID의 산정 결과가 그대로다. 검사 코드는 ID 계산에 들어가지 않는다.

### 해시 일치와 청킹 데이터 변화

- `checks/check_records.py`로 파일에서 해시를 다시 계산해 확인했다. 문제는 0건이다.
  - 원문 자료 폴더 9개 파일, 청킹 자료 폴더 4개 파일이 모두 `manifest.json`과 맞는다. 목록에 없는 파일이나 섞인 검사 결과 파일은 없다.
  - 모든 실행 기록의 결과 파일 해시가 `run_manifest.json`과 맞는다. `index.json`의 `run_manifest` 해시도 맞는다.
  - 현재 실행들이 검사한 자료 파일은 지금 자료와 같다.
  - 과거 실행 두 개는 검사 결과를 옮기기 전 상태를 가리키므로 지금 자료 목록과 다르다고 표시된다(예상된 차이).
- **청킹 데이터 변화: 없음.**
  - DB 지문(원문 11개 테이블, 청킹 5개 테이블의 행 수와 내용 해시)이 작업 전과 같다.
  - 자료 파일(`chunks.jsonl`, `input_usage.jsonl`, `stats.json`, `import_manifest.json`, `search_records.jsonl` 등)의 해시도 작업 전과 같다.
  - 바뀐 것은 두 `manifest.json`이고, 자료 폴더에서 빠진 것은 검사 결과 3개다(실행 기록에 바이트 그대로 있음, `cmp`로 확인).
- 청크 5,764개, 원문 레코드 23,481개, 검색 입력 23,484개, 표 2,328개, 참조 241개의 내용과 상태가 그대로다. 이번 `verify_db`·`verify_chunks` 실행에서도 확인했다.
- 실행 기록 경로의 실패 처리 시험(`checks/run_records_selftest.py`, 가상 실행): 5개 항목 통과. 검사 실패, 저장 실패, 도중 멈춤, 이전 기록 보존, 파일 변경 감지를 확인했다.

### 아직 확인하지 못한 항목과 다음 단계

- 1b 원문 검사의 상세 결과 값은 복구할 수 없다. 남은 증거는 검사 이름과 통과 여부뿐이다.
- `db.py load`는 여전히 원문 자료 폴더의 `manifest.json`을 예전 방식(`*.json`만)으로 다시 쓴다. 이 파일은 릴리스 ID 계산에 들어가므로 이번에는 고치지 않았다. 원문 릴리스를 새로 만들 때 함께 고쳐야 한다. 현재 자료 폴더 목록은 바르게 다시 만들어 두었다.
- 격리 DB `civilai_rag_tx`는 검사 흔적으로 남겨 두었다. 기존 검증 DB와 별개다.
- **다음 근거 조회 단계는 진행할 수 있다.** 청킹 묶음 `cs-37f81b5cfb1b-46f4f035c0fa`와 원문 릴리스 `rk-complete-82c206c61e21-37f81b5cfb1b`가 그대로이고, 각 대상의 `index.json`이 현재 통과 실행을 가리킨다.
- 소속 미확정 설명과 수식 의미는 이번 범위가 아니며 바꾸지 않았다.

## 실행 명령

저장소 루트에서, 로컬 Supabase가 켜진 상태로 실행한다.

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_db.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_chunks.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/isolated_tx.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/check_records.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/run_records_selftest.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/fingerprint.py
```

## 결과 경로

- 실행 기록: `experiments/retrieval-v1/out/verification_runs/rk-complete-82c206c61e21-37f81b5cfb1b/`, `…/cs-37f81b5cfb1b-46f4f035c0fa/`. 각 폴더에 `index.json`과 실행별 폴더가 있다.
- 작업 전 보관: `experiments/retrieval-v1/baseline/before-02b/`
  - 덮어써진 파일과 당시 `manifest.json`
  - 코드 사본
  - 실행 출력 기록
  - `out` 파일 해시 목록 `out_files_sha256.txt`
  - DB 지문 `db_fingerprint.json`
- 작업 후 DB 지문: `experiments/retrieval-v1/baseline/db_fingerprint_after_02b.json`(작업 전과 같음).
- 새 코드:
  - `src/run_records.py`
  - `checks/isolated_tx.py`, `checks/check_records.py`, `checks/fingerprint.py`
  - `checks/run_records_selftest.py`(결과 `checks/run_records_selftest_result.json`)
  - `checks/archive_past_runs.py`
  - 수정: `checks/verify_db.py`, `checks/verify_chunks.py`, `README.md`

검사 수는 정확도 점수가 아니다.
