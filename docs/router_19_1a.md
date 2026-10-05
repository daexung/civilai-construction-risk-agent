# 19-1a 라우터 검증

라우터는 견적(`estimate`), 품셈 상담(`qa`), 범위 밖(`out_of_scope`)을 분류한다. `AGENT_LLM=off` 또는 LLM 실패 시 기존 두 갈래 규칙으로 대체한다. 상담은 이번 단계에서 검색 근거만 보여주며 계산하지 않는다.

## 합격 기준

| 항목 | 기준 |
|---|---:|
| 전체 정답률 | 90% 이상 |
| 경계 문항 정답률 | 80% 이상 |
| 견적 → 범위 밖 오분류 | 0건 |
| 평균 라우팅 지연 | 1.5초 이하 |

## 오프라인 결과

원본 시험지 SHA-256: `9820132B9B034C53743A9A7117444D32B6F4992424A47A9E0FA3A85DB25D5DC7`. 실제 파일은 46문항이며 `boundary: true`는 20문항이다. 작업 지시문의 21문항 표기와 달랐지만 원본은 수정하지 않았다.

2026-10-03 규칙 전용 채점: 전체 25/46(54.3%), 경계 8/20(40.0%), 견적 → 범위 밖 2건, 평균 지연 0.0ms. 이 결과는 LLM 합격 판정이 아니다. 상세 결과는 `evals/results/router_2026-10-03.json`에 있다. 실제 LLM 채점은 이번 작업에서 실행하지 않았으므로 합격 여부는 미확인이다.

검토자 실행 명령 (PowerShell, 프로젝트 루트):

```powershell
$env:AGENT_LLM='off'; .\.venv\Scripts\python.exe evals\eval_router.py
$env:AGENT_LLM='on'; .\.venv\Scripts\python.exe evals\eval_router.py
```

두 실행 결과는 당일의 `evals/results/router_<날짜>.json`의 `modes.rule`, `modes.llm`에 함께 저장된다. LLM 모드의 스크립트 종료 코드 1은 기준 미달을 뜻한다.

기존 검사 기대값 변경: `check_scope_inputs.py`의 양성 라우터 출력은 새 메타데이터가 생겨 빈 dict 비교 대신 `route == estimate`로 확인한다. `check_api.py`의 A5는 완료된 대화에서 같은 `thread_id`로 새 질문을 보내면 직전 대화 요약을 사용할 수 있도록 같은 ID가 유지되는 것으로 바꿨다. 기존 계산 금액과 산식의 기대값은 변경하지 않았다.

오프라인 `run_quick.py` 전체 통과. `run_all.py`는 검색 검사 `check_rag.py`의 기존 `n03`(육지에서 다리 받침 인력, 기대 절 `6-6-1` 미검색) 1건으로 26/27, 나머지 24개 검사 스크립트는 통과했다. 라우터에서 검색기를 바꾸지 않았으며, 이 실패를 라우터 성능으로 계산하지 않는다.
