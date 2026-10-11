# Sonnet 후속 지시서: 생성 번호에 빠진 입력 반영

작성일: 2026-10-10

이 지시는 이미 승인된 표 후처리와 원문 구조 보존 첫 작업의 생성 기록을 보완하는 것이다. 다음 단계의 구현을 시작하는 지시가 아니다.

## 먼저 읽을 자료

원본 저장소:

`C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent`

1. `docs/reviews/table-structure-preservation-review-2026-10-10.md`
2. `docs/reviews/table-structure-preservation-result-2026-10-10.md`
3. 기존 첫 지시서 `docs/handoffs/implement-table-structure-preservation-2026-10-10.md`의 실행 조건과 제외 범위

## 고칠 내용 한 가지

작업 폴더:

`C:\Users\user\Desktop\PROJECTS\_table-structure-preservation-2026-10-10`

`checks/run_export.py`의 `generation()`은 입력 기록에 `page_map.json` 해시를 남기지만 생성 번호의 `key`에는 포함하지 않는다. 같은 파일의 `run()`에서 이 파일로 청크의 부문을 정하므로, 부문 정보 내용이 바뀌면 다른 결과에 같은 생성 번호가 붙을 수 있다.

생성 번호의 근거에 `page_map.json`의 내용 해시를 포함하도록 수정한다. 가능하면 입력 기록의 해시에서 생성 번호의 근거를 가져와 두 목록이 어긋나지 않게 한다. 입력 파일의 경로만 달라지고 내용이 같으면 같은 입력으로 다룬다.

기존 `assemble.py`, `structure_store.py`, `structure_export.py`, 의존 코드와 실제 입력 파일은 수정하지 않는다. 행 분리나 머리글 규칙을 다시 바꾸지 않는다.

## 이번 수정 범위

- 전용 폴더의 `checks/run_export.py`
- 이 변경만 확인하는 작은 기능 확인 코드가 필요하면 전용 폴더의 `checks/`에 추가
- 전용 폴더의 `out/`에 수정 전 결과 보존, 이번 diff와 확인 결과, 현재 입력의 새 생성 결과 저장
- 원본 저장소의 `docs/reviews/`에 이번 결과 보고서 하나 추가

수정 전 출력은 전용 폴더 안에서 별도 보존한다. 원본 데이터나 기존 다른 작업 폴더는 변경하지 않는다. 폴더가 예상 상태와 다르면 사용자 작업을 덮어쓰지 않는다.

## 필요한 확인만 수행

1. 같은 입력 해시·쪽·코드로 생성 번호를 두 번 만들면 동일하다.
2. ODL·쪽·코드는 그대로 두고 부문 정보의 내용 해시만 바꾸면 생성 번호가 달라진다. 실제 `page_map.json`을 바꾸지 않고 메모리의 입력 또는 전용 폴더의 작은 가상 입력으로 확인한다.
3. 현재 입력으로 `dev3`와 `regress12` 결과를 다시 생성한다. 기존 원시 ODL 출력만 사용하고 새 파싱은 하지 않는다.
4. 생성 번호와 이에 종속된 레코드·관계 식별자 변경을 제외하면, 수정 전후 보관 내용·레코드 글과 구조·청크 내용·원문 연결 관계가 같다. 식별자 변화는 일관된 대응으로 비교하고 글이나 다른 필드를 통째로 제외해 비교하지 않는다.
5. 각 결과 묶음의 보관 자료·레코드·청크·연결 정보가 새 생성 번호로 일치한다.

원래 89개 전체 검사나 PDF 원문 대조를 다시 실행하지 않는다. 위 확인에 실패해 기존 내용이 달라졌다면 원인을 보고하고 범위를 임의로 늘리지 않는다.

## 실행 조건

기존 Python과 `AGENT_OFFLINE=1`, `AGENT_LLM=off`, `PYTHONDONTWRITEBYTECODE=1`, Python `-B`를 사용한다.

실제 입력 자료·완료 패치·기존 시제품·원본 추적 파일은 변경하지 않는다. 전체 재처리·외부 API·운영 접속·설치·다운로드·환경 변경·비밀값 접근·커밋·푸시·배포는 금지 조건을 유지한다.

## 결과 보고와 종료

보고서:

`C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\docs\reviews\table-structure-generation-id-fix-result-2026-10-10.md`

기존 문서가 있으면 덮어쓰지 말고 새 이름으로 기록한다. 쉬운 한국어로 작성하고 한자를 사용하지 않는다.

고친 이유, 실제 diff, 수정 파일 범위, 확인 결과, 새 생성 번호, 식별자를 제외한 결과 유지 여부, 기존 입력·데이터·운영의 미변경 상태를 보고한다. 과거 89개를 새로 통과시켰다고 쓰지 않는다.

결과를 제출하면 종료한다. 다음 작업과 운영 전환은 시작하지 않는다.
