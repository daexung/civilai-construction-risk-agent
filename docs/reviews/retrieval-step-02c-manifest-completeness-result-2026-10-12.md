# 검색 2c단계 결과: 원문 해시 목록 누락 수정

작성일: 2026-10-12. 해시 목록을 만드는 코드만 고쳤다. 파싱·청킹 내용과 연결은 바꾸지 않았다. 기존 원문 릴리스와 청킹 묶음은 지우거나 덮어쓰지 않았다. 근거 조회·임베딩·원격 연결·배포·커밋·푸시는 하지 않았다.

## 먼저 알아야 할 것

### 1. 청킹 묶음은 기존 원문 버전을 계속 쓴다

| 대상 | ID | 상태 |
|---|---|---|
| **현재 청킹 묶음** | `cs-37f81b5cfb1b-46f4f035c0fa` | 그대로. complete |
| 청킹 묶음이 쓰는 원문 릴리스 | `rk-complete-82c206c61e21-37f81b5cfb1b` | **그대로 계속 사용.** 행·파일 모두 바뀌지 않음 |
| 새로 생긴 원문 릴리스 | `rk-complete-82c206c61e21-248c1cd42357` | `db.py`가 바뀌어 생긴 새 버전. 내용은 위와 같음. 청킹 묶음은 이쪽을 보지 않음 |

- 청킹 코드(`chunking.py`)의 `DEFAULT_RELEASE`는 기존 릴리스에 그대로 고정이다. 청킹 코드와 청킹 묶음 ID는 바뀌지 않았다.
- 새 릴리스에는 청킹 묶음을 만들지 않았다. 새 릴리스에서 청킹을 메모리로만 돌려 보고(저장 없음), 결과가 기존 청킹 묶음 저장 내용과 같음을 확인했다.
- 활성 릴리스(`release_channels`)는 0행 그대로다.
- `out/input_manifest.json`(가장 최근 적재 기록)은 새 릴리스를 가리키도록 다시 써졌다. 적재 코드가 매번 쓰는 파일이며, `verify_db.py`가 이 파일을 따라간다. 이전 내용은 `baseline/before-02c/out_input_manifest.json`에 있다. 청킹 쪽은 이 파일을 쓰지 않는다.

### 2. 원인과 수정

- **원인**: `db.py`의 `write_manifest`가 `*.json`만 모아서 청킹 입력 `search_records.jsonl`이 해시 목록에서 빠졌다.
- **수정**(`src/db.py`):
  - 폴더 안의 자료 파일 전체를 목록에 넣는다. 제외는 `manifest.json` 자신과 검사 결과 파일(`verification.json`, `example_queries.json`)뿐이다.
  - 상태 값을 주지 않으면 기존 목록의 상태를 유지한다(나중에 목록만 다시 만들 때 쓴다).
- **저장 순서**: `load`는 결과 파일(장부·`search_records.jsonl`·`import_manifest.json`)을 먼저 모두 저장하고, DB 적재가 성공한 뒤 마지막에 해시 목록을 만든다. 이 순서는 원래 그랬고 그대로다.
- **같이 고친 곳**(`checks/compare_releases.py`): 이 도구는 적재 뒤에 `compare_with_previous_release.json`을 자료 폴더에 쓴다. 쓴 직후 해시 목록을 다시 만들도록 한 줄을 더했다. **이번에는 이 도구를 실행하지 않았다**(새 버전 비교는 아래 `release_manifest_check.py`로 했다). 코드만 고쳤고 실행해 보지는 않았다.

### 3. 새 버전이 생긴 이유

`db.py`는 원문 릴리스 ID 계산에 들어간다. 입력 파일 해시는 같고 바뀐 코드 파일은 `db.py` 하나뿐이다(검사로 확인). 그래서 ID 끝 12자리만 `37f81b5cfb1b` → `248c1cd42357`로 바뀌었다. 기존 번호를 억지로 유지하지 않았다.

## 검증 결과

### 격리 환경에서 생성 경로 실행

`checks/release_manifest_check.py`(새 파일)가 격리 DB `civilai_rag_tx`와 임시 폴더에서 `db.load()`를 실행하고 확인했다. 기존 검증 DB와 자료 폴더는 읽기만 했고, 임시 폴더는 검사 뒤 지웠다.

| 확인 | 결과 |
|---|---|
| 해시 목록에 `search_records.jsonl` 포함 | 통과 |
| 폴더의 자료 파일 8개가 모두 목록에 있고, 목록의 파일이 모두 있음 | 통과 |
| 목록의 모든 해시가 파일에서 다시 계산한 값과 같음 | 통과 |
| 자료 폴더에 검사 결과 파일이 섞이지 않음 | 통과 |
| 장부·`search_records.jsonl`이 기존 릴리스와 같음(`release_id`만 다름) | 통과 |
| 입력 파일 해시 동일, 바뀐 코드는 `db.py`뿐 | 통과 |
| 원문 테이블 11개가 기존 릴리스와 같음(`release_id` 열만 제외) | 통과 |
| 새 릴리스의 청킹 입력 해시 = 기존 청킹 묶음의 입력 해시 | 통과 |
| 새 릴리스에서 메모리로 청킹한 결과 = 기존 청킹 묶음 저장 내용(ID 열 제외) | 통과 |
| 기존 청킹 묶음은 기존 원문 릴리스에 연결된 그대로 | 통과 |

같은 12개 항목을 새 릴리스를 검증 DB에 정상 기록한 뒤(`--recorded`)에도 다시 실행했고 모두 통과했다.

### 새 버전을 정상 기록

`db.py load`를 검증 DB `civilai_rag_verify`에서 실행했다. 새 릴리스 ID의 행만 추가했다. 새 자료 폴더는 `out/rk-complete-82c206c61e21-248c1cd42357/`이고, 해시 목록은 자료 파일 8개를 담는다(`search_records.jsonl` 포함).

| 대상 | 새 실행 | 결과 |
|---|---|---|
| 새 원문 릴리스 | `verify_db.py` | 통과 49 / 실패 0 |
| 기존 청킹 묶음 | `verify_chunks.py` | 통과 32 / 실패 0 |
| 새 원문 릴리스 | `isolated_tx.py`(원문 쪽) | 5개 통과 |
| 기존 청킹 묶음 | `isolated_tx.py`(청킹 쪽) | 4개 통과 |
| 전체 | `check_records.py` | 문제 0건 |

`isolated_tx.py`와 `check_records.py`는 새 릴리스 ID에 맞게 고쳤다(아래 파일 목록). 검사 개수는 정확도 점수가 아니다.

### 파싱·청킹 내용과 연결은 그대로

- **DB 지문**: 기존 원문 릴리스 11개 테이블, 기존 청킹 묶음 5개 테이블의 행 수와 내용 해시가 작업 전(`baseline/before-02c/db_fingerprint.json`)과 완전히 같다(`cmp`로 확인).
- **파일**: `out/` 파일 해시를 작업 전과 비교했다. 기존 자료 파일은 하나도 바뀌지 않았다. 바뀐 것은 아래 두 개뿐이다.
  - `out/input_manifest.json`: 최근 적재 기록(위 설명).
  - `out/verification_runs/cs-37f81b5cfb1b-46f4f035c0fa/index.json`: 새 실행 기록이 추가됨. 과거 실행은 그대로.
- **새 릴리스 내용**: 기존 릴리스와 같다. 청크 5,764개, 원문 레코드 23,481개, 검색 입력 23,484개, 참조 241개(기존 232 + 새 후보 9)는 같은 수다.
- 청킹을 새 릴리스에서 다시 돌리면 청킹 묶음 ID는 `cs-248c1cd42357-c074a14622a2`가 되지만(격리 DB에서 확인), 내용은 기존 묶음과 같다.

## 아직 확인하지 못한 것과 결정할 것

- `checks/compare_releases.py`의 해시 목록 재생성 한 줄은 실행해 보지 않았다.
- **어느 원문 릴리스를 근거 조회에 쓸지 정해야 한다.**
  - 기존 릴리스는 청킹 묶음이 외래 키로 가리키고 있다. 내용이 같으므로 그대로 쓰는 쪽이 간단하다.
  - 새 릴리스를 쓰려면 청킹 묶음을 새로 적재해야 하고, 그러면 청킹 묶음 ID가 바뀐다. 이번에는 하지 않았다.
- 기존 릴리스의 `manifest.json`은 2b단계에서 손으로 다시 만든 것이다. 지금 코드는 그 릴리스 ID를 다시 만들 수 없다(`db.py` 해시가 다름). 기존 릴리스를 다시 적재할 일은 없어야 한다.
- 격리 DB `civilai_rag_tx`는 검사 흔적으로 남아 있고, 이제 새 릴리스와 `cs-248c1cd42357-c074a14622a2`를 담고 있다. 기존 검증 DB와 별개다.
- 소속 미확정 설명과 수식 의미는 이번 범위가 아니며 바꾸지 않았다.

## 실행 명령

저장소 루트에서, 로컬 Supabase가 켜진 상태로 실행한다.

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/release_manifest_check.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/release_manifest_check.py --recorded rk-complete-82c206c61e21-248c1cd42357
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_db.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_chunks.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/isolated_tx.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/check_records.py
```

## 바뀐 파일과 결과 경로

- 수정: `src/db.py`(`write_manifest`), `checks/compare_releases.py`, `checks/isolated_tx.py`, `checks/fingerprint.py`(ID 열을 빼고 비교하는 옵션), `checks/check_records.py`(실행 기록이 있는 대상을 자동으로 따라감), `README.md`.
- 새 파일: `checks/release_manifest_check.py`.
- 새 원문 릴리스 자료: `experiments/retrieval-v1/out/rk-complete-82c206c61e21-248c1cd42357/`
- 실행 기록: `experiments/retrieval-v1/out/verification_runs/rk-complete-82c206c61e21-248c1cd42357/` (`index.json` + 실행별 폴더)
- 작업 전 보관: `experiments/retrieval-v1/baseline/before-02c/` (코드 사본, `out` 파일 해시 목록, DB 지문, 이전 `input_manifest.json`)
- 작업 후 DB 지문: `experiments/retrieval-v1/baseline/db_fingerprint_after_02c.json` (작업 전과 같음)
