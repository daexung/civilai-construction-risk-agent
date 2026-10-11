"""OpenDataLoader PDF(로컬 모드)의 표 출력을 공통 표 형식으로 바꾸는 어댑터.

전환 계획(docs/ODL_MIGRATION_PLAN.md) P1 단계의 산출물이다. parse.py는 아직 이 모듈을 쓰지 않는다.

흐름:
    run_odl(pdf, pages, out_dir)          → ODL CLI 실행, 원시 JSON 경로 반환
    read_tables(json_path, page_heights)  → {쪽 번호: [공통 표, ...]}
    to_grid(table)                        → 현행 조립 로직(clean_table)에 넣을 2차원 격자

공통 표:
    {"page", "bbox_pt": [x0, y0, x1, y1] (왼쪽 위 원점), "bbox_native" (왼쪽 아래 원점, ODL 그대로), "coord", "nested": bool,
     "n_rows", "n_cols", "row_splits", "row_map",
     "cells": [{"r0", "r1", "c0", "c1", "text", "bbox_pt", "odl_cell", "split"}]}   # r1·c1은 끝을 포함하지 않는다

2026-10-11 변경: 행 분리의 근거(split_row)와 좌표 종류를 명시해 전달한다. PDF 글자 기준선(probe)이 있으면 쓴다.

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


def run_odl(pdf: Path, pages: list[int], out_dir: Path, java: Path | None = None, jar: Path | None = None,
            table_method: str = "default") -> dict:
    """지정한 쪽만 ODL로 추출한다. 반환값은 원시 JSON 경로와 실행 기록."""
    java = Path(java or os.environ.get("ODL_JAVA") or DEFAULT_JAVA)
    jar = Path(jar or os.environ.get("ODL_JAR") or DEFAULT_JAR)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(java), "-jar", str(jar), "-f", "json", "--keep-line-breaks", "--table-method", table_method,
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

# 같은 행으로 보는 PDF 글자 기준선 차이(pt). 실제 표에서 같은 행은 0.00, 줄바꿈된 이름 칸은 0.6 이상이었다
ALIGN_TOL = 0.3

# 행 기준선이 되는 값: 숫자, 괄호 숫자, 범위, 백분율, 이하·이상, 분류번호(0301-0057), '-', '〃'
VALUE_RE = re.compile(r"^(?:[-–〃]|\(?\d[\d.,\-]*\)?(?:[~∼]\d[\d.,]*)?(?:%|이하|이상|미만|초과)?)$")
# 앞 줄에 딸린 설명·보충 줄
CONTINUATION_PREFIXES = ("-", "(", "※")


def cell_lines(cell: dict, probe=None, page: int | None = None):
    """칸의 줄을 (세로 위치, 글자)로 위에서 아래 순서로 내고, 위치의 종류를 함께 낸다.

    반환 (줄 목록, 위치 종류). 좌표를 알 수 없는 내용이 있으면 (None, None).
    위치 종류
      pdf_baseline        probe(PDF 글자층)가 있고 글자 줄 수가 ODL 줄 수와 같을 때의 실제 기준선
      paragraph_estimate  문단 bbox를 줄 수로 나눈 추정 위치(실제 글자 좌표가 아니다)
    """
    # 칸 글(cell_text)과 같은 순서로 글 노드를 모은다. 글이 든 노드는 자기 좌표를 가져야 하고, 표가 섞이면 쓰지 않는다
    nodes = []
    usable = True

    def walk(n):
        nonlocal usable
        if isinstance(n, dict):
            if n.get("type") == "table":
                usable = False
                return
            if isinstance(n.get("content"), str):
                if "bounding box" not in n:
                    usable = False
                    return
                nodes.append(n)
            for key in CHILD_KEYS:
                for child in n.get(key) or []:
                    walk(child)

    for key in CHILD_KEYS:
        for kid in cell.get(key) or []:
            walk(kid)
    if not usable:
        return None, None
    lines = []
    for node in nodes:
        texts = node["content"].split("\n")
        _, bottom, _, top = node["bounding box"]
        height = (top - bottom) / len(texts)
        lines += [(top - (i + 0.5) * height, text) for i, text in enumerate(texts)]
    lines.sort(key=lambda line: -line[0])
    if probe is not None and page is not None and "bounding box" in cell and lines and all(t.strip() for _, t in lines):
        base = probe(page, cell["bounding box"])
        if len(base) == len(lines):
            return [(y, t) for y, (_, t) in zip(base, lines)], "pdf_baseline"
    return lines, "paragraph_estimate"


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


def split_row(cells: list[dict], group_first_col: bool = False, probe=None, page: int | None = None):
    """한 ODL 행을 하위 행으로 나눈다. 행 분리의 유일한 판정 지점이다.

    반환 (결과, 근거). 결과는 None(나누지 않음) 또는 (하위 행 수, {칸 id: 하위 행별 글자 목록 또는 None(병합 칸으로 둠)}).
    근거 info: coord_kind(pdf_baseline|paragraph_estimate), label_decisions(첫 열 판정), reason(나누지 않은 이유)
    group_first_col=True면 첫 열은 여러 하위 행에 걸친 조건으로 보고 나누지 않는다.

    판정 순서
      1. 숫자가 줄로 쌓인 칸의 줄 위치(기준선)가 행의 기준선이다. 서로 다른 기준선 둘 이상이어야 한다.
      2. 첫 열 줄 수가 기준선 수와 같으면, 실제 PDF 기준선이 숫자 칸과 일치할 때(차이 ALIGN_TOL 이하)만 행 라벨로 나눈다.
         일치하지 않으면 줄바꿈된 이름(여러 행에 걸친 조건)이다. 추정 위치만 있으면 가릴 수 없어 나누지 않는다.
      3. 그 밖의 글자 열은 기준선 가까운 줄을 그 행에, 벗어난 줄은 앞 줄에 이어 붙인다.
    """
    info = {"coord_kind": None, "label_decisions": {}, "reason": None}
    single = [c for c in cells if c.get("row span", 1) == 1]
    lines, kinds = {}, {}
    for c in single:
        got, kind = cell_lines(c, probe, page)
        if got is None:
            info["reason"] = "칸 안에 문단이 아닌 내용(표·목록)이 있거나 좌표가 없음"
            return None, info
        lines[id(c)], kinds[id(c)] = got, kind
    numeric = [c for c in single if len(lines[id(c)]) >= 2
               and all(VALUE_RE.match(re.sub(r"\s+", "", t)) for _, t in lines[id(c)])]
    if not numeric:
        info["reason"] = "숫자가 줄로 쌓인 칸이 없음"
        return None, info
    actual = all(kinds[id(c)] == "pdf_baseline" for c in numeric)
    info["coord_kind"] = "pdf_baseline" if actual else "paragraph_estimate"
    # 숫자 칸마다 줄 수가 다르면(규격 '1 / (11.19)'처럼 괄호 보충 줄이 붙은 칸) 가장 흔한 줄 수가 행 수다.
    # 줄 수가 더 많은 칸은 '(' '-' '※'로 시작하는 보충 줄을 앞 줄에 이어 붙여 행 수와 같아질 때만 그렇게 읽는다
    counts = {}
    for c in numeric:
        counts[len(lines[id(c)])] = counts.get(len(lines[id(c)]), 0) + 1
    if len(counts) > 1:
        rows_n = max(counts, key=lambda n: (counts[n], -n))
        for c in numeric:
            if len(lines[id(c)]) > rows_n:
                merged = join_continuations(lines[id(c)])
                if len(merged) == rows_n:
                    lines[id(c)] = merged
                    info.setdefault("merged_continuations", []).append(c["column number"])

    tol = 0.6 * line_height(single)
    anchors: list[list[float]] = []
    for y in sorted((y for c in numeric for y, _ in lines[id(c)]), reverse=True):
        if anchors and abs(sum(anchors[-1]) / len(anchors[-1]) - y) <= tol:
            anchors[-1].append(y)
        else:
            anchors.append([y])
    centers = [sum(a) / len(a) for a in anchors]
    if len(centers) < 2:
        info["reason"] = "서로 다른 숫자 기준선이 하나뿐"
        return None, info
    info["anchors"] = [round(c, 2) for c in centers]       # 하위 행의 세로 위치(ODL 좌표, 왼쪽 아래 원점)

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
                    info["reason"] = "숫자 줄이 기준선에 맞지 않음"
                    return None, info
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
            #   여러 하위 행에 걸친 조건으로 두고 나누지 않는다.
            # - 줄 수가 기준선 수와 같으면 행 라벨(106쪽 '비계공/보통인부')인지 줄바꿈된 조건
            #   (188쪽 '신구-콘크리트/접착제바르기')인지 추정 좌표로는 가릴 수 없다. 실제 기준선이 있으면 일치 여부로 가린다.
            if not group_first_col and len(joined) == len(centers):
                if actual and kinds[id(c)] == "pdf_baseline" and len(joined) == len(cl):
                    dev = max(abs(y - centers[i]) for i, (y, _) in enumerate(joined))
                    if dev <= ALIGN_TOL:
                        plan[id(c)] = [t for _, t in joined]
                        info["label_decisions"][1] = f"행 라벨(PDF 기준선 일치, 최대 차이 {dev:.2f}pt)"
                        continue
                    info["label_decisions"][1] = f"줄바꿈된 이름(PDF 기준선 불일치, 최대 차이 {dev:.2f}pt)"
                    plan[id(c)] = None
                    continue
                info["reason"] = "첫 열 줄 수가 행 수와 같아 행 라벨인지 줄바꿈인지 추정 위치로는 가릴 수 없음"
                return None, info
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
        info["reason"] = "나뉘는 칸이 하나뿐(칸 안 줄바꿈)"
        return None, info
    return (len(centers), plan), info


def stacked_candidate(cells: list[dict], probe=None, page: int | None = None) -> dict | None:
    """어댑터가 나누지 않은 행에 줄이 쌓인 칸이 둘 이상이면 후보로 기록한다(보류 대상).

    PDF 기준선이 있으면, 줄 수가 같은 칸끼리 기준선이 일치하는지(aligned)를 함께 낸다.
    """
    multi = []
    for c in cells:
        if c.get("row span", 1) != 1 or any(find_tables(c)):
            continue
        text = cell_text(c)
        got = [t for t in text.split("\n") if t.strip()]
        if len(got) >= 2:
            multi.append((c, got))
    if len(multi) < 2:
        return None
    out = {"columns": [c["column number"] for c, _ in multi], "line_counts": [len(g) for _, g in multi], "aligned": None}
    if probe is not None and page is not None:
        bases = {}
        for c, got in multi:
            if "bounding box" in c:
                b = probe(page, c["bounding box"])
                if len(b) == len(got):
                    bases.setdefault(len(got), []).append(b)
        if bases:
            out["aligned"] = all(len(v) >= 2 and all(max(abs(x - y) for x, y in zip(v[0], w)) <= ALIGN_TOL for w in v[1:])
                                 for v in bases.values() if len(v) >= 2) and any(len(v) >= 2 for v in bases.values())
    return out


def to_common(table: dict, page_height: float, nested: bool, split_rows: bool = False, probe=None,
              height_source: str = "호출자가 준 값") -> dict:
    """ODL 표 -> 공통 표.

    ODL 좌표는 왼쪽 아래 원점이라 쪽 높이로 뒤집어 bbox_pt(왼쪽 위 원점)를 만든다. 원래 좌표는 bbox_native에 남긴다.
    칸마다 odl_cell(원래 칸 식별·좌표)과 split(행 분리 기록)을 명시한다. 같은 좌표가 반복됐는지로 추측하지 않는다.
    표에는 row_splits(분리한 행의 근거)와 row_map(격자 행마다 split|stacked_unsplit|single)을 둔다.
    """
    x0, y0, x1, y1 = table["bounding box"]
    page = table.get("page number")
    rows = table.get("rows") or []
    # 원래 행마다 몇 개의 하위 행으로 나눌지 먼저 정한다
    splits, infos = {}, {}
    for r, row in enumerate(rows):
        if split_rows:
            splits[r], infos[r] = split_row(row.get("cells") or [], first_col_is_group(rows, r, table["number of columns"]),
                                            probe, page)
        else:
            splits[r], infos[r] = None, {"coord_kind": None, "label_decisions": {}, "reason": "행 분리를 끔"}
    offsets, total = [], 0
    for r in range(table["number of rows"]):
        offsets.append(total)
        total += splits[r][0] if splits.get(r) else 1
    offsets.append(total)

    cells = []
    for r, row in enumerate(rows):
        res, info = splits.get(r), infos.get(r)
        for cell in row.get("cells") or []:
            r0, c0 = cell["row number"] - 1, cell["column number"] - 1
            c1 = c0 + cell.get("column span", 1)
            r1 = r0 + cell.get("row span", 1)
            per_row = res[1].get(id(cell)) if res and cell.get("row span", 1) == 1 else None
            # 칸 좌표(왼쪽 위 원점). 하위 행으로 나눈 칸은 원래 칸 좌표를 그대로 쓴다
            bx0, by0, bx1, by1 = cell.get("bounding box") or table["bounding box"]
            box = [round(bx0, 1), round(page_height - by1, 1), round(bx1, 1), round(page_height - by0, 1)]
            origin = {"id": cell.get("id"), "row": cell["row number"], "col": cell["column number"],
                      "row_span": cell.get("row span", 1), "col_span": cell.get("column span", 1),
                      "bbox_native": [round(v, 1) for v in (bx0, by0, bx1, by1)]}
            if per_row is None:
                split = ({"role": "span_in_split_row", "odl_row": r + 1, "of": res[0], "coord_kind": info["coord_kind"]}
                         if res and cell.get("row span", 1) == 1 else None)
                cells.append({"r0": offsets[r0], "r1": offsets[r1], "c0": c0, "c1": c1, "text": cell_text(cell),
                              "bbox_pt": box, "odl_cell": origin, "split": split})
            else:
                confirmed = info["coord_kind"] == "pdf_baseline"
                cells += [{"r0": offsets[r0] + i, "r1": offsets[r0] + i + 1, "c0": c0, "c1": c1, "text": text,
                           "bbox_pt": box, "odl_cell": origin,
                           "split": {"role": "piece", "odl_row": r + 1, "index": i, "of": res[0],
                                     "basis": "numeric_line_anchors", "coord_kind": info["coord_kind"],
                                     "confirmed": confirmed, "orig_lines": len(per_row), "orig_text": cell_text(cell)}}
                          for i, text in enumerate(per_row)]
    # 분리 기록과 격자 행 상태
    row_splits, row_map = [], []
    for r in range(table["number of rows"]):
        res = splits.get(r)
        info = infos.get(r) or {"coord_kind": None, "label_decisions": {}, "reason": None}
        if res:
            row_splits.append({"odl_row": r + 1, "first_grid_row": offsets[r], "sub_rows": res[0],
                               "basis": "numeric_line_anchors", "coord_kind": info["coord_kind"],
                               "confirmed": info["coord_kind"] == "pdf_baseline", "anchors": info.get("anchors"),
                               "label_decisions": info["label_decisions"]})
            row_map += [{"odl_row": r + 1, "state": "split", "coord_kind": info["coord_kind"]}] * res[0]
            continue
        cand = stacked_candidate(rows[r].get("cells") or [], probe, page) if r < len(rows) and split_rows else None
        if cand:
            row_map.append({"odl_row": r + 1, "state": "stacked_unsplit", "reason": info["reason"], **cand})
        else:
            row_map.append({"odl_row": r + 1, "state": "single"})
    return {"page": page,
            "bbox_pt": [round(v, 1) for v in (x0, page_height - y1, x1, page_height - y0)],
            "bbox_native": [round(v, 1) for v in (x0, y0, x1, y1)],
            "coord": {"native_origin": "왼쪽 아래(ODL·PDF 점)", "bbox_pt_origin": "왼쪽 위", "page_height": page_height,
                      "page_height_source": height_source},
            "nested": nested,
            "contains_nested_table": any(find_tables(c) for row in rows for c in row.get("cells") or []),
            "n_rows": total, "n_cols": table["number of columns"],
            "rows_split": sum(1 for s in splits.values() if s),
            "row_splits": row_splits, "row_map": row_map,
            "cells": cells}


def read_tables(json_path: Path, page_heights: dict[int, float], split_rows: bool = False, probe=None,
                height_source: str = "호출자가 준 값") -> dict[int, list[dict]]:
    """원시 JSON에서 page_heights에 있는 쪽의 표를 모두 공통 표로 바꾼다. 중첩 표도 별도 표로 포함한다.

    split_rows=True면 가로선 없이 한 칸에 쌓인 여러 행을 숫자 줄의 위치로 나눈다(기본은 꺼짐).
    probe가 있으면 PDF 글자의 실제 기준선을 쓴다(structure_rules.PdfProbe).
    """
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    tables: dict[int, list[dict]] = {page: [] for page in page_heights}
    for node, depth in find_tables(doc):
        page = node.get("page number")
        if page in page_heights:
            tables[page].append(to_common(node, page_heights[page], nested=depth > 0, split_rows=split_rows,
                                          probe=probe, height_source=height_source))
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
