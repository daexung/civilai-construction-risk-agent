# retrieval-v1: 원문·절·참조 저장소 (1단계)

최종 파싱 결과(`experiments/parsing-final`, 생성 `complete-82c206c61e21`)를 로컬 PostgreSQL에 저장하고, 실제 본문 절 목록과 기존 참조 232건의 대상 절 연결을 만든다. 청킹·임베딩·서비스 변경은 다음 단계다.

## 구성

| 경로 | 내용 |
|---|---|
| `sql/20261011000100_rag_knowledge.sql` | 마이그레이션. 전용 스키마 `rag_knowledge`, 릴리스 단위 저장. 다시 실행해도 안전 |
| `sql/20261011000200_rag_search_records.sql` | 교정 자료(`corrections`)와 다음 청킹 입력(`search_records`) |
| `src/build_index.py` | 입력 해시·수량 확인, 원문 노드, 절 목록, 목차 대조, 참조 연결, 새 후보 점검(DB 없이 실행) |
| `src/db.py` | 검증 DB 생성, 마이그레이션, 한 트랜잭션 적재, 장부 작성 |
| `src/query.py` | 조회 초안(`EvidenceStore`): 참조 따라가기(방문 기록·깊이 한도), 절 범위 읽기 |
| `checks/expected_references.json` | 결과를 보기 전에 PDF 원문으로 정한 기대 연결 |
| `checks/verify_db.py` | DB와 원래 입력 직접 비교, 기대 사례, 중단 시 되돌림·재적재 동일성 |
| `checks/virtual_cases.py` | 가상 입력 검사(외부 문서·없는 절·순환·대상 변경) |
| `out/<release_id>/` | 적재 장부와 검증 결과(Git 제외) |

## 실행 환경

- 기존 로컬 Supabase(`supabase/config.toml`, PostgreSQL 17, Docker 컨테이너 `supabase_db_civilai-construction-risk-agent`)를 재사용한다.
- 회원·대화 자료가 있는 `postgres` DB는 쓰지 않고 같은 서버에 검증 전용 DB `civilai_rag_verify`를 만든다. `db.py`는 원격 주소와 `postgres` DB를 거부한다.
- Python은 저장소 `.venv`(psycopg 3)를 쓴다. 연결 문자열은 `RAG_DATABASE_URL`, 없으면 로컬 기본값.

## 재현

저장소 루트에서 실행한다. Docker Desktop과 로컬 Supabase가 켜져 있어야 한다(`npx --yes supabase@2.119.0 start --exclude postgres-meta`).

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/db.py createdb
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/db.py migrate
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/db.py load
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_db.py --reload
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/virtual_cases.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/correction_guard.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/compare_releases.py <이전 release_id> <새 release_id>
```

`load`는 같은 입력이면 같은 `release_id`를 만들고, 그 릴리스 행을 한 트랜잭션에서 지우고 다시 넣는다. 실패하면 전부 되돌리고, 활성 릴리스(`release_channels`)는 바꾸지 않는다. `release_id`는 입력 해시와 적재 코드·마이그레이션 해시로 정한다.

## 출력(`out/<release_id>/`)

`input_manifest.json`, `import_manifest.json`(테이블별 행 수·내용 해시), `source_coverage.json`, `section_registry.json`, `reference_ledger.json`(기존 232건), `additional_reference_candidates.json`(새 후보, 별도), `correction_ledger.json`, `search_records.jsonl`, `manifest.json`. 검사 결과(`verification.json` 등)는 이 폴더가 아니라 `out/verification_runs/`에 쌓는다.

`manifest.json`은 이 폴더의 자료 파일 전체(`manifest.json`·검사 결과 제외)의 해시 목록이며 모든 결과 파일 저장 뒤 마지막에 만든다(`db.write_manifest`). 이후 파일을 더 쓰면 `db.write_manifest(release_id)`로 다시 만든다.

## 원문 대조 교정(1b단계)

- `corrections/shoulder_sections.json`: 원시 ODL 출력에 없던 토목 1-2-2·1-3-2·1-4-2 기계포설(길어깨) 제목과 각 `(일당)` 기준. PDF 해시·입력 해시·PDF 위치·대상 원문 식별자·기존 소속·근거를 고정한다.
- `src/corrections.py`가 적용 전에 PDF 영역 글자, 대상 순서와 기존 소속, 목차 항목을 다시 확인하고 하나라도 다르면 거부한다(`checks/correction_guard.py`).
- 파싱 원본(`experiments/parsing-final`)과 `source_records`는 그대로다. 교정으로 추가한 노드는 `corr:` 식별자이고 ODL 번호·순서 번호가 없다.
- **다음 청킹 입력**: DB `rag_knowledge.search_records`(같은 내용 파일 `out/<release_id>/search_records.jsonl`). 원본 레코드 23,481개 중 교정 대상 30개만 글 앞 절 제목이 바뀌고, 원문에서 보완한 `(일당)` 3개가 더해진다.
- 원본 관계 중 교정 소속과 맞지 않는 15건은 바꾸지 않고 `corrections.data.superseded_relations`와 `correction_ledger.json`에 기록한다. 청킹은 교정 소속을 따른다.
- 비교: `checks/compare_releases.py <이전> <새>`. 수정 전 코드·장부·대상 주변 소속은 `baseline/before-01b/`에 있다.

## 청킹(2단계)

- 코드 `src/chunking.py`, 마이그레이션 `sql/20261012000100_rag_chunks.sql`, 검사 `checks/verify_chunks.py`, 사전 기대값 `checks/expected_chunks.json`.
- 입력: 원문 릴리스 `rk-complete-82c206c61e21-37f81b5cfb1b`의 `search_records`와 원문 구조·관계(DB). 원문 릴리스는 바꾸지 않는다.
- 조각 종류: `work`(본문 절), `rule`(설명), `table`(표). 저장 테이블: `chunk_sets`, `chunks`, `chunk_sources`, `chunk_cells`, `chunk_links`, `chunk_exclusions`.
- 출력: `out/chunks/<chunk_set_id>/`(`chunks.jsonl`, `input_usage.jsonl`, `stats.json`, `import_manifest.json`, `manifest.json`, `verification.json`).

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/chunking.py migrate
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/chunking.py load
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_chunks.py
```

주의: 청크가 원문 릴리스 행을 외래 키로 가리키므로, 같은 원문 릴리스를 `db.py load`로 다시 적재하면 외래 키가 막는다(원문 보호).

## 검사 실행 기록(2b단계)

- 검사 결과는 자료 폴더에 쓰지 않는다. 실행마다 `out/verification_runs/<release_id 또는 chunk_set_id>/<run_id>/`에 결과와 `run_manifest.json`(결과 파일 해시, 검사한 자료 파일 해시, 상태)을 쓰고, 마지막에 `index.json`을 갱신한다(`src/run_records.py`). 과거 실행은 지우지 않는다.
- 재적재·중단 검사는 격리 DB `civilai_rag_tx`에서 한다: `checks/isolated_tx.py`. `verify_db.py`·`verify_chunks.py`의 `--reload`는 쓰지 않는다.
- 독립 확인: `checks/check_records.py`(자료 폴더 해시 목록과 모든 실행 기록을 다시 계산), `checks/run_records_selftest.py`(실패·저장 실패·중단 시 통과로 표시하지 않는지), `checks/fingerprint.py`(DB 내용 지문).

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_db.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_chunks.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/isolated_tx.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/check_records.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/release_manifest_check.py   # 격리 DB에서 적재 경로 실행: 해시 목록 완전성·기존 릴리스와 내용 동일성
```

`db.py`는 원문 릴리스 ID 계산에 들어가므로 고치면 새 릴리스 ID가 생긴다. 기존 청킹 묶음은 `chunking.DEFAULT_RELEASE`에 고정된 원문 릴리스를 계속 쓰며, 새 릴리스로 옮기려면 청킹을 새로 만들고 적재해야 한다.

## 근거 조회(3단계)

- 코드 `src/evidence.py`(읽기 전용, 임베딩·외부 API 없음), 사전 기대값 `checks/expected_evidence.json`, 검사 `checks/verify_evidence.py`, 다음 단계 평가 질문 `eval/new_questions_2026-10-12.json`(20문, 구현 조정에 쓰지 않음).
- 입력: 청킹 묶음 ID, 청크 ID 목록, 참조 깊이(0~2, 기본 1), 문맥 예산(추정 토큰, 기본 4000). 청킹 묶음이 연결한 원문 릴리스(`PINNED`)만 쓰고 다르거나 미완료면 거부한다. `out/input_manifest.json`(최근 적재 기록)은 보지 않는다.
- 결과 JSON: `units`(조회 자료 전체), `answer_context`(예산 안에 담은 단위와 글), `excluded`(제외한 조각과 사유), `references`(참조 문장·조건·출처·대상 상태·후보), `unresolved_references`(깊이·예산·모호·부분·없음), `coverage`, `quality_flags`. 시각이 없어 같은 입력이면 같은 결과다.
- 적용 여부는 판단하지 않는다(`applicability=unknown`). 대상 확인(`target_status`)·관계 확정(`link_state`)·정상 계산 근거 여부(`normal_calculation_basis`)는 서로 다른 값이다.
- 따라가는 것: 구조로 확정된 부모·자식 표, 위치 근거 설명·주석 표 후보(미확정 표시), `resolved`·`partial` 참조의 확정 대상(role=target). 따라가지 않는 것: 모호 후보, 없음·범위 밖, 소속 미확정 설명, 잘못된 길어깨 관계 15건.

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/evidence.py t:full-p185-o18870 --depth 1 --budget 4000 --text
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_evidence.py
```

## 임베딩·결합 검색(4단계)

- 코드: `src/embed_index.py`(문서 임베딩·캐시·재개), `src/retrieve.py`(BM25+벡터 RRF, 근거 조회 연결), 검사 `checks/verify_embeddings.py`·`checks/verify_search.py`, 평가 `checks/eval_search.py`, 개발 질문 사본 `eval/dev_questions_2026-10-10.json`.
- 임베딩 호출은 공통 경로 `backend/shared/embedding.py`(두 키 번갈아 사용, 429 시 다른 키)를 쓴다. 키 값은 출력하지 않는다.
- 입력: DB `chunks.text`를 `title: none | text: …`로 포장(문맥이 text에 있어 제목을 다시 넣지 않음). 캐시 키는 입력 전체 SHA-256 + 제공자·모델·차원·입력 형식·용도. 벡터는 float32 base64로 `out/embeddings/<청킹 묶음>/<제공자-모델-차원-입력형식>/cache.jsonl`에 호출 직후 추가한다.
- **한도**: 무료 등급 키는 모델당 하루 입력 1,000개까지다(`GEMINI_API_KEY_SEC`). 유료 키(`GEMINI_API_KEY`)와 번갈아 쓰며 무료 키가 429면 공통 경로가 유료 키로 이어간다. 두 키가 모두 하루 한도면 바로 멈추고 같은 명령으로 재개한다(성공분은 다시 호출하지 않음).
- `ready`는 모든 검색 대상의 벡터와 입력 해시가 맞을 때만 true다(`manifest.json`). ready가 아니면 `Retriever(vectors=True)`는 거부한다.

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/embed_index.py plan       # 호출 없음
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/embed_index.py run        # 이어서 생성(재개 가능)
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/embed_index.py export     # 전부 맞을 때만 ready, Parquet 저장
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_embeddings.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_search.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_search.py dev     # 개발: 기존 20문
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_search.py freeze  # 설정·코드 해시 고정(새 20문 평가 전)
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_search.py new     # 새 20문, 한 번만
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/retrieve.py "콘크리트 표면 마무리 기준"
```

## 근거 선택(4b)

- 코드 `src/select_evidence.py`(`Selector.run`): 후보 점수(벡터+BM25, 세 종류 조각 전체) → 질문 목적 신호(목록·값·규칙) → 목록은 범위 공종 집합 확장, 값·규칙은 절 안에서 조각 선택(앞 소제목·단위 기준·주석 표 대조) → `evidence.Reader`로 구조 연결 읽기 → 근거 충분성 확인 → 추가 검색(질문 전체 최대 2회, 상위 묶음 하위 절 탐색 포함).
- 상태: `supported`(근거 있음) / `needs_confirmation`(근거 부족·확인 필요) / `not_found`(관련 근거를 찾지 못함, 가까운 후보는 `diagnostic_*`에만).
- 평가: `checks/eval_selection.py`(`dev`·`freeze`·`new`), 동작·보존 `checks/verify_selection.py`. 질문 집합 역할은 `eval/question_roles_04b.json`, 작업 전 보관 `baseline/before-04b/`, 4b 고정 기록 `eval/freeze_step04b.json`(과거 `freeze_step04.json`은 그대로).
- 코드는 질문 ID·정답 조각·참조 ID를 쓰지 않는다(`verify_selection.py`가 검사).

```powershell
.venv\Scripts\python.exe -B experiments/retrieval-v1/src/select_evidence.py "콘크리트 표면 마무리 기준"
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/verify_selection.py
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_selection.py dev
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_selection.py freeze
.venv\Scripts\python.exe -B experiments/retrieval-v1/checks/eval_selection.py new   # 새 4b 질문, 한 번만
```

## 근거 선택 소규모 비교(4c)

- 실험 폴더 `pilots/step04c/`: 질문 12개 고정 `freeze_questions.py`→`expectations_fixed.json`, 공통 후보·문맥 `build_candidates.py`, 기존 서비스 언어 모델 호출 `llm_select.py`(`backend.agent.tools.llm.client.generate` 그대로, 상한 $2·50회, 호출 전 `precall_estimate.json`), 평가 `evaluate.py`, 표 `make_tables.py`, 전후 보존 `preserve.py`.
- 결과: `docs/reviews/retrieval-step-04c-selection-pilot-result-2026-10-12.md`. 전용 재순위(Voyage)는 키가 없어 **미실행**.
- 12문은 이미 본 개발 자료다(독립 평가·전체 정확도 아님). 기존 코드·고정 기록·출력은 바꾸지 않았다.

## 검증형 근거 선택(4d, 실험용 경로)

- 코드 `src/select_verified.py`(`VerifiedSelector.run`): 결합 검색 후보 + 구조 문맥(표 앞 제목 줄, 다른 표 제목 줄 표시, 소유 경쟁) → 서비스 언어 모델이 후보·줄·행 **식별자**로 주·보조 근거를 고름 → 코드가 식별자·소속·버전을 검증하고 인용을 DB에서 가져옴 → 최종 상태는 선택한 근거의 의존 관계(소속 미확정·수식 미확정·부분/모호/없는 참조·표 대상 근거의 소유 경쟁·예산)로 결정. 목록은 기존 절 계층 조회 후 절별 포함·제외·판단 보류. 추가 조회는 질문당 최대 2회.
- 실행·평가: `pilots/step04d/`(`run_4d.py`, `evaluate_4d.py`, `compare_4d.py`, `verify_4d.py`, `replay_4c.py`). 운영 상한 $5·200회, 원장 `ledger.jsonl`, 결과 `runs/<run_id>/`.
- 결과: `docs/reviews/retrieval-step-04d-verified-selection-result-2026-10-12.md`. 60문은 개발·회귀 자료이며 독립 평가가 아니다.

## 남은 선택·조회 문제의 제한된 마무리(4e, 실험용 경로)

- 코드 `src/select_verified.py`(4d 위에 변경): 문서 순서상 인접 설명을 위치 근거(미확정)로 인정, **확인용 문맥**(선택한 근거와 구조상 연결된 주석 표·수식/소속 미확정 조각을 정상 계산 근거와 별도로 보존), 번호만 있는 질문의 **구조 조회 대안**(`division_choice_required`, 모델 호출 없음), 낱말 부재를 **거부 사유가 아닌 부족 신호**로 처리(`alias_confirmed` / `target_term_unconfirmed` / `term_absent_in_corpus`), 근거 역할 `confirmed`·`confirmation_only` 구분.
- 실행·평가: `pilots/step04e/`(`run_4e.py replay|run`, `evaluate_4e.py`, `evaluate_dev_4e.py`, `verify_4e.py`, `preserve.py`). 상한 30회·$1, 원장 `ledger_4e.jsonl`. 4d 캐시·원장은 읽기 전용.
- 결과: `docs/reviews/retrieval-step-04e-targeted-finish-result-2026-10-12.md`. 60문 최종 확인에서 필수 근거 55/55(확정 33·확인용 선택 7·확인용 문맥 4·조회 11), 금지 0, 정상 거부 0, 승격 0이나 **N19 자료 없음 `not_found` 미달(4/5)**과 낱말 어미 오판으로 **V13·V18 보류 부작용**이 남았다(최종 확인 뒤 지시에 따라 고치지 않음). 개발·회귀 자료이며 독립 평가가 아니다.

## 질문 대상·작업·요청 표현 구분과 부문 범위 판정(4f, 실험용 경로)

- 코드 `src/select_verified.py`(4e 위에 변경): 질문 어절을 어간·꼬리로 나눠 **역할**(번호·부문·요청 표현·대상·작업·부정·조건)을 기록하고 어간만 원문 부재를 판정(`question_roles`, `absent_terms`), **번호 + 일반 질문 표현**에서도 같은 번호 본문 절 후보를 조회해 구별 제목이 없으면 부문별 대안(`number_lookup`, 모델 호출 0), 원문에 없는 대상 낱말이 있는데 근거가 선택된 경우 **대상 대조**(`target_compare`, 작은 별도 호출, 다름 + 유효한 줄 근거만 답변 문맥에서 제외), 부정 표지 `negation_unverified`.
- 실행·평가: `pilots/step04f/`(`run_4f.py replay|run`, `evaluate_4f.py`, `evaluate_dev_4f.py`, `verify_4f.py`, `preserve.py`). 상한 20회·$1, 원장 `ledger_4f.jsonl`. 4d·4e 캐시·원장은 읽기 전용.
- 결과: `docs/reviews/retrieval-step-04f-question-scope-result-2026-10-12.md`. 60문 최종 확인에서 필수 근거 55/55(확정 34·확인용 선택 6·확인용 문맥 4·조회 11), 금지 0, 정상 거부 0, 승격 0, 자료 없음 5/5(N19는 대조 판정 1회에 기댐). 개발 사례 18/19(F03은 고정 기대 목록 누락 + 부정 조건 불필요 보류). 개발·회귀 자료이며 독립 평가가 아니다.

## 새 질문 20개 평가(4g, 코드 수정 없음)

- 코드 4f 최종(`select_verified.py` `dc011b6d…`)을 그대로 두고 원문 DB·PDF를 읽어 고정한 새 질문 20개(`eval/questions_04g_2026-10-12.json`, 기대값 `expected_04g_…`, 근거 확인 `evidence_check_04g_…`)로 검색→선택→검증→조회→최종 문맥을 실행. 실행·평가 `pilots/step04g/`(`run_4g.py`, `evaluate_4g.py`, `freeze.py`), 상한 80회·$2, 원장 `ledger_4g.jsonl`.
- 결과: `docs/reviews/retrieval-step-04g-independent-evaluation-result-2026-10-12.md`. 20문 중 18 통과, 필수 근거 문맥 포함 11/13(84.6%, 목표 95% 미달), 금지 혼입 0·정상 거부 0·승격 0·자료 없음 4/4. 결론은 **일부 유형만 시험 가능**. F03 기대값 오류 기록 `docs/reviews/retrieval-step-04g-f03-expectation-correction-2026-10-12.md`. 20문 표본이며 전체 정확도가 아니다.

## 근거 보존·대조 권한 제거·목록 완전성 분리(4h, 실험용 경로)

- 코드 `src/select_verified.py`(4g 위에 변경): 질문 어절을 원문 그대로 보존하고 어간·꼬리는 약한 분석으로만 기록(`spec_connector` 역할로 `짜리` 등 분리), 추가 대조 모델은 **경고만**(`mode: advisory`, 근거 제거·승격·자동 `not_found` 경로 삭제), 전달 문맥을 정상 답변 근거·검토용 원문·진단 후보로 구분(`answer_evidence_chunks`, `review_chunks`, `diagnostic_candidates`), 소속 미확정 설명만 선택돼도 인접 설명 연쇄가 닿는 표를 검토용으로 조회(`retained_review`), 목록 `candidates_processed`와 `scope_completeness`(`unverified`/`partial`) 분리.
- 실행·평가: `pilots/step04h/`(`run_4h.py replay|run`, `evaluate_4h.py`, `evaluate_g20_4h.py`, `verify_4h.py`, `freeze.py`). 상한 30회·$1, 원장 `ledger_4h.jsonl`.
- 결과: `docs/reviews/retrieval-step-04h-evidence-retention-result-2026-10-12.md`. 4g 20문(개발·회귀 전환) 필수 13/13, 60문 필수 55/55 유지, N19는 정책상 needs_confirmation, **G02 새 불필요 보류** 남음. 4g 최초 독립 결과(18/20, 11/13)와 분리해 기록. 새 독립 평가는 하지 않았다.

## 보류 권한 비교(4i, 저장 응답 재생·정책 변경 없음)

- `pilots/step04i/`: `select_verified_cmp.py`(현재 코드 복사본 + 권한 스위치 `AUTH`), `run_4i.py`(캐시 재생·로컬 아닌 연결 차단), `compare_4i.py`. 약한 낱말 부재 권한과 대조 경고 권한을 해제하는 네 방식(가 기준선·나·다·라)을 60문·4g 20문·개발 사례에 재생. 새 모델·임베딩 호출 0.
- 결과: `docs/reviews/retrieval-step-04i-status-authority-comparison-result-2026-10-13.md`. 두 문제(G02 불필요 보류, N19 잘못된 근거 승격)를 함께 해결하는 방식 없음. 다=가, 나는 G02 미해결+E02·E03·H1 승격, 라는 G02 해결+N19 무관 표 2개 정상 근거 승격+3건 승격. 추천: 현재 기본(가) 유지. 기본 정책은 바꾸지 않았다.

## 로컬 서비스 시험 연결(5단계, 검색 정책 변경 없음)

- 코드: `backend/api/local_trial.py`(기본 꺼짐 `LOCAL_TRIAL_RETRIEVAL=on`, 독립 앱 `backend.api.local_trial:app`, 원격 저장·사용량·분석 미사용), `backend/api/main.py`(+5줄, 옵션 켜졌을 때만 라우터 연결), 화면 `frontend/src/components/LocalTrial.tsx`(`REACT_APP_LOCAL_TRIAL=on`, 경로 `/trial`). `select_verified.py`(4h) 변경 없음.
- 실행·결과: `pilots/step05/`(`run_trial_05.py`, `trial_results_05_final.json`, `trial_log.jsonl`, `ledger_05.jsonl`, `preserve.py`). 시험 `checks/test_local_trial_05.py`(16), `frontend/src/components/LocalTrial.test.js`(4). 상한 60회·$2 중 29회·약 $0.06.
- 결과: `docs/reviews/retrieval-step-05-local-service-trial-result-2026-10-13.md`. 고정 10문 상태 10/10(G02·N19는 현재 한계 그대로 표시), 정상 답변 3문 실제 모델 설명 후 원문 대조, 브라우저 4개 흐름 확인. 설명 검증 실패 시 원문 표시로 전환(27회 중 6회). 기존 상담 경로 비교는 원격 연결이 필요해 미실행. 서비스 연결 시험이며 검색 정확도·배포 승인이 아님.

## Git 보존 범위

검색·검증·실행 코드, SQL, 교정 자료, 고정 질문과 기대값, 최종 요약·설정·해시 및 단계별 문서는 Git에 보관한다. 원문 출력·벡터·기준선 복사·모델 응답·실행 로그·이미지는 로컬에 그대로 두고 Git에서 제외한다. 일부 저장 결과 검사는 해당 로컬 파일이 없으면 건너뛴다. 모델과 DB가 필요 없는 입력 검사는 코드와 함께 재실행할 수 있다.

전체 재생에는 고정 릴리스의 로컬 검증 DB와 `out/` 자료, 해당 실행 캐시가 별도로 필요하다. Git 체크아웃만으로 이 대용량 자료가 복구되지는 않는다. 운영 상담 전환은 아직 하지 않았으며 `/trial`은 기본 꺼짐인 로컬 시험 경로다.

## 규칙 요약

- 원문 레코드·표·칸·관계는 원래 JSON 그대로 보관하고, 원래 식별자를 노드 ID로 쓴다. 노드가 아닌 관계 끝점(제목 글자·행 선택자)은 원시 값만 두고 노드를 만들지 않는다.
- 절: 부문 표지 쪽으로 본문 부문 구간을 나누고, 본문의 번호 제목(`N-N-N`, `N-N`, `제N장`)만 절로 둔다. 목차 줄은 `toc_entries`에 따로 두고 대조만 한다. 같은 번호라도 부문이 다르면 다른 절이다.
- 참조: 부문·번호·제목·하위 항목을 대조해 `resolved/partial/ambiguous/missing/external`로 둔다. 애매하면 후보만 저장한다. 기존 `confirmed=false`는 그대로이며, 적용 여부는 저장하지 않는다(질문별 판단).
