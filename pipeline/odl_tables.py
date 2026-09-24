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


def to_common(table: dict, page_height: float, nested: bool) -> dict:
    # ODL 좌표는 왼쪽 아래 원점이라 쪽 높이로 뒤집는다
    x0, y0, x1, y1 = table["bounding box"]
    cells = []
    for row in table.get("rows") or []:
        for cell in row.get("cells") or []:
            r0, c0 = cell["row number"] - 1, cell["column number"] - 1
            cells.append({"r0": r0, "r1": r0 + cell.get("row span", 1),
                          "c0": c0, "c1": c0 + cell.get("column span", 1),
                          "text": cell_text(cell)})
    return {"page": table["page number"],
            "bbox_pt": [round(v, 1) for v in (x0, page_height - y1, x1, page_height - y0)],
            "nested": nested,
            "n_rows": table["number of rows"], "n_cols": table["number of columns"],
            "cells": cells}


def read_tables(json_path: Path, page_heights: dict[int, float]) -> dict[int, list[dict]]:
    """원시 JSON에서 page_heights에 있는 쪽의 표를 모두 공통 표로 바꾼다. 중첩 표도 별도 표로 포함한다."""
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    tables: dict[int, list[dict]] = {page: [] for page in page_heights}
    for node, depth in find_tables(doc):
        page = node.get("page number")
        if page in page_heights:
            tables[page].append(to_common(node, page_heights[page], nested=depth > 0))
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
