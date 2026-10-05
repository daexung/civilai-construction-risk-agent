# 18-1 부문별 서비스 범위와 검색 평가

서비스 범위는 `agent/rules/scope_config.json`의 공통·토목·건축·기계설비다. 검색은 전체 청크와 전체 벡터에서 이 부문만 고르고, 초안 계산도 같은 부문 목록을 따른다. 부문 미확인 조각과 유지관리는 제외한다. 사람 검토 명세는 동일 절의 AI 초안보다 우선한다. 기존 6장 평가는 `evals/index_configs/6chapter_studio.json`을 명시해 그대로 실행한다.

켜진 부문의 실행 가능 AI 초안은 **327개**다: 공통 99, 토목 50, 건축 111, 기계설비 67. 공통의 검토 완료 명세 1개를 더하면 서비스 계산 명세는 328개다. `executable.json`의 전체 실행 가능 초안 382개 중 유지관리 등 꺼진 부문의 초안은 서비스에 포함하지 않는다.

## 쪽 부문 보정과 벡터 상태

전체 쪽을 확인했을 때 앞뒤와 다른 단일 쪽은 **699, 947쪽**이었다. 947쪽은 인쇄 891쪽, `제2장 토목` 본문이다. 본문에 인용된 `[공통부문] 1-4-4`를 머리말에서 읽어 공통으로 오인한 것이다. 앞뒤 946·948쪽과 같은 **유지관리**로 보정하고 이유를 page_map에 기록했다. 699쪽은 인쇄 쪽 번호가 없는 실제 `기계설비부문` 표제지이므로 보존했다. 표제지까지 앞뒤 부문으로 덮어쓰면 새 오분류가 생긴다.

`chunks.all.jsonl`을 재생성해 비교한 결과 p947의 6조각에서 `division`만 공통→유지관리로 바뀌었다. 조각 ID와 텍스트를 포함한 다른 필드는 그대로다. 잘못 저장된 `공통/2-1-30`, `공통/2-1-31` 초안은 삭제하지 않고 `data/drafts/misfiled.json`에 기록했으며 로더·실행 가능성 평가에서 제외했다. 두 초안은 유지관리 2-1-30·2-1-31로 **재작성 검토가 필요**하다. 기존 `유지관리/2-1-30` 초안은 인쇄 890쪽만 출처로 쓰고 있어 891쪽 내용을 포함했는지 재검토해야 하며, `유지관리/2-1-31` 초안은 없다. 재작성은 수행하지 않았다.

`page_map.json`과 `chunks.all.jsonl`은 `.gitignore`의 가공 산출물이므로 현재 작업 폴더에 재생성했고 커밋하지 않았다. 다른 작업 폴더에서는 아래 명령으로 같은 보정을 반영한다.

```powershell
.\.venv\Scripts\python.exe -m pipeline.page_map
.\.venv\Scripts\python.exe -m pipeline.chunk --parsed data/processed/parsed.all.jsonl --out data/processed/chunks.all.jsonl
```

전체 Parquet은 4,475/4,813조각이며 없는 338벡터는 이제 모두 **유지관리** 조각이다. 켜진 네 부문은 **4,390/4,390조각**, 오래되거나 누락된 벡터 0개로 확인했다. PDF 947쪽 여섯 조각을 유지관리로 바로잡아 서버 시작의 공통 6개 누락 오류가 해소됐다. Parquet에는 API 호출 없이 캐시에 있던 벡터만 기록했다.

## BM25 평가

`draft_questions.jsonl`에서 켜진 부문 질문 300개를 시드 181로 부문별 질문 수에 비례해 고정 추출했다. 잘못 저장된 두 초안에서 만든 공통 질문 6개는 후보에서 제외하고 표본을 다시 만들었다. 정답은 질문을 생성한 초안의 `(부문, 절 번호)`다. `scope_sample.jsonl`에 표본을, `evals/results/scope_bm25_20261003.json`에 문항별 결과를 저장했다. 검색 순위는 조각의 첫 등장 절을 기준으로 중복 절을 제거해 1위·3위 안을 센다. `select`는 기존 `MARGIN=4.0`을 그대로 썼다. 같은 절 번호·다른 부문 혼동은 상위 10개 검색 조각에 나타난 경우다.

| 부문 | 표본 | route 통과 | 1위 절 정답 | 3위 안 정답 | select 정답 확정 | 오답 확정 | 되묻기 | 동번호 타부문 혼동 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 공통 | 116 | 76 | 50 | 59 | 13 | 1 | 102 | 0 |
| 토목 | 32 | 30 | 18 | 23 | 4 | 0 | 28 | 1 |
| 건축 | 62 | 49 | 32 | 39 | 12 | 0 | 50 | 1 |
| 기계설비 | 90 | 67 | 41 | 50 | 14 | 2 | 74 | 0 |
| 전체 | 300 | 222 | 141 | 171 | 43 | 3 | 254 | 2 |

오프라인 결과는 BM25만 측정한 것이다. route에서 탈락한 78건도 분모에 포함했고, 그 문항은 검색·선택에서 되묻기로 계산했다. 기준값은 조정하지 않았다.

하이브리드 평가는 검토자가 다음 명령으로 실행한다. 이 명령은 질문 임베딩을 외부 API에 요청한다.

```powershell
$env:AGENT_LLM='off'
Remove-Item Env:AGENT_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:INDEX_CONFIG -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe evals/check_scope.py --mode hybrid
```

결과는 `evals/results/scope_hybrid_<실행일>.json`에 따로 저장된다. 평가 스크립트는 검색 방식이 실제 `hybrid`이고 질문당 API 호출이 확인되지 않으면 실패한다.

## 기존 검사에서 바뀐 기대

- `check_fill.py` F1과 `check_api.py` A10: 공사 종류의 출처만 `기본값`에서 `기본값(부문)`으로 변경했다. 기존 금액 기대값은 유지했다.
- `check_api.py` A35 M1: 질문에 이미 있는 enum 표시 이름 `철근구조물`을 자동 추출하므로, 해당 조건을 다시 묻는 기대를 추출된 입력값 검사로 바꿨다. 기대 금액은 유지했다.

자동문 A1은 API 테스트에서 건축 기본 조건·3개소를 적용해 도급액 2,727,421원, 공종 표시 `건축 10-1-7 자동문 설치`, 엑셀 파일명 `자동문 설치_견적서.xlsx`로 확인했다. 초안 표기는 `AI 초안 · 검토 전`이다.

## 검증

- `AGENT_OFFLINE=1`, `AGENT_LLM=off`에서 `.venv/Scripts/python.exe evals/run_quick.py`: 17개 스크립트 모두 PASS. `check_api` 42/42, `check_scope_inputs` 38/38, 새 `check_page_divisions` 8/8 포함.
- `.venv/Scripts/python.exe evals/check_scope.py --mode bm25`: 300개 표본 결과 생성, 종료 코드 0.
- 프런트엔드 `npm.cmd run build`: Compiled successfully, 종료 코드 0.
- `evals/check_chunk_ids.py`: 5/5. 켜진 부문 벡터 인덱스를 직접 열어 누락·구버전 0개를 확인했다. FastAPI 시작 훅을 거치는 `TestClient`로 `/api/health` 정상 응답도 확인했다.
