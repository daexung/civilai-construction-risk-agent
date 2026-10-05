# 작업 22-4 결과

## 작업 범위

- PR #11 머지 커밋 `74c31fc`에서 main을 fast-forward한 뒤 `feat/estimate-tabs` 생성. 로컬 커밋만 수행.
- 계산·금액·엑셀 생성 로직 변경 없음. 기존 수정된 샘플 엑셀 두 파일을 검사 전 복사하고 검사 후 SHA256이 같은 원본으로 복구.
- `.env` 직접 열람 없음. 실제 외부 LLM 호출 없음. UI 확인은 `AGENT_OFFLINE=1`, `AGENT_LLM=off`인 8030 API와 3030 UI 사용.
- 브라우저 연결 도구가 제공하는 앱/브라우저가 없어 기존 Edge의 debugging pipe 사용. 추가 디버깅 포트나 npm 패키지 사용 없음.

## UI

- 존재하는 표만 원가계산서 → 내역서 → 일위대가표(단위 기준 포함) → 단가대비표 → 산출근거 순으로 표시.
- 선택한 패널 하나만 표시. 답변마다 독립 상태이며 응답 객체 교체 시 첫 탭으로 초기화.
- 텍스트 탭, accent 2px 밑줄, tablist/tab/tabpanel 및 좌우 키 이동 적용.
- 근거 접기와 미산정 안내는 탭 아래 유지. 표 셀의 수량·단가 접기 유지.
- fixed 견적에는 배지 없음. template 응답에는 작은 회색 `간단 응답`만 표시.
- 미리보기의 숫자·표를 보존하고, 실제 8030 응답에서 answer/answer_source/llm_info 세 필드만 갱신.

캡처:

- `ui_22-4/estimate-statement.png`: 탭 5개와 원가계산서 기본 선택
- `ui_22-4/estimate-unit-price.png`: 일위대가표 선택
- `ui_22-4/estimate-mobile-390.png`: 390px 화면 탭 스크롤

브라우저 확인: 페이지 scrollWidth 390px, 탭 줄 scrollWidth 517px / clientWidth 360px. ArrowRight로 내역서 이동. 조건 변경 적용 후 원가계산서 선택 복귀. 첫 페이지 탭 5개 확인, pointer-events 없음 유지.

## 미산정 문장 판단

사유에 `단가` 또는 `가격`이 있으면 단가 누락으로 묶는다. 예: `유류 가격 미입력`인 펌프차 연료·잡재료비. 다른 사유가 있으면 `이번 계산에서 빠졌습니다`로 묶는다. 지급보증 수수료는 지급보증액 발급금액 기준 산정 방법 미확인이므로 두 번째 그룹이다. 소규모 적용·살수 양생 품량도 계산 범위 미산정 사유로 두 번째 그룹이다. 사유가 없는 기존 fixture는 단가 누락 그룹으로 처리한다. 이름은 두 출처 전체에서 중복 제거하고 각 그룹 마지막 이름에 `_josa`를 적용한다.

## 바뀐 기대값 전체

모두 `evals/check_compose.py`. graph/api 파일의 기대값 및 모든 금액·숫자 기대값은 변경하지 않았다.

| 검사 이름 | 이전 | 이후 |
|---|---|---|
| C0 draft-review fact omitted from compose input | captured_prompt[0]에 draft_review 없음, source llm | captured_prompt 비어 있음, source fixed; facts의 draft_review 없음은 유지 |
| C0e 빠진 항목 이름 중복 제거 | `미산정 항목:` 1회, priced 이름 각 1회 | 옛 접두어 없음, `빠졌습니다.` 있음, priced+statement 전체 이름 각 1회 |
| C1 facts 숫자만 쓰면 llm 채택 → C1 견적은 fixed 문장 사용 | source llm, good_llm 문장 | source fixed, build_template(facts) 문장 |
| C1b VAT-inclusive contract amount with unpriced item accepted | source llm, estimate_answer | source fixed, estimate_answer 유지; 상태에 priced fixture 추가 |
| C9 그래프 전체: answer 필드 추가 | source가 llm/template 중 하나 | source fixed |

```diff
- "draft_review" not in captured_prompt[0]
- draft_compose["answer_source"] == "llm"
+ not captured_prompt
+ draft_compose["answer_source"] == "fixed"

- duplicate_names = [item["name"] for item in facts["priced"]["unpriced"]]
+ duplicate_names = unpriced_names(facts)
- duplicate_text.count("미산정 항목:") == 1
+ "미산정 항목:" not in duplicate_text and "빠졌습니다." in duplicate_text

- good["answer_source"] == "llm" and good["answer"] == good_llm("", "")
+ good["answer_source"] == "fixed" and good["answer"] == build_template(facts)

- estimate_llm["answer_source"] == "llm"
+ estimate_llm["answer_source"] == "fixed"

- final.get("answer_source") in ("llm", "template")
+ final.get("answer_source") == "fixed"
```

기대값을 바꾸지 않고 입력 경로만 조정한 검사: C2, C3, C3b, C4, C7b, C11, C12, C13, C14, C15, C16, C17, C-new2. 계산 결과가 없는 PARTIAL 상태에 기존 facts를 주입하는 `legacy_compose`로 기존 LLM 숫자 검증·실패 대체·재시도·클라이언트 캐시 검사를 계속 수행한다. 실패를 숨기기 위한 기대값 수정 없이 원래 단언을 유지했다.

추가 검사: PARTIAL/OK 각각 generate_fn 호출 0회 및 fixed/skip 메타데이터 확인, OUT_OF_SCOPE generate_fn 호출 1회, 지급보증 수수료의 비단가 사유 문장 확인.

## 검사 결과

- `check_compose.py`: 42/42.
- `npm.cmd run build`: 성공.
- `run_quick.py`: 20개 스크립트 중 18개 통과, 종료 코드 1.
- `check_api.py`: 47/48. A9 응답에 llm_info 포함 실패. 기존 검사는 견적 llm_info의 provider=`vertex`, model=`gemini-3.5-flash-lite`, attempts=0을 요구하지만 fixed 견적은 `{"skipped":"estimate_fixed_text"}`만 반환한다. 이는 허용된 answer_source/가짜 LLM 문장 기대값 변경 범위 밖이므로 수정하지 않았다.
- `check_chunk_ids.py`: 기존 4/5 실패 `전체 청크 재생성 일치` 유지.
- 나머지 router 23/23, qa 70/70, label_shift 11/11, fill 16/16, graph 19/19, price 20/20, equipment 18/18, supply 8/8, spec_cases 25/25, citation 13/13, cost_statement 8/8, embedding_config 19/19, per_unit 34/34, adjustments 20/20, scope_inputs 39/39, page_divisions 9/9. overhead_rates는 종료 코드 0이며 요약 줄 없음.

기존 샘플 엑셀 SHA256:

- sample_견적서.xlsx: `80F333F681024C365FD61DD7D234F5FBB1BC6711237EF27A0C62C01FBEB6C66D`
- sample_견적서_사급.xlsx: `B804F035678CF35232C845F62521C3BFE8A33D055DA4DC5F8E039E8237B5B313`
