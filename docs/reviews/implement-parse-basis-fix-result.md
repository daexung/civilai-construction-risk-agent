# 파싱 기준 보존 수정 반영 결과 (`pipeline/parse.py` 하나, 별도 작업 폴더)

## 요약

| 항목 | 내용 |
|---|---|
| 작업 폴더 | `C:\Users\user\Desktop\PROJECTS\_parse-basis-fix-baf186f` (새 Git worktree, detached HEAD) |
| HEAD | `baf186ff5afbd13616169c042c270a1fac750a68` (전체 커밋 일치 확인) |
| 수정 파일 | `C:\Users\user\Desktop\PROJECTS\_parse-basis-fix-baf186f\pipeline\parse.py` 하나 (+51 / −17, 커밋하지 않음) |
| 반영한 동작 | ① `read_text_blocks` 줄별 판정, ② 기준 레코드의 동일 글 제거 예외 |
| 검사 결과 | **실패 0건**(67개 확인 모두 통과). 아래 상세 |
| 현재 상태 | 데이터·벡터·운영은 **갱신하지 않았다.** 커밋·푸시·PR·배포 없음 |

원본 저장소는 브랜치 `claude/multi-work-estimate`, HEAD `ad38869` 그대로이고 추적 파일 변경이 없다(기존 미추적 `.claude/`, `docs/handoffs/`, `docs/planning/`, `docs/reviews/`만 있고, 이 결과 문서가 `docs/reviews/`에 추가된 유일한 변경이다). 새 worktree 등록은 원본 `.git`의 worktree 목록에 한 줄 추가된다.

## 반영한 두 동작

1. **`read_text_blocks`**: 글자 블록 전체가 아니라 **줄 단위**로 제외를 판정한다.
   - 표 안 판정은 줄 중심·±2pt(기존 식 그대로).
   - 제목(`SECTION_RE`/`SUBSECTION_RE`)은 해당 줄만 제외한다.
   - 제외 줄이 없는 블록은 한 레코드, 위치는 블록 y0 그대로.
   - 일부 줄만 제외된 블록은 남은 연속 구간마다 한 레코드, 위치는 구간 첫 줄 y0.
   - 쪽 머리글 판정(`RUNNING_HEAD_RE`)은 블록 단위 그대로.
   - 반환 형식 `[(세로 위치, 글)]`과 호출부는 그대로.
2. **`parse_pages` 동일 글 제거**: `kind == "text"`이고 글이 `| 설명 | (…당)`으로 끝나는 기준 레코드는 같은 글이어도 보존한다(`BASIS_RECORD_RE`). 일반 설명·표 행의 제거 정책은 그대로.

범위 밖(바꾸지 않음): 청킹·ID·검색 코드, 다른 함수 정리, 파일 포맷, 의존성·설정. 작업 폴더의 `pipeline/chunk.py`는 `baf186f`와 동일함을 확인했다.

참고: 작업 폴더 파일은 `core.autocrlf` 설정 때문에 CRLF 줄바꿈이며 수정도 CRLF로 했다. Git의 정규화 diff는 위 51/17줄이다.

## 검사 방법

- Python: 원본 저장소 `.venv\Scripts\python.exe`, `AGENT_OFFLINE=1`, `AGENT_LLM=off`, `PYTHONDONTWRITEBYTECODE=1`, `-B`.
- **실제 수정한 파일**(`_parse-basis-fix-baf186f\pipeline\parse.py`)을 import해 `parse_pages`를 호출했고, 기준 코드는 `git show baf186f:pipeline/parse.py`를 메모리 모듈로 만들어 같은 입력으로 비교했다. 청킹은 작업 폴더의 기존 `make_chunks`이며 부문은 `page_map.json`에서 명시적으로 넘겼다.
- 원본 PDF·`data/processed`는 읽기 전용. 파싱·청킹 결과는 메모리에서만 다뤘고 `parsed`·`chunks`·벡터·캐시는 쓰지 않았다. 검사 스크립트는 작업 폴더의 추적 파일에 추가하지 않았다(스크래치패드에만 있음).
- 수정 파일에 문서의 제안 함수가 그대로 들어 있음을 확인했다(함수 sha256 `fb21815534ddbfc95a80cd24a4c03d0d7ffb7f846ec7ab3251919caa86a0332a`, 이전 회귀 검사에서 고정한 값과 같음).

## 결과

### 1. 개발 사례 186·195·645쪽 (쪽별 실행, 실제 PDF)

| 대상 | 원문 기준 | 기준 코드 `basis` | 수정 파일 `basis` | 표 값·제목·주석 |
|---|---|---|---|---|
| 186쪽 6-1-3 `p186-t0` | `(100㎡당)` | `None` | `(100㎡당)` | 표 레코드 6건 동일, `[주]` 유지 |
| 195쪽 6-3-5 `p195-t3` | `(개소당)` | `None` | `(개소당)` | 표 레코드 13건 동일, 주석 유지 (6-3-4 `p195-t2`도 `(㎡당)` 부착) |
| 645쪽 4-1-1 `p645-t0` | `(㎡당)` | `None` | `(㎡당)` | 표 레코드 7건 동일 |
| 645쪽 4-1-3 `p645-t2` | `(일당)` | `None` | `(일당)` | 〃 |
| 645쪽 4-1-4 `p645-t3` | `(일당)` | `None` | `(일당)` | 〃, 주석 유지 |

세 쪽 모두 기준 코드 레코드 소실 0건, 줄글 청크 글 동일, 청크 수 동일(6·7·8), ID 중복 없음.

### 2. 고정 회귀 구간 (기준 커밋 vs 수정 파일)

| 구간 | 표 레코드 | 소실 레코드 | 추가 레코드 | 줄글 ID 변화 |
|---|---|---|---|---|
| 420~421쪽 | 44건 동일 | 0 | `(개소당)` 1건 (`p421-t3` 6-2-3) | `p421-x29→x30` |
| 679~680쪽 | 25건 동일 | 0 | `(㎥당)`, `(일당)` 2건 (`p679-t0`, `p679-t2`) | `x1→x2`, `x9→x10`, `x15→x17` |
| 131쪽 | 15건 동일 | 0 | 없음 | 없음 |
| 724쪽 | 6건 동일 | 0 | 없음 | 없음 |

추가 레코드는 지난 회귀 검사에서 기록한 3건과 정확히 같다. 새 표본을 고르지 않았고 규칙을 조정하지 않았다.

### 3. 같은 절의 두 표 앞 `(일당)` (가상 입력, 실제 `parse_pages` 로직)

가상 입력이며 실제 PDF가 아니다. 쪽 읽기 함수만 메모리에서 바꿔 끼우고 수정 파일의 `parse_pages`를 그대로 호출했다.

| 표 | 기준 코드 | 수정 파일 |
|---|---|---|
| 첫 번째 표 `p1-t0` | `(일당)` | `(일당)` |
| 두 번째 표 `p1-t1` | `None` (기준 소실 재현) | `(일당)` |

일반 설명 `[주]` 중복은 수정 파일에서도 1건만 남는다(정책 유지).

### 4. 기능 검사

- 변경이 필요 없는 일반 설명 블록: 기준 코드와 수정 파일의 반환이 같다(레코드 1건).
- 표 경계 ±2pt 8개 줄(위·아래·왼쪽·오른쪽 각각 경계 안 −2pt/+2pt와 경계 밖 0.25pt): 기준 코드와 수정 파일의 판정이 모두 같다.
- 제목·표 사이의 글(`앞쪽 줄`, `뒤쪽 줄 A·B`, `(㎡당)`)은 다시 합쳐지지 않는다.

이 두 검사는 인위적 입력이며 새 품셈 표본 검증이 아니다.

### 5. Git 상태

- `git diff --check`: 문제 없음.
- 변경 파일 목록: `pipeline/parse.py` 하나. 작업 폴더에 미추적 파일 없음.

## 한계와 미실행

- **알려진 제목 정규식 오인 가능성은 해결하지 않았다.** 줄별 판정은 블록 안 모든 줄에 `숫자-숫자 `형 정규식을 적용하므로 줄바꿈된 본문 줄이 우연히 이 형태로 시작하면 제외될 수 있다. 검사한 9쪽에서는 사례가 없었고 이 위험은 미검사로 남아 있다.
- **소제목에 붙은 기준**(`[참고자료] 모르타르 배합 재료량 (㎥당)` 유형, `p679-t1`)은 이번 수정 범위 밖이며 해결하지 않았다.
- **쪽별 실행 한계:** 검사는 쪽·구간별로 실행했다. 첫 쪽 이전 문맥과 쪽을 넘는 동일 글 제거는 확인하지 않았다.
- **줄글 ID가 밀린다.** 기준 레코드가 추가된 쪽의 뒤따르는 줄글 ID와 `record_ids`가 바뀐다. 청킹·ID·임베딩은 수정하지 않았다. 실제 갱신 시 대응은 `parse-filter-reviewable-change-result.md`의 "청크 ID 고지"를 따른다.
- **미실행:** 전체 문서 재파싱·재청킹, `parsed`·`chunks`·벡터 재생성, 전체 파이프라인 회귀 검사, 183개 후보 점검, 운영 적용. 데이터·벡터·운영 상태는 갱신하지 않았다.

## 최종 diff (`pipeline/parse.py`, 기준 커밋 `baf186f` 대비)

```diff
diff --git a/pipeline/parse.py b/pipeline/parse.py
index 5b5a531..f8046c8 100644
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
@@ -75,31 +79,60 @@ def read_titles(page) -> list:
 
 
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
+            if RUNNING_HEAD_RE.match(text):
+                continue
+            # 줄을 하나도 제외하지 않은 블록은 예전 블록 위치를 그대로 쓴다
+            untouched = len(runs) == 1 and len(run) == len(lines)
+            blocks.append((block["bbox"][1] if untouched else run[0][0], text))
 
     return blocks
 
@@ -337,7 +370,8 @@ def parse_pages(pdf_path: str, start_page: int, end_page: int) -> list:
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
