# 답변 실행 기록 조회와 평가 반영

## 평가에서 실행과 단계 찾기

Supabase SQL Editor에서 먼저 답변 식별자로 평가와 실행을 찾습니다. 여기에는 사용자 질문·답변이 포함되므로 접근이 허용된 운영자만 조회하세요.

```sql
select f.answer_id, f.rating, f.reason, f.review_status, f.error_type,
       f.review_note, f.expected_evidence, f.reviewed_by, f.reviewed_at,
       f.eval_question, f.expected_result, f.eval_approved_by, f.eval_approved_at,
       r.id as run_id, r.status as run_status, r.answer_status, r.started_at,
       r.finished_at, r.environment, r.agent_mode, r.versions, r.capture_status,
       r.expires_at
from public.answer_feedback f
left join public.answer_runs r on r.id = f.run_id
where f.answer_id = 'REPLACE-WITH-ANSWER-UUID'::uuid;
```

`run_id`가 비어 있으면 당시 로그가 수집되지 않은 과거 답변이거나 로그 저장에 실패한 경우입니다. 과거 로그나 버전을 추측해 채우지 마세요. 실행 상태가 `running`이고 종료 정보가 없으면 프로세스가 중간에 종료된 실행입니다. `capture_status='partial'` 또는 요약 안의 `_truncated` 표시는 누락 가능성을 뜻하며, 모델의 정답 여부를 뜻하지 않습니다.

위 결과의 실행 UUID를 단계 조회에 넣습니다. 순서, 부모 단계, 같은 이름의 반복 실행, 시간, 제한된 입력·출력 요약, 상태와 모델 호출 metadata를 확인할 수 있습니다.

```sql
select sequence, id as step_id, parent_step_id, step_kind, name,
       started_at, finished_at, duration_ms, status,
       input_summary, output_summary, error_code, error_type, metadata
from public.answer_run_steps
where run_id = 'REPLACE-WITH-RUN-UUID'::uuid
order by sequence;
```

테이블은 RLS가 켜져 있고 `anon`, `authenticated`, `public`의 권한을 회수했습니다. 애플리케이션의 서비스 역할과 승인된 운영자만 조회하세요. 일반 사용자 API는 이 테이블을 반환하지 않습니다.

## 검토 기록

오류를 확인한 뒤에만 피드백 행을 검토 완료로 바꿉니다. `expected_evidence`는 원문 출처 식별자와 페이지·표·행·열 및 확인한 값을 담는 JSON 배열입니다. `error_type`은 `retrieval`, `calculation`, `explanation`, `other` 중 하나입니다. 검토자 이름 대신 조직의 운영자 식별자를 기록하세요. 기대 결과가 불명확하면 평가 사례로 승인하지 않습니다.

```sql
update public.answer_feedback
set review_status = 'resolved',
    error_type = 'calculation',
    review_note = '오류 원인과 수정 근거를 검토한 요약',
    expected_evidence = '[{"source_id":"p186-t1","page":186,"row":"작업조","column":"콘크리트공","value":"4","unit":"인"}]'::jsonb,
    reviewed_by = 'ops-reviewer-01',
    reviewed_at = now()
where answer_id = 'REPLACE-WITH-ANSWER-UUID'::uuid;
```

평가 도구로 보낼 사례는 원문과 별도로 개인정보를 제거한 `eval_question`, 기대 상태, `numbers` 객체(수치 기대값이 없으면 `{}`), `unit`(없으면 `null`), 필요한 입력 및 출처 근거를 운영자가 직접 작성합니다. QA 기대값에는 `division`과 `section_no`를 둡니다. 견적 기대값에는 `spec_id`와 검토한 `input` 조건을 두고, `unit`에는 계산 기준 단위나 품 줄별 단위를 기록합니다. 예: `{"task":"estimate","status":"computed","numbers":{"daily_volume_m3":"130","work_days":"2"},"unit":{"unit_basis_per":"1㎥"},"spec_id":"...","input":{"volume":"260"}}`. 그 사례의 정확성과 개인정보 제거를 다시 확인한 뒤 `eval_approved_by`, `eval_approved_at`을 기록하세요. 이 검토·승인 없이 제보를 정답으로 취급하거나 학습 자료로 쓰지 않습니다.

승인된 사례만 외부의 명시한 위치로 JSONL 내보낼 수 있습니다. `.env`의 DB 연결을 사용합니다. 이 명령은 질문·답변 원문이나 이메일, 계정 ID를 선택하지 않으며 저장소 안의 경로로 내보내기를 거부합니다.

```powershell
python evals/export_reviewed_answer_cases.py --target local --output C:\reviewed-cases\answer-feedback.jsonl
```

운영 DB를 읽을 때만 `--target supabase`를 사용하세요. 각 사례는 `id`, `label`, `question`, `expected`, `sources`를 가진 JSONL 행입니다. QA 행은 `division`·`section_no`를 포함해 `evals/eval_qa.py --cases <파일>`로 전달할 수 있습니다. 견적 행은 `spec_id`·입력 조건·예상 상태와 숫자를 포함해 `evals/check_spec_cases.py --cases <파일>`로 전달할 수 있습니다. 외부 사례 옵션을 줄 때만 해당 평가를 실행합니다. QA 비교는 `AGENT_LLM=on`이 필요하며 기본 검사는 AI를 호출하지 않습니다. 내보낸 파일은 Git에 자동 추가하지 말고, 수정 전후 비교 세트에 넣기 전에 운영자가 개인정보와 기대 결과를 다시 확인하세요. 이 절차는 자동 학습, 자동 배포 또는 자동 반복 평가를 실행하지 않습니다.

## 배포 전 마이그레이션

이미 적용된 초기 `20261014000100_answer_runs.sql`을 수정하지 않습니다. 로컬 계획에서 `20261014000100`이 이미 적용되었는지, `20261014000200`만 남았는지 확인한 뒤 순서대로 실행하세요.

```powershell
python deploy/apply_answer_runs.py --target local
python deploy/apply_answer_runs.py --target local --apply
python deploy/apply_answer_runs.py --target supabase
python deploy/apply_answer_runs.py --target supabase --apply
```

원격 실행 전 계획 출력에 나타난 적용 목록이 승인된 두 파일과 일치하는지 확인하세요. 변경 파일은 `supabase/migrations/20261014000100_answer_runs.sql`, 이어서 `supabase/migrations/20261014000200_answer_run_steps.sql`입니다. 초기 파일은 기존 로컬 DB에서 발견되지 않을 때만 필요한 환경에 적용됩니다. 기존 피드백·메시지 행 수를 전후 비교하며, 과거 단계 이력은 만들지 않습니다.

## 보관과 장애

정리 작업은 기본 90일이 지난 피드백을 먼저 지우고, 아직 보관 중인 평가와 연결된 실행은 평가 보관 기한까지 유지합니다. 실행 단계는 실행 삭제와 함께 삭제됩니다. 회원 대화·계정 삭제는 FK cascade로 기록을 지우고, 확인된 비회원 대화 삭제도 해당 평가와 실행을 지웁니다. 로그 DB 장애는 상담 응답을 중단시키지 않고 실행 UUID와 실패 유형만 서버 경고에 남깁니다. 시작 행 이후 종료 정보가 없는 실행은 `running`으로 남을 수 있습니다.
