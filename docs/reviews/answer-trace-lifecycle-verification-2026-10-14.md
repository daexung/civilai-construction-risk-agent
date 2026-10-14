# 실행 로그의 복원·이전·삭제 확인

날짜: 2026-10-14

## 범위와 결과

로컬 Supabase `127.0.0.1:54322`에서 시험 계정과 대화를 만들어 확인했다. 운영 DB, 외부 모델, 원격 인증 서비스는 사용하지 않았다. 인증 사용자 판정과 계정 삭제용 인증 서버 응답은 시험 자료로 대체했고, 상담 API 처리 함수와 DB 저장·이전·삭제 경로는 실제 코드를 사용했다.

- `evals/test_answer_runs.py`: pytest로 5개 통과.
- `evals/test_answer_trace_lifecycle.py`: pytest로 3개 통과.
- `evals/check_answer_trace_offline.py`: 그래프 단계 4개, 도구형 단계 4개 수집 및 결과 유지 확인 통과.
- `git diff --check`: 통과.

## 추가 확인

1. 과거 `execution` 필드를 가진 회원 답변을 DB에 저장하고 대화 조회 API를 실행했다. 응답에는 내부 필드가 없었고 저장된 과거 자료는 그대로였다.
2. 같은 요청 번호로 상담 API를 다시 호출했다. 상담을 재실행하지 않고 기존 답변을 반환했으며 내부 필드는 없었다. 해당 답변의 실행 기록도 한 개로 유지됐다.
3. 실제 로컬 상담 API로 만든 비회원 실행 기록을 확인했다. 틀린 비회원 비밀값으로 삭제하면 거부됐고 기록이 유지됐다. 올바른 값으로 삭제하면 실행과 단계가 함께 삭제됐다.
4. 비회원 대화 이전 API를 실행했다. 실행 기록의 회원·대화·스레드 소속이 새 회원 대화로 함께 바뀌고 단계가 유지됐다. 회원 대화 삭제 후 실행과 단계가 모두 사라졌다.
5. 계정 삭제의 재인증 확인·삭제 함수를 실행했다. 인증 서버 삭제 요청은 로컬 시험 계정 삭제로 대체했다. 대화에 연결된 실행뿐 아니라 답변·대화가 없는 회원 실패 실행도 함께 삭제됐다.

시험 계정과 비회원 실행 자료는 정리했다. 모델 호출이나 유료 비용은 없었다. 샌드박스에서 로컬 소켓 접근이 거부되어 권한을 받아 같은 검사를 다시 실행했으며, 최종 결과는 8개 통과였다. pytest는 기존 무시 경로 `tmp/pr-check-deps`의 설치본을 사용해 의존성 파일을 바꾸지 않았다. 라이브러리의 Python 3.16 관련 폐기 예정 경고 13개가 있었고 검사 실패는 없었다.

## 변경과 남은 범위

이번 작업은 검사 파일과 이 결과 문서만 추가했다. 운영 코드, 다른 세션의 수정, 대시보드 계획은 변경하지 않았다. 커밋·푸시·PR·운영 마이그레이션·배포는 하지 않았다.

이 결과는 로컬 기록 수명과 응답 분리의 확인이다. 실제 Google 로그인·운영 인증 서버의 계정 삭제, 실제 모델 재시도, 운영 환경의 저장 크기·지연은 확인하지 않았다. PR 전 전체 변경 검토와 운영 적용 후 확인은 별도다.

## 다시 실행

저장소 폴더의 PowerShell에서 실행한다. 로컬 DB가 실행 중이어야 한다.

```powershell
$env:PYTHONPATH="$PWD\tmp\pr-check-deps;$PWD"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:CHAT_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:54322/postgres'
$env:AGENT_OFFLINE='1'
$env:AGENT_LLM='off'
$env:QUOTA_HASH_SECRET='local-lifecycle-fixture'
.venv\Scripts\python.exe -m pytest evals/test_answer_runs.py evals/test_answer_trace_lifecycle.py -q --tb=short
.venv\Scripts\python.exe evals/check_answer_trace_offline.py
```
