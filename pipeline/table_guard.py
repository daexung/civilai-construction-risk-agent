"""선 기반 표 누락 감시 (전환 계획 P3, D3).

ODL이 표를 문단으로 내고 경고 없이 넘어가는 경우(396·500쪽 대각선 머리칸 표)를 막는다.
parse.py는 아직 이 모듈을 쓰지 않는다.

적용 범위 (docs/ODL_MIGRATION_PLAN.md 3절):
  감시 대상 = PDF 벡터 선으로 칸이 그려진 표. 아래를 모두 만족하는 "선 표 후보" 영역.
    1. 서로 이어진(세로선으로 연결된) 가로선이 2개 이상이다. 가로선 길이는 본문 폭의 50% 이상이다.
    2. 영역 안쪽(양 끝에서 10pt 넘게 떨어진 곳)에 세로선이 1개 이상 있다.
    3. 영역 높이가 20pt 이상이다.
  제외: 쪽 위아래 띠(쪽 높이의 7%) 안에만 있는 영역. 쪽 번호·장 이름 막대가 여기에 해당한다.
  판정: 후보 영역 넓이 대비 ODL 표 bbox가 덮은 비율로 가른다.
    - 80% 미만: 누락 의심. 그 영역만 PyMuPDF find_tables로 대체 추출하고 extractor=fallback으로 표시한다.
    - 50~80%: 부분 누락 의심. 경고만 남긴다.
  감시하지 못하는 것: 가로선만 있는 표, 선이 없는 표, 이미지 표, 구조·값이 틀린 표, 쪽을 넘어 이어지는 표.
"""
import pymupdf

BODY_WIDTH_RATIO = 0.78      # 본문 폭 ≈ 쪽 폭 × 0.78 (612pt 쪽에서 약 477pt)
MIN_HLINE_RATIO = 0.5        # 가로선 최소 길이 = 본문 폭의 50%
MIN_HEIGHT = 20.0            # 영역 최소 높이(pt)
INNER_MARGIN = 10.0          # 안쪽 세로선 판정 여백(pt)
BAND_RATIO = 0.07            # 쪽 위아래 제외 띠
MISSING_BELOW = 0.8          # 이 비율 미만이면 누락 의심
PARTIAL_BELOW = 0.5          # (구간 50~80%는 부분 누락 의심)
TOL = 2.0                    # 선이 닿았다고 보는 거리(pt)


def line_segments(page) -> tuple[list, list]:
    """축 방향 직선만 가로선·세로선으로 나눈다. 대각선(머리칸 사선)은 쓰지 않는다."""
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] != "l":
                continue
            a, b = item[1], item[2]
            if abs(a.y - b.y) <= 1 and abs(a.x - b.x) > 1:
                horizontal.append((min(a.x, b.x), a.y, max(a.x, b.x), a.y))
            elif abs(a.x - b.x) <= 1 and abs(a.y - b.y) > 1:
                vertical.append((a.x, min(a.y, b.y), a.x, max(a.y, b.y)))
    return horizontal, vertical


def touches(h, v) -> bool:
    return h[0] - TOL <= v[0] <= h[2] + TOL and v[1] - TOL <= h[1] <= v[3] + TOL


def ruled_regions(page) -> list[list[float]]:
    """선 표 후보 영역 bbox 목록 (왼쪽 위 원점, pt)."""
    horizontal, vertical = line_segments(page)
    min_len = page.rect.width * BODY_WIDTH_RATIO * MIN_HLINE_RATIO
    horizontal = [h for h in horizontal if h[2] - h[0] >= min_len]
    segments = [("h", h) for h in horizontal] + [("v", v) for v in vertical]

    # 가로선과 세로선이 닿으면 같은 묶음 (union-find)
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (ki, si) in enumerate(segments):
        for j in range(i + 1, len(segments)):
            kj, sj = segments[j]
            if ki != kj and touches(si if ki == "h" else sj, sj if ki == "h" else si):
                parent[find(i)] = find(j)

    groups: dict[int, list] = {}
    for i, seg in enumerate(segments):
        groups.setdefault(find(i), []).append(seg)

    band = page.rect.height * BAND_RATIO
    regions = []
    for segs in groups.values():
        hs = [s for k, s in segs if k == "h"]
        vs = [s for k, s in segs if k == "v"]
        if len(hs) < 2:
            continue
        x0 = min(s[0] for _, s in segs)
        x1 = max(s[2] for _, s in segs)
        y0 = min(s[1] for _, s in segs)
        y1 = max(s[3] for _, s in segs)
        if y1 - y0 < MIN_HEIGHT:
            continue
        if not any(x0 + INNER_MARGIN < v[0] < x1 - INNER_MARGIN for v in vs):
            continue
        if y1 <= band or y0 >= page.rect.height - band:
            continue
        regions.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
    return sorted(regions, key=lambda r: r[1])


def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def coverage(region, tables) -> float:
    covered = 0.0
    for t in tables:
        b = t["bbox_pt"]
        covered += area([max(region[0], b[0]), max(region[1], b[1]), min(region[2], b[2]), min(region[3], b[3])])
    return min(1.0, covered / area(region)) if area(region) else 1.0


def merge_edges(values, tol: float = 1.0) -> list[float]:
    edges = []
    for v in sorted(values):
        if not edges or v - edges[-1] > tol:
            edges.append(v)
    return edges


def nearest_edge(edges, v) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def pymupdf_to_common(table, page_no: int) -> dict:
    """PyMuPDF 표 → 공통 표. 칸 상자 좌표로 병합 범위를 복원한다(experiments/parser_bench/extract_pymupdf.py와 같은 방식)."""
    extract = table.extract()
    row_boxes = [row.bbox for row in table.rows]
    x_edges = merge_edges([v for row in table.rows for cell in row.cells if cell for v in (cell[0], cell[2])])
    cells = []
    for i, row in enumerate(table.rows):
        for j, box in enumerate(row.cells):
            if box is None:
                continue
            r1 = i + 1
            while r1 < len(row_boxes) and row_boxes[r1][3] <= box[3] + 1.0:
                r1 += 1
            cells.append({"r0": i, "r1": r1, "c0": nearest_edge(x_edges, box[0]), "c1": nearest_edge(x_edges, box[2]),
                          "text": extract[i][j] or ""})
    return {"page": page_no, "bbox_pt": [round(v, 1) for v in table.bbox], "nested": False,
            "n_rows": len(row_boxes), "n_cols": len(x_edges) - 1, "cells": cells,
            "extractor": "fallback", "rows_split": 0}


def fallback_tables(page, region, page_no: int) -> list[dict]:
    """누락 의심 영역의 표를 PyMuPDF로 뽑는다.

    find_tables(clip=영역)은 잘린 영역에서 격자를 다르게 잡아 병합 칸 글자를 잃는다(500쪽 첫 열 라벨).
    그래서 쪽 전체에서 표를 찾고, 영역과 IoU 0.5 이상 겹치는 표만 쓴다.
    """
    out = []
    for table in page.find_tables().tables:
        b = list(table.bbox)
        inter = area([max(region[0], b[0]), max(region[1], b[1]), min(region[2], b[2]), min(region[3], b[3])])
        union = area(region) + area(b) - inter
        if union and inter / union >= 0.5:
            out.append(pymupdf_to_common(table, page_no))
    return out


def guard(pdf_path, tables_by_page: dict[int, list[dict]]) -> tuple[dict[int, list[dict]], list[dict]]:
    """쪽마다 선 표 후보를 ODL 표와 대조한다. 누락 의심 영역은 대체 추출한 표를 덧붙인다.

    반환: (대체 추출이 덧붙은 표 목록, 영역별 판정 기록)
    """
    result = {page: list(tables) for page, tables in tables_by_page.items()}
    log = []
    with pymupdf.open(pdf_path) as doc:
        for page_no, tables in tables_by_page.items():
            page = doc[page_no - 1]
            for region in ruled_regions(page):
                cov = coverage(region, tables)
                status = "covered" if cov >= MISSING_BELOW else ("partial" if cov >= PARTIAL_BELOW else "missing")
                entry = {"page": page_no, "region": region, "coverage": round(cov, 3), "status": status}
                if status == "missing":
                    added = fallback_tables(page, region, page_no)
                    result[page_no] += added
                    entry["fallback_tables"] = [f"{t['n_rows']}x{t['n_cols']}" for t in added]
                log.append(entry)
    return result, log
