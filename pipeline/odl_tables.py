"""OpenDataLoader PDF(로컬 모드)의 표 출력을 공통 표 형식으로 바꾸는 어댑터.

전환 계획(docs/ODL_MIGRATION_PLAN.md) P1 단계의 산출물이다. parse.py는 아직 이 모듈을 쓰지 않는다.

흐름:
    run_odl(pdf, pages, out_dir)          → ODL CLI 실행, 원시 JSON 경로 반환
    read_tables(json_path, page_heights)  → {쪽 번호: [공통 표, ...]}
    to_grid(table)                        → 현행 조립 로직(clean_table)에 넣을 2차원 격자

공통 표:
    {"page", "bbox_pt": [x0, y0, x1, y1] (왼쪽 위 원점), "nested": bool,
     "n_rows", "n_cols", "cells": [{"r0", "r1", "c0", "c1", "text"}]}   # r1·c1은 끝을 포함하지 않는다

Java와 jar 위치는 인자로 받거나 환경 변수 ODL_JAVA·ODL_JAR로 정한다. 둘 다 없으면 저장소의 .venv-odl을 쓴다.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JAVA = ROOT / ".venv-odl/jre/bin/java.exe"
DEFAULT_JAR = ROOT / ".venv-odl/Lib/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar"

# 자식 노드가 들어가는 키. 목록('list items') 안에도 표나 문장이 들어갈 수 있다
# (예: 185쪽 비고 칸의 '- ' 문장들, 188쪽 [주] ② 목록 항목 안의 층별 할증률 표)
CHILD_KEYS = ("kids", "rows", "cells", "list items")


def run_odl(pdf: Path, pages: list[int], out_dir: Path, java: Path | None = None, jar: Path | None = None) -> dict:
    """지정한 쪽만 ODL로 추출한다. 반환값은 원시 JSON 경로와 실행 기록."""
    java = Path(java or os.environ.get("ODL_JAVA") or DEFAULT_JAVA)
    jar = Path(jar or os.environ.get("ODL_JAR") or DEFAULT_JAR)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(java), "-jar", str(jar), "-f", "json", "--keep-line-breaks", "--table-method", "default",
           "-o", str(out_dir), "--pages", ",".join(str(p) for p in pages), str(pdf)]

    started = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"ODL 실행 실패(exit {proc.returncode}): {proc.stderr[-2000:]}")

    json_path = out_dir / f"{pdf.stem}.json"
    if not json_path.exists():
        raise RuntimeError(f"ODL 출력이 없다: {json_path}")
    return {"json_path": json_path, "command": cmd, "elapsed_sec": round(elapsed, 2)}


def cell_text(node: dict) -> str:
    """칸 안의 글자를 문서 순서대로 모은다. 중첩 표가 있으면 그 글자도 이어 붙는다(PyMuPDF와 같은 동작)."""
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("content"), str):
                parts.append(n["content"])
            for key in CHILD_KEYS:
                for child in n.get(key) or []:
                    walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    for key in CHILD_KEYS:
        for kid in node.get(key) or []:
            walk(kid)
    return "\n".join(parts)


def find_tables(node, depth: int = 0, found: list | None = None) -> list[tuple[dict, int]]:
    """문서 트리에서 표 노드를 모두 찾는다. depth > 0이면 다른 표의 칸 안에 든 중첩 표다."""
    found = [] if found is None else found
    if isinstance(node, dict):
        is_table = node.get("type") == "table"
        if is_table:
            found.append((node, depth))
        for key in CHILD_KEYS:
            for child in node.get(key) or []:
                find_tables(child, depth + (1 if is_table else 0), found)
    elif isinstance(node, list):
        for child in node:
            find_tables(child, depth, found)
    return found


# ---------------- 칸 안 행 분리 (P2) ----------------
# 가로선이 없는 여러 행을 ODL이 한 칸에 쌓아 줄 때, 칸 안 문단 좌표로 행을 다시 나눈다.
# 줄마다의 좌표는 없으므로 문단 bbox를 줄 수로 나눠 각 줄의 세로 위치를 추정한다.

# 행 기준선이 되는 값: 숫자, 괄호 숫자, 범위, 백분율, 이하·이상, 분류번호(0301-0057), '-', '〃'
VALUE_RE = re.compile(r"^(?:[-–〃]|\(?\d[\d.,\-]*\)?(?:[~∼]\d[\d.,]*)?(?:%|이하|이상|미만|초과)?)$")
# 앞 줄에 딸린 설명·보충 줄
CONTINUATION_PREFIXES = ("-", "(", "※")


def cell_lines(cell: dict) -> list[tuple[float, str]] | None:
    """칸의 줄을 (추정 세로 위치, 글자)로 위에서 아래 순서로 낸다. 좌표를 알 수 없는 내용이 있으면 None."""
    lines = []
    for kid in cell.get("kids") or []:
        if kid.get("type") != "paragraph" or "bounding box" not in kid or not isinstance(kid.get("content"), str):
            return None
        texts = kid["content"].split("\n")
        _, bottom, _, top = kid["bounding box"]
        height = (top - bottom) / len(texts)
        lines += [(top - (i + 0.5) * height, text) for i, text in enumerate(texts)]
    if any(cell.get(key) for key in ("rows", "cells", "list items")):
        return None
    return sorted(lines, key=lambda line: -line[0])


def line_height(cells: list[dict]) -> float:
    heights = sorted((k["bounding box"][3] - k["bounding box"][1]) / len(k["content"].split("\n"))
                     for c in cells for k in c.get("kids") or [] if "bounding box" in k and isinstance(k.get("content"), str))
    return heights[len(heights) // 2] if heights else 0.0


def join_continuations(lines):
    out = []
    for y, text in lines:
        if out and text.strip().startswith(CONTINUATION_PREFIXES):
            out[-1] = (out[-1][0], f"{out[-1][1]} {text}")
        else:
            out.append((y, text))
    return out


def nearest(y: float, anchors: list[float]) -> int:
    return min(range(len(anchors)), key=lambda i: abs(anchors[i] - y))


def first_col_is_group(rows: list[dict], r: int, n_cols: int) -> bool:
    """r행의 첫 열이 오른쪽 열과 같은 머리글 아래에 있는 상위 조건 열인지.

    위쪽 행 중 첫 열을 덮는 칸(표 전체 폭 제목 칸은 제외)이 이 행의 첫 열 칸보다 넓으면 그렇다고 본다.
    예: 185쪽 머리글 '구 분'이 두 열에 걸치고, 그 아래가 '인력운반 타설'(조건) + '콘크리트공/보통인부'(직종).
    """
    own = next((c for c in rows[r].get("cells") or [] if c["column number"] == 1), None)
    if own is None:
        return False
    for above in rows[:r]:
        head = next((c for c in above.get("cells") or [] if c["column number"] == 1), None)
        if head is None or head.get("column span", 1) >= n_cols:
            continue
        return head.get("column span", 1) > own.get("column span", 1)
    return False


def split_row(cells: list[dict], group_first_col: bool = False) -> tuple[int, dict[int, list[str] | None]] | None:
    """한 ODL 행을 하위 행으로 나눈다. 나눌 수 없으면 None.

    반환: (하위 행 수, {칸 번호: 하위 행별 글자 목록 또는 None(병합 칸으로 둠)})
    group_first_col=True면 첫 열은 여러 하위 행에 걸친 조건으로 보고 나누지 않는다.
    """
    single = [c for c in cells if c.get("row span", 1) == 1]
    lines = {id(c): cell_lines(c) for c in single}
    if any(v is None for v in lines.values()):
        return None
    numeric = [c for c in single if len(lines[id(c)]) >= 2
               and all(VALUE_RE.match(re.sub(r"\s+", "", t)) for _, t in lines[id(c)])]
    if not numeric:
        return None

    tol = 0.6 * line_height(single)
    anchors: list[list[float]] = []
    for y in sorted((y for c in numeric for y, _ in lines[id(c)]), reverse=True):
        if anchors and abs(sum(anchors[-1]) / len(anchors[-1]) - y) <= tol:
            anchors[-1].append(y)
        else:
            anchors.append([y])
    centers = [sum(a) / len(a) for a in anchors]
    if len(centers) < 2:
        return None

    plan: dict[int, list[str] | None] = {}
    for c in single:
        cl = lines[id(c)]
        slots = [""] * len(centers)
        if c in numeric:
            # 숫자 줄은 서로 다른 기준선에 허용 오차 안으로 맞아야 한다. 아니면 이 행은 나누지 않는다
            used = set()
            for y, text in cl:
                i = nearest(y, centers)
                if abs(centers[i] - y) > tol or i in used:
                    return None
                used.add(i)
                slots[i] = text
            plan[id(c)] = slots
            continue
        if len(cl) < 2:
            plan[id(c)] = None
            continue
        joined = join_continuations(cl)
        if c["column number"] == 1:
            # 첫 열은 그룹 조건 열인 경우가 많다.
            # - 머리글상 상위 조건 열(185쪽)이거나 줄 수가 기준선 수와 다르면(835쪽 'Lower inner casing / 설치운반…')
            #   여러 하위 행에 걸친 조건으로 두고 나눈다.
            # - 줄 수가 기준선 수와 같으면 행 라벨(106쪽 '비계공/보통인부')인지 줄바꿈된 조건
            #   (188쪽 '신구-콘크리트/접착제바르기')인지 좌표로 가릴 수 없다. 이 행은 나누지 않고 현행 조립에 맡긴다.
            if not group_first_col and len(joined) == len(centers):
                return None
            plan[id(c)] = None
            continue
        # 그 밖의 글자 열: 기준선에서 벗어난 줄은 앞 줄에 이어 붙인다(줄바꿈된 직종명 등)
        current = None
        for y, text in joined:
            i = nearest(y, centers)
            if abs(centers[i] - y) > tol and current is not None:
                slots[current] = f"{slots[current]} {text}"
                continue
            if slots[i]:
                current = None
                break
            slots[i], current = text, i
        plan[id(c)] = slots if current is not None and all(slots) else None
    # 행별로 나뉘는 칸이 하나뿐이면 여러 행이 쌓인 것이 아니라 한 칸이 줄바꿈된 것이다
    # (334쪽 규격 '15/(0.38)': 용량과 괄호 보충이 한 행)
    if sum(1 for v in plan.values() if v is not None) < 2:
        return None
    return len(centers), plan


def to_common(table: dict, page_height: float, nested: bool, split_rows: bool = False) -> dict:
    # ODL 좌표는 왼쪽 아래 원점이라 쪽 높이로 뒤집는다
    x0, y0, x1, y1 = table["bounding box"]
    rows = table.get("rows") or []
    # 원래 행마다 몇 개의 하위 행으로 나눌지 먼저 정한다
    splits = {}
    for r, row in enumerate(rows):
        result = (split_row(row.get("cells") or [], first_col_is_group(rows, r, table["number of columns"]))
                  if split_rows else None)
        splits[r] = result
    offsets, total = [], 0
    for r in range(table["number of rows"]):
        offsets.append(total)
        total += splits[r][0] if splits.get(r) else 1
    offsets.append(total)

    cells = []
    for r, row in enumerate(rows):
        for cell in row.get("cells") or []:
            r0, c0 = cell["row number"] - 1, cell["column number"] - 1
            c1 = c0 + cell.get("column span", 1)
            r1 = r0 + cell.get("row span", 1)
            per_row = splits[r][1].get(id(cell)) if splits.get(r) and cell.get("row span", 1) == 1 else None
            if per_row is None:
                cells.append({"r0": offsets[r0], "r1": offsets[r1], "c0": c0, "c1": c1, "text": cell_text(cell)})
            else:
                cells += [{"r0": offsets[r0] + i, "r1": offsets[r0] + i + 1, "c0": c0, "c1": c1, "text": text}
                          for i, text in enumerate(per_row)]
    return {"page": table["page number"],
            "bbox_pt": [round(v, 1) for v in (x0, page_height - y1, x1, page_height - y0)],
            "nested": nested,
            "n_rows": total, "n_cols": table["number of columns"],
            "rows_split": sum(1 for s in splits.values() if s),
            "cells": cells}


def read_tables(json_path: Path, page_heights: dict[int, float], split_rows: bool = False) -> dict[int, list[dict]]:
    """원시 JSON에서 page_heights에 있는 쪽의 표를 모두 공통 표로 바꾼다. 중첩 표도 별도 표로 포함한다.

    split_rows=True면 가로선 없이 한 칸에 쌓인 여러 행을 칸 안 문단 좌표로 나눈다(P2, 기본은 꺼짐).
    """
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    tables: dict[int, list[dict]] = {page: [] for page in page_heights}
    for node, depth in find_tables(doc):
        page = node.get("page number")
        if page in page_heights:
            tables[page].append(to_common(node, page_heights[page], nested=depth > 0, split_rows=split_rows))
    return tables


def to_grid(table: dict, fill_spans: bool = True) -> list[list[str | None]]:
    """공통 표 → 2차원 격자.

    fill_spans=True면 병합 범위의 모든 칸에 같은 글자를 채운다. False면 왼쪽 위 칸에만 둔다.
    빈 칸은 None으로 둔다. ODL은 빈 칸을 ''로 주는데, 현행 clean_table은 None일 때만 위 행 라벨을 이어받는다.
    """
    grid: list[list[str | None]] = [[None] * table["n_cols"] for _ in range(table["n_rows"])]
    # 큰 칸을 먼저 쓰고 작은 칸이 덮어써, 겹친 칸은 더 구체적인 쪽이 남는다
    for cell in sorted(table["cells"], key=lambda c: (c["r1"] - c["r0"]) * (c["c1"] - c["c0"]), reverse=True):
        text = cell["text"] if (cell["text"] or "").strip() else None
        rows = range(cell["r0"], cell["r1"]) if fill_spans else [cell["r0"]]
        cols = range(cell["c0"], cell["c1"]) if fill_spans else [cell["c0"]]
        for r in rows:
            for c in cols:
                grid[r][c] = text
    return grid


if __name__ == "__main__":
    # 확인용: python pipeline/odl_tables.py 185 188 → 해당 쪽의 표 모양과 첫 행을 출력
    import sys
    import tempfile

    import pymupdf

    pdf = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
    pages = [int(p) for p in sys.argv[1:]] or [185]
    with pymupdf.open(pdf) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
    with tempfile.TemporaryDirectory() as tmp:
        run = run_odl(pdf, pages, Path(tmp))
        tables = read_tables(run["json_path"], heights)
    print(f"ODL {run['elapsed_sec']}초")
    for page, page_tables in tables.items():
        for i, table in enumerate(page_tables):
            grid = to_grid(table)
            print(f"p{page} 표{i} {table['n_rows']}x{table['n_cols']} 중첩={table['nested']} bbox={table['bbox_pt']}")
            print("   ", grid[0])
