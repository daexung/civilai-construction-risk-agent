# 3단계 항목별 품 흐름 결과

## 작업 위치와 범위

- 시작 커밋: `cba36bf` (`Add confirmed scope analysis workflow`)
- 작업 브랜치: `codex/item-labor-flow`
- 이전 `EstimateSession`은 여러 항목을 담을 수 있지만 `tools._item()`과 기존 품 도구는 첫 항목만 사용합니다. 기존 상태를 한 세션으로 묶어 넘기지 않고, 확인된 범위 ID마다 단일 항목 `EstimateSession`을 만들었습니다. 검색·후보 결정·조건 질문·품 계산은 기존 `find_work`, `set_conditions`, `compute_labor`를 사용합니다.
- `claude/multi-work-estimate` 브랜치는 읽기만 했습니다. 큰 별도 변경 묶음은 합치지 않았습니다.
- 운영 `backend/api/main.py`와 기본 상담은 바꾸지 않았습니다. 새 독립 FastAPI 시험 경로만 추가했습니다. 회원 세션, 운영 저장, 로그, 사용량 차감 계약은 변경하지 않았습니다.
- 외부 모델·검색·임베딩·API·DB 호출은 없었습니다. 검색 후보는 HTTP body로 넣은 고정 모의 후보이고, 표와 쪽 인용은 원본 저장소의 기존 자료를 읽기 전용으로 참조했습니다.

## 실행과 요청 예

로컬에서만 실행합니다. `PYTHONPATH`의 첫 경로는 이 worktree여야 합니다.

```powershell
$env:PYTHONPATH = "<worktree>;<기존 .venv의 site-packages>"
$env:LOCAL_TRIAL_ITEM_LABOR = "on"
python -m uvicorn backend.api.item_labor_trial:app --host 127.0.0.1 --port 8011
```

옵션이 꺼져 있거나 `APP_ENV=production`, `K_SERVICE`, `K_REVISION` 중 하나가 설정됐거나 요청 원격 주소가 loopback이 아니면 시험 API가 404를 반환합니다. 이 모듈은 기본 운영 앱에 포함되지 않습니다.

1. 분석:

```powershell
$a = Invoke-RestMethod -Method Post http://127.0.0.1:8011/api/item-labor/analyze `
  -ContentType application/json `
  -Body '{"text":"수성페인트 롤러칠 2회 벽면 100㎡ 그리고 실내 방수모르타르 10㎜ 바닥 20㎡"}'
$a.analysis.scope_spans
```

2. 반환된 모든 `span_id`를 보고 명시적으로 확인합니다. 요청 작업은 `include_work`, 수량·조건은 `keep_condition`, 바탕은 `keep_background`, 제외는 `keep_excluded`를 보냅니다. 미확정 구절을 작업으로 넣으려면 해당 원문 안의 작업 이름을 함께 보내야 합니다. 예를 들어 모르타르 구절을 방수 작업으로 확인할 때는 `{"span_id":"<반환 ID>","action":"include_work","work":"방수"}` 형태입니다.

```powershell
$confirmed = Invoke-RestMethod -Method Post "http://127.0.0.1:8011/api/item-labor/$($a.trial_id)/confirm" `
  -ContentType application/json -Body (@{ decisions = $decisions } | ConvertTo-Json -Depth 10)
$confirmed.items
```

3. 각 항목의 `item_id`로 후보를 검색합니다. 아래 후보는 로컬 모의 검색 결과입니다. 실제 시험에서는 적용할 명세 절을 먼저 정하고 해당 절을 넣습니다.

```powershell
$hits = @(@{ section_no='11-2-2'; division='건축'; rank=1;
  section='11-2-2 수성페인트 롤러칠'; chunk_id='mock-paint'; score=1 })
$result = Invoke-RestMethod -Method Post "http://127.0.0.1:8011/api/item-labor/$($a.trial_id)/items/$itemId/search" `
  -ContentType application/json -Body (@{ hits = $hits } | ConvertTo-Json -Depth 10)
```

4. 응답에 질문이 있으면 그 항목에서 반환한 최신 질문 ID와 버전을 그대로 답합니다. `unit`을 생략하면 질문에 적힌 단위로 해석합니다. 단위를 보내면 명세 단위와 같거나 기존 별칭 표에서 같은 단위로 확인되는 값만 허용합니다. 예를 들어 면적 질문에 `m`은 422로 거절되고 질문은 그대로 남습니다.

```powershell
$q = $result.items[0].questions[0]
$answer = Invoke-RestMethod -Method Post "http://127.0.0.1:8011/api/item-labor/$($a.trial_id)/items/$itemId/answer" `
  -ContentType application/json -Body (@{ question_id=$q.question_id; version=$q.version;
    value=$false; unit=$q.unit } | ConvertTo-Json -Depth 10)
```

현재 상태는 `GET /api/item-labor/{trial_id}`에서 확인합니다. 수정은 항목의 `input_revision`과 함께 `POST .../items/{item_id}/edit`로 보내며, 해당 항목만 다시 `confirm-edit` 해야 계산이 이어집니다. `POST .../reorder`는 현재 항목 ID를 새 순서로 받습니다. 상태는 프로세스 메모리에만 있어 서버를 다시 켜면 사라집니다.

## 실제 고정 사례와 결과

실행 명세 파일은 `data/drafts/specs/건축/11-2-2.json`과 `data/drafts/specs/건축/6-4-3.json`입니다. 양쪽 모두 `AI 초안 · 검토 전` 표기와 원문 표 인용을 유지했습니다.

입력은 다음과 같습니다.

```text
수성페인트 롤러칠 2회 벽면 100㎡ 그리고 실내 방수모르타르 10㎜ 바닥 20㎡
```

두 항목은 각각 `CALCULATED`가 됐습니다. 기존 계산기의 `labor.unit_lines[].applied`는 물량당 품이고, 전체 작업 품량은 그 값에 해당 항목 물량을 적용한 값입니다. 시험 응답에는 계산기 원본의 단위 품 줄과 물량을 구분해 반환하며, 검사는 이 둘로 기대 인·일을 대조했습니다. 서비스에 새 품 계산식은 추가하지 않았습니다.

| 항목 | 선택 절 / 표 | 물량 | 기존 도구의 단위 품 | 물량 기준 대조값 |
|---|---|---:|---|---|
| 수성페인트 롤러칠 2회 | 건축 11-2-2 / `p693-t1` | 100㎡ | 도장공 0.024, 보통인부 0.004 인/㎡ | 도장공 2.4, 보통인부 0.4 인·일 |
| 실내 방수모르타르 10㎜ | 건축 6-4-3 / `p662-t2` | 20㎡ | 미장공 0.047, 보통인부 0.035 인/㎡ | 미장공 0.94, 보통인부 0.70 인·일 |

응답은 `selected_specification`, 원문 구간과 물량을 포함한 `evidence.source_spans`, 계산 도구의 `evidence.unit_lines`, 표·주석 인용 및 `labor.not_calculated`를 항목마다 반환합니다. 미산정 범위에는 바탕만들기·높이 할증·페인트/모르타르 재료량처럼 해당 명세가 별도 산정으로 남긴 항목이 포함됩니다. 이 `CALCULATED` 상태는 해당 작업의 기존 품 계산이 끝났다는 뜻이며 전체 견적 완료 표시는 아닙니다.

## 변경 파일

- `backend/api/item_labor_trial.py`: 시험 옵션이 있는 독립 HTTP 진입점, 항목별 단일 세션, 질문 ID/버전, 범위 수정 확인, 후보 모의 입력, 항목별 응답.
- `backend/agent/estimate/scope.py`: 서로 다른 단위의 조건은 확인 전 물량 하나로 고르지 않으며, 같은 원문 구간에 확인된 작업이 하나뿐인 경우에만 연결되지 않은 조건을 그 작업에 붙입니다. 같은 구간에 작업이 여럿이면 차단합니다.
- `evals/check_item_labor_trial.py`: 고정 후보를 넣은 HTTP 회귀.
- `docs/reviews/item-labor-flow-expectations.md`: 검사 전에 적은 기대값.
- `docs/reviews/item-labor-flow.md`: 이 결과와 실행 안내.

## 검사 결과

| 검사 | 결과 |
|---|---:|
| 신규 로컬 HTTP 흐름 | 21/21 통과 |
| 2단계 범위 확인·변경 무효화 회귀 | 22/22 통과 |
| 기존 품 도구 회귀 | 70/70 통과 |
| 기존 단일 공종 조건 회귀 | 11/11 통과 |
| Python 구문 검사 | 통과 |

신규 HTTP 검사는 옵션 꺼짐·배포 표식·원격 클라이언트 차단, 확인 전 계산 차단, 도장/방수 두 항목 계산, 같은 공종의 내부/외부 분리, 교차 항목/오래된 질문 거부, 작업 순서 변경, 동일 범위 확인 재요청의 멱등성, 한 항목만 수정·재확인, 제외 구절 거부, 연결되지 않은 바탕 차단, 단위 불일치 답변의 거부와 질문 보존을 확인합니다.

검사는 격리 환경의 Python 실행기가 사라진 uv 경로 경고를 출력했지만 종료 코드는 성공했습니다. HTTP 검사는 Windows의 로컬 소켓 제한 때문에 권한을 높인 in-process loopback ASGI 요청으로 실행했습니다. 원본 PDF·쪽 대응표·청크 자료는 읽기만 했습니다.

## 미확인과 다음 단계

- 지원 가능한 검색 후보를 실제 인덱스나 서비스에서 가져오지 않고 요청 body에 넣은 모의 후보로만 시험했습니다. 실제 검색 정확도와 모델 질문 문장은 미검증입니다.
- 두 명세는 실행 가능한 로컬 초안으로 표시되지만 `AI 초안 · 검토 전` 상태입니다. 시험 결과가 원문 명세의 독립 검수를 대신하지 않습니다.
- 기존 `per_unit` 도구는 물량당 품과 물량을 별도 반환합니다. 서비스 코드는 총 품을 새 계산식으로 만들지 않습니다. 검사는 도구가 반환한 `applied` 단위 품과 물량을 각각 대조하고 그 곱이 명세의 기대 인·일(도장 2.4/0.4, 방수 0.94/0.70)과 맞는지 평가했습니다.
- 새 세션은 프로세스 메모리에만 있고 사용자 소유권, 영속성, 대화 화면 연결이 없습니다. 운영 API에 연결하려면 인증·저장·사용량 정책을 별도 검토해야 합니다.
- 4단계에서 다룰 전체 합계, 공통 비용 배분, 통합 엑셀은 구현하지 않았습니다.
