# 파싱 필터 수정안: `read_text_blocks` 줄별 판정 (검토용 제안)

**이 문서는 제안이다.** 저장소의 코드·설정·데이터는 바꾸지 않았고, 아래 함수는 어떤 파일에도 적용하지 않았다.

## 한눈에 보기

- **바꿀 곳:** 기준 코드 `baf186f`의 `pipeline/parse.py` 안 `read_text_blocks` 함수 하나. 반환 형식 `[(세로 위치, 글)]`과 호출부(`parse_pages`)는 그대로다. 청킹은 건드리지 않는다.
- **바뀌는 행동:** 제목 줄과 표 안 줄은 계속 제외한다. 다만 판정 단위가 글자 블록 전체에서 **줄**로 바뀐다. PDF가 표 바깥 기준 표기(`(100㎡당)`, `(개소당)`, `(㎡당)`, `(일당)`)를 제목이나 표 안 글자와 한 블록으로 묶어도 기준 줄은 남는다.
- **확인 결과:**
  - 세 원문 사례(186·195·645쪽): 기준 보존, 표 안 글자 중복 없음, `read_titles` 제목 유지, 주변 주석 유지가 모두 그대로다. 기존에 있던 레코드는 하나도 사라지지 않았다.
  - 기능 검사 둘: (1) 변경이 필요 없는 일반 설명 블록은 반환 내용이 같다, (2) ±2pt 경계 안과 밖 8개 줄에서 기존 판정이 유지된다. 이 검사는 인위적 입력이며 새 품셈 표본의 검증이 아니다.
- **실제 적용 전 남은 것:** 전체 파이프라인 회귀 검사, 청크·벡터 갱신 시 ID 대응(아래 "청크 ID 고지").

## 제안 요약

| 항목 | 기존 | 제안 |
|---|---|---|
| 읽는 자료 | `get_text("blocks")` | `get_text("dict")` (줄 단위 bbox, 글자는 같은 정규화) |
| 제목 제외 | 블록 글자가 `SECTION_RE`/`SUBSECTION_RE`로 시작하면 블록 전체 | 해당 **줄**만 |
| 표 안 제외 | 블록 중심이 표 안(±2pt)이면 블록 전체 | 줄 중심이 표 안(±2pt)인 **줄**만 (경계식 그대로) |
| 쪽 머리글 | 블록 글자가 `RUNNING_HEAD_RE`에 맞으면 제외 | 같음. 남은 연속 구간에도 같은 판정을 적용 |
| 제외 줄이 없는 블록 | 한 레코드, 위치 = 블록 y0 | 한 레코드, 위치 = 블록 y0 (그대로) |
| 일부 줄만 제외된 블록 | 블록 전체 소실 | 제외 줄을 경계로 **남은 연속 줄만** 묶어 구간마다 한 레코드, 위치 = 구간 첫 줄 y0 |
| 한 줄씩 쪼개는가 | - | 아니다. 연속 줄은 한 레코드로 묶는다 |
| 제목·표를 사이에 둔 글 | - | 다시 합치지 않는다 (제외 줄에서 구간이 끊긴다) |

## 확인 결과 상세

방법: 기준 코드를 `git show baf186f:pipeline/parse.py`로 사본에 두고 함수만 교체해 메모리에서 비교했다. 표 좌표는 `experiments/table_census/results/tables.json`(해당 쪽 표 전부), 글자층은 PDF의 기존 글자층이다. 새 표 추출·파서 실행은 하지 않았다.

### 세 원문 사례 (기존 함수 vs 제안 함수, 같은 입력)

| 쪽·표 | 블록 수 기존→제안 | 기존에만 있는 레코드 | 새로 남는 기준 줄 | 제목 `read_titles` | 본문이 제목으로 시작 | 표 안 글자와 같은 본문 | 주변 주석 |
|---|---|---|---|---|---|---|---|
| 186쪽 `p186-t0` | 13 → 14 | 없음 | `(100㎡당)` (y 213.4) | 유지 | 없음 | 없음 | 유지 |
| 195쪽 `p195-t3` | 9 → 11 | 없음 | `(개소당)` (y 575.8), `(㎡당)` (y 429.2, 6-3-4 표, 범위 밖 관찰) | 유지 | 없음 | 없음 | 유지 |
| 645쪽 `p645-t0` | 10 → 13 | 없음 | `(㎡당)` (y 183.8), `(일당)` ×2 (y 505.7·640.6, 4-1-3·4-1-4, 범위 밖 관찰) | 유지 | 없음 | 없음 | 유지 |

- 186쪽 본문에는 주석 안에 `‘[공통부문] 6-1-3 표면 마무리’`라는 참조 문장이 있다. 제목 글자를 포함하지만 제목 줄이 남은 것이 아니고, 기존 함수의 결과에도 같은 문장이 있다.
- 기존 레코드의 (위치, 글)은 전부 제안 결과에 같은 값으로 들어 있다.

### 기능 검사 (인위적 입력, 새 품셈 표본 검증 아님)

1. **일반 설명 블록:** 제외 줄이 없고 표와 떨어진 3줄 `[주]` 블록을 두 함수에 넣었다. 반환 값이 같다(레코드 1건, 위치 같음).
2. **±2pt 경계:** 표 (x 100~300, y 200~300) 둘레에 한 줄짜리 블록 8개를 놓았다. 두 함수의 판정이 모두 같았다.

| 줄 중심 | 기존 | 제안 |
|---|---|---|
| 위쪽 정확히 −2pt (y 198.0) | 제외 | 제외 |
| 위쪽 경계 밖 0.25pt (y 197.75) | 남음 | 남음 |
| 아래쪽 정확히 +2pt (y 302.0) | 제외 | 제외 |
| 아래쪽 경계 밖 0.25pt (y 302.25) | 남음 | 남음 |
| 왼쪽 정확히 −2pt (x 98.0) | 제외 | 제외 |
| 왼쪽 경계 밖 0.25pt (x 97.75) | 남음 | 남음 |
| 오른쪽 정확히 +2pt (x 302.0) | 제외 | 제외 |
| 오른쪽 경계 밖 0.25pt (x 302.25) | 남음 | 남음 |

보조로 `앞쪽 줄 / 제목 줄 / 뒤쪽 줄 A, B / 표 안 줄 / (㎡당)`이 한 블록에 있는 입력을 넣었다. 결과는 `앞쪽 줄`, `뒤쪽 줄 A 뒤쪽 줄 B`, `(㎡당)` 세 레코드이며, 제목을 사이에 둔 글이 다시 합쳐지지 않는다.

### 제안의 한계

- **줄별 제목 판정은 기존보다 넓다.** 기존은 블록 시작만 봤지만 제안은 블록 안 모든 줄에 `SECTION_RE`(`^\d+-\d+-\d+\s`)·`SUBSECTION_RE`(`^\d+-\d+\s`)를 적용한다. 줄바꿈된 본문 줄이 우연히 `숫자-숫자 `로 시작하면 제외된다(`read_titles`는 이미 같은 방식으로 줄을 제목 후보로 본다). 세 쪽 밖에서는 확인하지 않았다.
- **블록 중심만 표 안인 블록:** 줄 중심이 모두 표 밖이면 이제 남는다(기존은 블록 중심이 표 안이면 제외). 표를 사이에 두고 위아래로 걸친 블록이 이에 해당할 수 있다. 세 쪽에서는 해당 사례가 없었다.
- **`dict`와 `blocks`의 글자 동등성:** 정규화한 글이 같다는 것은 세 쪽과 기능 검사로만 확인했다. 전체 PDF에서의 동등성은 확인하지 않았다.
- **쪽 머리글 규칙은 그대로**다(내용 정규식). 위치가 아닌 내용 판정의 한계를 이번에 고치지 않았다.
- **`parse_pages`의 동일 글 중복 제거(코드 읽기만):** 같은 절 안에서 글이 완전히 같은 레코드는 하나만 남긴다. 한 절에 같은 기준 표기(`(일당)`)가 반복되면 두 번째 이후 표의 기준 레코드는 제거될 수 있다. 이번 제안 범위 밖이며 실행해 확인하지 않았다.
- 실패한 검사는 없었다. 규칙을 덧붙이거나 페이지별 예외를 두지 않았다.

## 청크 ID 고지 (실제 데이터 갱신 시 대응 사항)

청킹·ID·임베딩 코드는 수정하지 않는다. 기준 코드 `baf186f`에서 청크 ID 사용처를 `git grep`으로 제한적으로 읽었다. 운영 서버·DB의 저장 상태는 확인하지 않았다.

**ID가 바뀌는 구조**

- 줄글 ID는 `pipeline/chunk.py:137`의 `p{쪽}-x{쪽 안 레코드 순번}`이다. 기준 레코드가 쪽 안에 하나 더 생기면 뒤따르는 줄글 ID가 하나씩 밀린다. 186쪽은 `x4→x5`, `x6→x7`, `x16→x17`로 바뀐다(표 ID `p186-t0`·`t1`은 `find_tables` 순번이라 안 바뀐다).
- `record_ids`는 `parsed*.jsonl` 레코드의 **전체 순번**이다. 기준 레코드가 늘면 그 뒤 모든 레코드 순번이 밀린다.

**혼용 위험과 기존 방어**

| 저장·참조 위치 | 키 | 변경 후 위험 | 기존 방어 |
|---|---|---|---|
| 임베딩 벡터 `backend/agent/tools/search/vector.py:76-87` | `chunk_id` + `text_sha256` (`backend/shared/embedding.py:76-81`, 절 제목+글의 해시) | ID가 바뀐 청크는 옛 행이 `stale`, 새 ID는 `missing`. 같은 ID에 다른 글이 오면 해시가 달라 `stale` | 켜진 부문에 `missing`이 있으면 `MissingVectorsError`로 **큰 소리로 실패**. 조용한 혼용은 아니다 |
| 줄 순번 `quantity.py:134,165`, `legacy_labor.py:29-52` | `chunk.record_ids` → `records[rid]` | `chunks*.jsonl`과 `parsed*.jsonl`이 서로 다른 시점이면 엉뚱한 행을 읽는다 | 없음. **두 파일을 한 번에 같이 재생성**해야 한다. `evals/check_chunk_ids.py`가 재생성 일치·ID 중복·185~214쪽 175개를 확인하나 175는 고정값이다 |
| 규칙 명세 `backend/agent/rules/specs/common/6-1-4_pump.json:460,532` | 설명 문자열 `p186-x16`, `p187-x5` | 갱신 뒤 설명이 어긋난다(`p186-x16`→`x17`) | 조회는 `cite`의 `section_no`·`subsection_no`·`marker`로 하므로 동작은 영향이 없다 |
| 하드코딩 `backend/agent/tools/calc/adjustments.py:235` | `p80-x0` | 80쪽에 기준 레코드가 맨 앞에 새로 생기면 어긋난다 | 없음 |
| 순번 비교 `adjustments.py:131-132` | 청크 ID 숫자 부분 | 쪽 안 순번이 밀리면 "앞쪽 조각" 판정이 바뀔 수 있다 | 없음 |
| 초안 자료 `data/drafts/report.json`, `data/drafts/specs/*` | 줄글 ID 문자열 다수 | 갱신 뒤 표기와 어긋난다 | 없음 (초안 자료) |
| 근거·인용 결과 (`evals/results/*` 등) | `chunk_id` | 갱신 전 근거와 갱신 후 청크를 대조하면 어긋난다 | 없음 |

**실제 갱신 시 대응할 것 (제안 아님, 기록)**

1. `parsed`와 `chunks`를 같은 실행으로 함께 재생성하고, 이전 `chunks*.jsonl`·벡터 파일과 섞어 쓰지 않는다.
2. 벡터는 `missing`·`stale` 목록 기준으로 다시 만든다(`MissingVectorsError`가 안전망).
3. 줄글 ID를 문자열로 적어 둔 규칙 명세·하드코딩·초안 자료를 갱신 후 ID로 점검한다.
4. 갱신 전 근거·인용 결과는 ID가 아니라 쪽·절·글로 대조한다.
5. 이번 변경으로 ID가 바뀌는 쪽 수는 전체 실행 없이는 알 수 없어 계산하지 않았다.

## 제안 함수 (교체할 함수 전체)

실제 저장소 파일에는 적용하지 않았다. `SECTION_RE`, `SUBSECTION_RE`, `RUNNING_HEAD_RE`는 기존 모듈 상단 정의를 그대로 쓴다.

```python
# 표 밖에 있는 줄글을 (세로 위치, 글) 목록으로 읽는다
#
# 제외는 블록이 아니라 줄 단위로 판정한다. PDF가 '(100㎡당)' 같은 기준 표기를 표 안 글자나
# 절 제목과 한 블록으로 묶는 일이 있어, 블록째 버리면 기준도 함께 사라진다.
# 제외되는 줄이 없는 블록은 예전처럼 한 레코드로 두고, 제외된 줄이 끼면 남은 연속된 줄만 묶는다.
def read_text_blocks(page, table_boxes: list) -> list:
    blocks = []

    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue

        # 줄마다 (세로 위치, 글, 제외 여부)
        lines = []
        for line in block["lines"]:
            text = " ".join("".join(span["text"] for span in line["spans"]).split())
            if not text:
                continue

            x0, y0, x1, y1 = line["bbox"]
            center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
            # 제목 줄은 section 항목으로 따로 남으므로 본문에서는 뺀다.
            # 표 안의 글자는 이미 격자로 읽었다
            excluded = (
                bool(SECTION_RE.match(text) or SUBSECTION_RE.match(text))
                or any(
                    box[0] - 2 <= center_x <= box[2] + 2 and box[1] - 2 <= center_y <= box[3] + 2
                    for box in table_boxes
                )
            )
            lines.append((y0, text, excluded))

        # 쪽 번호와 쪽마다 반복되는 머리글은 블록 단위로 거른다
        if RUNNING_HEAD_RE.match(" ".join(text for _, text, _ in lines)):
            continue

        # 제외된 줄을 경계로 남은 줄을 연속 구간으로 나눈다
        runs, run = [], []
        for y0, text, excluded in lines:
            if excluded:
                if run:
                    runs.append(run)
                run = []
            else:
                run.append((y0, text))
        if run:
            runs.append(run)

        for run in runs:
            text = " ".join(t for _, t in run)
            if RUNNING_HEAD_RE.match(text):
                continue
            # 줄을 하나도 제외하지 않은 블록은 예전 블록 위치를 그대로 쓴다
            untouched = len(runs) == 1 and len(run) == len(lines)
            blocks.append((block["bbox"][1] if untouched else run[0][0], text))

    return blocks
```

## 수정 전후 diff

```diff
--- baf186f:pipeline/parse.py (read_text_blocks)
+++ 제안 read_text_blocks
@@ -1,28 +1,57 @@
 # 표 밖에 있는 줄글을 (세로 위치, 글) 목록으로 읽는다
+#
+# 제외는 블록이 아니라 줄 단위로 판정한다. PDF가 '(100㎡당)' 같은 기준 표기를 표 안 글자나
+# 절 제목과 한 블록으로 묶는 일이 있어, 블록째 버리면 기준도 함께 사라진다.
+# 제외되는 줄이 없는 블록은 예전처럼 한 레코드로 두고, 제외된 줄이 끼면 남은 연속된 줄만 묶는다.
 def read_text_blocks(page, table_boxes: list) -> list:
     blocks = []
 
-    for x0, y0, x1, y1, text, _, block_type in page.get_text("blocks"):
-        text = " ".join(text.split())
-        if block_type != 0 or not text:
+    for block in page.get_text("dict")["blocks"]:
+        if block["type"] != 0:
             continue
 
-        # 쪽 번호와 쪽마다 반복되는 머리글
-        if RUNNING_HEAD_RE.match(text):
-            continue
-
-        # 제목 줄은 section 항목으로 따로 남으므로 본문에서는 뺀다
-        if SECTION_RE.match(text) or SUBSECTION_RE.match(text):
-            continue
+        # 줄마다 (세로 위치, 글, 제외 여부)
+        lines = []
+        for line in block["lines"]:
+            text = " ".join("".join(span["text"] for span in line["spans"]).split())
+            if not text:
+                continue
+
+            x0, y0, x1, y1 = line["bbox"]
+            center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
+            # 제목 줄은 section 항목으로 따로 남으므로 본문에서는 뺀다.
+            # 표 안의 글자는 이미 격자로 읽었다
+            excluded = (
+                bool(SECTION_RE.match(text) or SUBSECTION_RE.match(text))
+                or any(
+                    box[0] - 2 <= center_x <= box[2] + 2 and box[1] - 2 <= center_y <= box[3] + 2
+                    for box in table_boxes
+                )
+            )
+            lines.append((y0, text, excluded))
 
-        # 표 안의 글자는 이미 격자로 읽었다
-        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
-        if any(
-            box[0] - 2 <= center_x <= box[2] + 2 and box[1] - 2 <= center_y <= box[3] + 2
-            for box in table_boxes
-        ):
+        # 쪽 번호와 쪽마다 반복되는 머리글은 블록 단위로 거른다
+        if RUNNING_HEAD_RE.match(" ".join(text for _, text, _ in lines)):
             continue
 
-        blocks.append((y0, text))
+        # 제외된 줄을 경계로 남은 줄을 연속 구간으로 나눈다
+        runs, run = [], []
+        for y0, text, excluded in lines:
+            if excluded:
+                if run:
+                    runs.append(run)
+                run = []
+            else:
+                run.append((y0, text))
+        if run:
+            runs.append(run)
+
+        for run in runs:
+            text = " ".join(t for _, t in run)
+            if RUNNING_HEAD_RE.match(text):
+                continue
+            # 줄을 하나도 제외하지 않은 블록은 예전 블록 위치를 그대로 쓴다
+            untouched = len(runs) == 1 and len(run) == len(lines)
+            blocks.append((block["bbox"][1] if untouched else run[0][0], text))
 
     return blocks
```

## 하지 않은 것

- 운영 파일 수정, 커밋·푸시·PR·배포.
- 청킹·ID·임베딩 코드 수정, 계산·임베딩·검색, 183개 후보 전체 검사, 전체 파이프라인 실행.
- 운영 서버·DB의 저장 상태 확인.
