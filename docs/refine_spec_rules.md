# 명세 규칙 정제 후보 도구

`pipeline.refine_spec_rules`는 `draft_specs.py`로 만든 명세를 원문 PDF·파싱 조각과 함께 검토하기 위한 후보 작업 도구입니다. `prepare`는 입력을 별도 폴더에 저장하고, `candidate`/`validate`는 후보 및 차이 보고서를 별도 경로에 기록합니다. 원본 draft와 운영 명세 경로, 입력 bundle은 출력 대상으로 거부하며 기존 출력 파일도 덮어쓰지 않습니다.

## 공통 6-3-1 준비 재현

프로젝트 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pipeline.refine_spec_rules prepare --division 공통 --section 6-3-1 --out-dir tmp\refine-6-3-1
```

입력 파일은 `tmp/refine-6-3-1/input.json`, 쪽 번호 및 해시 기록은 `manifest.json`, 발췌 PDF는 `source_excerpt.pdf`에 저장됩니다. 준비 결과에서 PDF 내부 page index는 191–194이며 인쇄 쪽은 135–138입니다. 따라서 인쇄 쪽 137은 PDF 내부 index 193에 대응합니다. 파싱 조각에 전체 절 표와 비고가 포함되었는지 입력 bundle의 `parsed_chunks`에서 확인할 수 있습니다.

수정한 후보를 별도 경로로 복사하고 검사합니다.

```powershell
.\.venv\Scripts\python.exe -m pipeline.refine_spec_rules candidate --bundle tmp\refine-6-3-1\input.json --candidate-json edited.json --out tmp\refine-6-3-1\candidate.json
```

기계 검사와 후보 차이는 `candidate.review.json`에 남습니다. 미확정 사항이 있거나 검사가 실패하면 종료 코드는 1입니다. 검사 통과도 원문 의미에 대한 사람 검토 완료를 뜻하지 않습니다.

## 오프라인 검사

```powershell
.\.venv\Scripts\python.exe -m unittest evals.test_refine_spec_rules -v
```

검사는 유효 후보, 알 수 없는 source ID, 조작된 quote, 잘못된 JSON 구조/필드 타입, 6-3-1 미확정 3m 규칙, 다른 공종의 9% 표현, 보호 경로와 기존 파일 덮어쓰기 거부를 확인합니다. 네트워크를 사용하지 않습니다.

`refine`은 기본적으로 외부 모델을 호출하지 않습니다. 모델 호출이 필요한 경우 `--execute-model`이 필수이며, JSON Schema는 프롬프트 본문에 전달됩니다. API의 constrained decoding/response-schema 옵션으로 강제하지 않으므로 출력은 로컬 검사로 별도 확인해야 합니다.
