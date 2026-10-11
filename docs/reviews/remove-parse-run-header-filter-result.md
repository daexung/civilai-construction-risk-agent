# 구간별 머리글 필터 제거 결과 (`pipeline/parse.py`, 조건문 두 줄)

**구간별 머리글 조건문 두 줄을 실제로 제거했고, 검사 실패는 0건이다.** 실제 수정 파일로 확인 항목 99개를 실행해 모두 통과했다(기존 검사 67 + 가상 입력·직전 상태 비교·변경 범위 32). 전체 문서 검증을 완료했다는 뜻은 아니다.

## 작업 위치와 수정

| 항목 | 내용 |
|---|---|
| 작업 폴더 | `C:\Users\user\Desktop\PROJECTS\_parse-basis-fix-baf186f` (기존 worktree, 새로 만들지 않음) |
| HEAD | `baf186ff5afbd13616169c042c270a1fac750a68` (detached, 전체 커밋 일치) |
| 수정 파일 | `C:\Users\user\Desktop\PROJECTS\_parse-basis-fix-baf186f\pipeline\parse.py` 하나 |
| 시작 전 상태 | HEAD, 변경 파일 하나, +51/−17이 이전 보고와 같음(덮어쓰거나 되돌린 것 없음) |
| 이번 변경 | `for run in runs:` 안의 `if RUNNING_HEAD_RE.match(text): continue` 두 줄 제거 |
| 수정 후 | 기준 커밋 대비 +49/−17 |

블록 단위 머리글 판정(`RUNNING_HEAD_RE.match(" ".join(...))`, 파일의 114행), 줄별 제목·표 판정, 기준 레코드 중복 제거 예외는 그대로다. 파일 안 `RUNNING_HEAD_RE.match(` 호출은 이제 블록 단위 1곳이다. 줄바꿈(CRLF)과 다른 코드는 바꾸지 않았다.

## 검사 방법

- Python: 원본 저장소 `.venv\Scripts\python.exe`, `AGENT_OFFLINE=1`, `AGENT_LLM=off`, `PYTHONDONTWRITEBYTECODE=1`, `-B`.
- **수정 파일을 import**해 실제 `parse_pages`, `read_text_blocks`를 호출했다. 기준 코드는 `git show baf186f:pipeline/parse.py` 메모리 모듈, 청킹은 작업 폴더의 기존 `make_chunks`. 파싱·청킹 결과는 메모리에서만 다뤘고 `parsed`·`chunks`·벡터·캐시는 쓰지 않았다. 검사 스크립트는 추적 파일에 추가하지 않았다.
- 기존 검사 도우미(`verify_impl`)는 호출 형식(`verify_impl.py <스크래치패드>`)을 확인한 뒤 그대로 재사용했다. 제안 함수 일치 표시만 `False`로 바뀌었고 이는 두 줄이 의도적으로 빠졌기 때문이다(변경 범위 검사로 별도 확인).

## 결과

### 1. 실제 PDF 개발 사례 186·195·645쪽 (실제 PDF 표본, 쪽별 실행)

| 대상 | 원문 기준 | 기준 코드 `basis` | 수정 파일 `basis` | 표 값·제목·주석 |
|---|---|---|---|---|
| 186쪽 6-1-3 `p186-t0` | `(100㎡당)` | `None` | `(100㎡당)` | 표 레코드 6건 동일, `[주]` 유지 |
| 195쪽 6-3-5 `p195-t3` | `(개소당)` | `None` | `(개소당)` | 표 레코드 13건 동일, 주석 유지 (6-3-4 `p195-t2`는 `(㎡당)`) |
| 645쪽 4-1-1 `p645-t0` | `(㎡당)` | `None` | `(㎡당)` | 표 레코드 7건 동일 |
| 645쪽 4-1-3 `p645-t2` | `(일당)` | `None` | `(일당)` | 〃 |
| 645쪽 4-1-4 `p645-t3` | `(일당)` | `None` | `(일당)` | 〃, 주석 유지 |

### 2. 고정 회귀 구간 (실제 PDF 표본, 기준 커밋 대비)

| 구간 | 표 레코드 | 소실 레코드 | 추가 레코드 | 줄글 ID 변화 |
|---|---|---|---|---|
| 420~421쪽 | 44건 동일 | 0 | `(개소당)` 1건 (`p421-t3`) | `p421-x29→x30` |
| 679~680쪽 | 25건 동일 | 0 | `(㎥당)`, `(일당)` 2건 | `x1→x2`, `x9→x10`, `x15→x17` |
| 131쪽 | 15건 동일 | 0 | 없음 | 없음 |
| 724쪽 | 6건 동일 | 0 | 없음 | 없음 |

추가된 기준 3건과 표 레코드 보존이 기존 보고와 같다. 새 표본은 고르지 않았다.

### 3. 가상 입력: 같은 절의 두 표 앞 `(일당)`, 변경 불필요 블록, ±2pt 경계 (가상 입력)

- 두 표 앞 `(일당)`: 기준 코드는 두 번째 표 `basis`가 `None`, 수정 파일은 둘 다 `(일당)`. 일반 설명 중복 제거 정책은 유지(주석 1건).
- 변경이 필요 없는 일반 설명 블록: 반환 동일(레코드 1건).
- 표 경계 ±2pt 8개 줄과 제목·표 사이 글 비분리 확인: 모두 통과.

### 4. 가상 입력: 구간별 머리글 필터 제거 영향 (가상 입력, 실제 PDF 손실의 증거 아님)

| 입력 | 기준 코드 | 수정 파일(제거 후) | 비고 |
|---|---|---|---|
| 1a 제목 줄 + 표 밖 `3` | (없음) | `3` | **기준 코드가 버렸던 정수가 새로 남음** |
| 1b 본문 + 중간 제목 줄 + 표 밖 `12` | `① … 4-1-1 먹매김('15년 보완) 12` | `① 본 품은 바닥면적 기준이다.`, `12` | 본문 정수 `12` 남음, 제목은 본문에서 제외 |
| 2a 표 밖 `12` + 표 안 줄 (중심 표 밖) | `12 구 분` | `12` | 본문 정수 `12` 남음, 표 안 글자 제외 |
| 2b 표 밖 `12` + 표 안 줄 (중심 표 안) | (없음) | `12` | **기준 코드가 버렸던 정수가 새로 남음** |
| 2c 표 밖 `0.34` + 표 안 줄 | `0.34 구 분` | `0.34` | 소수는 영향 없음 |
| 3a 쪽 번호 `130` | (없음) | (없음) | 계속 제외 |
| 3b 머리글 `제4장 목공사` | (없음) | (없음) | 계속 제외 |
| 3c 머리글 `제4장` / `목공사` | (없음) | (없음) | 계속 제외 |

- 본문 정수 `12`가 남는 것(1b, 2a)과 일반 쪽 번호·머리글 블록이 계속 제외되는 것(3a~3c)을 확인했다.
- **새로 남는 정수 한 줄(1a의 `3`, 2b의 `12`)은 숨기지 않고 기록한다.** 기준 코드가 블록 통째로 버리던 경우에, 제외된 제목·표 안 줄 옆의 정수 한 줄이 짧은 줄글 레코드로 남는다. 이전 확인 결과에서 예상한 비용이며, 이번 수정에서 별도 규칙을 추가하지 않았다.

### 5. 이미 검사한 9쪽: 직전 상태와의 비교 (실제 PDF 표본, 새 표본 아님)

186·195·645·420·421·679·680·131·724쪽에서 제거 전후 `read_text_blocks` 반환이 9쪽 모두 같다. 실제 문서에서 이 두 줄이 결과를 바꾼 곳은 이 9쪽에서는 없다.

### 6. Git 상태

- `git diff --check`: 문제 없음.
- 변경 파일: `pipeline/parse.py` 하나. 미추적 파일 없음.
- 변경 범위 검사: 직전 상태에서 두 줄만 제거한 것과 파일이 정확히 일치.

## 원본 저장소와 갱신 상태

- 원본 폴더: 브랜치 `claude/multi-work-estimate`, HEAD `ad38869` 그대로. 추적 파일 변경 없음(기존 미추적 `.claude/`, `docs/handoffs/`, `docs/planning/`, `docs/reviews/`만 있고, 이 결과 문서가 추가된 변경이다).
- **데이터·벡터·운영은 갱신하지 않았다.** `parsed`·`chunks`·벡터·캐시를 쓰지 않았고 LLM·임베딩·네트워크·운영 접속·커밋·푸시·배포는 없었다.

## 한계

- 제목 정규식 오인 가능성, 소제목에 붙은 기준(`[참고자료] … (㎥당)`, `p679-t1`), 줄글 ID·`record_ids` 변화에 대한 대응은 이번 수정에 포함하지 않았다.
- 실제 PDF 확인은 개발 사례 3쪽과 회귀 6쪽(총 9쪽)뿐이다. 전체 재파싱·재청킹, 전체 회귀 검사, 183개 후보 점검은 하지 않았다.
- 새로 남는 정수 줄글(1a, 2b 유형)이 실제 문서 전체에서 얼마나 나오는지는 확인하지 않았다. 전체 회귀 검사에서 확인해야 한다.

## 직전 상태 대비 diff (이번 변경)

```diff
--- 직전 상태
+++ 수정 후
@@ -128,8 +128,6 @@
 
         for run in runs:
             text = " ".join(t for _, t in run)
-            if RUNNING_HEAD_RE.match(text):
-                continue
             # 줄을 하나도 제외하지 않은 블록은 예전 블록 위치를 그대로 쓴다
             untouched = len(runs) == 1 and len(run) == len(lines)
             blocks.append((block["bbox"][1] if untouched else run[0][0], text))
```

## 기준 커밋 `baf186f` 대비 최종 diff

```diff
diff --git a/pipeline/parse.py b/pipeline/parse.py
index 5b5a531..6ae2fbd 100644
--- a/pipeline/parse.py
+++ b/pipeline/parse.py
@@ -15,6 +15,10 @@ SECTION_RE = re.compile(r"^\d+-\d+-\d+\s")
 # "6-1 콘크리트" 처럼 두 자리 중분류. 절이 시작되기 전 도입부 설명을 묶는 데 쓴다
 SUBSECTION_RE = re.compile(r"^\d+-\d+\s")
 
+# 표 바로 위에 따로 인쇄되는 기준 표기('(일당)', '(100㎡당)')를 담은 줄글 레코드.
+# 같은 절의 서로 다른 표 앞에 같은 글로 반복되므로 동일 글 제거에서 뺀다
+BASIS_RECORD_RE = re.compile(r"\| 설명 \| \([^()]*당\)$")
+
 # 모든 쪽에 반복되는 머리글("제6장 철근콘크리트공사")과 쪽 번호.
 # 본문도 같은 높이에서 시작하는 쪽이 있어 위치가 아니라 내용으로 걸러야 한다
 RUNNING_HEAD_RE = re.compile(r"^(제\d+장(\s|$)|\d+$)")
@@ -75,31 +79,58 @@ def read_titles(page) -> list:
 
 
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
+        # 줄마다 (세로 위치, 글, 제외 여부)
+        lines = []
+        for line in block["lines"]:
+            text = " ".join("".join(span["text"] for span in line["spans"]).split())
+            if not text:
+                continue
 
-        # 제목 줄은 section 항목으로 따로 남으므로 본문에서는 뺀다
-        if SECTION_RE.match(text) or SUBSECTION_RE.match(text):
-            continue
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
+            # 줄을 하나도 제외하지 않은 블록은 예전 블록 위치를 그대로 쓴다
+            untouched = len(runs) == 1 and len(run) == len(lines)
+            blocks.append((block["bbox"][1] if untouched else run[0][0], text))
 
     return blocks
 
@@ -337,7 +368,8 @@ def parse_pages(pdf_path: str, start_page: int, end_page: int) -> list:
     seen = set()
     unique = []
     for record in records:
-        if record["text"] in seen:
+        is_basis = record["kind"] == "text" and BASIS_RECORD_RE.search(record["text"])
+        if record["text"] in seen and not is_basis:
             continue
         seen.add(record["text"])
         unique.append(record)
```
