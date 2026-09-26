"""기준선: PyMuPDF find_tables()로 5개 표를 공통 표 형식으로 저장한다.

- 병합 범위는 rows[].cells의 셀 좌표에서 복원한다(extract()는 병합을 평탄화하므로).
- 운영 파이프라인과 똑같은 입력을 재현하려고 extract() 결과도 함께 저장한다.
- Docling 등 다른 파서 입력용으로 대상 쪽만 떼어 낸 단쪽 PDF도 만든다.

실행(저장소 루트, 기존 .venv): python experiments/parser_bench/extract_pymupdf.py
"""
import time

import pymupdf

from common import PAGES_DIR, PDF, RESULTS, iou, load_goldens, save_json


def merge_edges(values, tol=1.0) -> list[float]:
    edges = []
    for v in sorted(values):
        if not edges or v - edges[-1] > tol:
            edges.append(v)
    return edges


def nearest(edges, v) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def to_common(table) -> dict:
    extract = table.extract()
    row_boxes = [row.bbox for row in table.rows]
    xs = [v for row in table.rows for cell in row.cells if cell for v in (cell[0], cell[2])]
    x_edges = merge_edges(xs)

    cells = []
    for i, row in enumerate(table.rows):
        for j, box in enumerate(row.cells):
            if box is None:
                continue
            r1 = i + 1
            while r1 < len(row_boxes) and row_boxes[r1][3] <= box[3] + 1.0:
                r1 += 1
            cells.append({
                "r0": i, "r1": r1,
                "c0": nearest(x_edges, box[0]), "c1": nearest(x_edges, box[2]),
                "text": extract[i][j] or "",
            })

    return {
        "n_rows": len(row_boxes),
        "n_cols": len(x_edges) - 1,
        "cells": cells,
        "extract": extract,
    }


def open_page(source: str, page_no: int):
    """source=full이면 원본 PDF의 해당 쪽, pages면 단쪽 PDF의 첫 쪽. (문서, 쪽) 반환."""
    if source == "full":
        doc = pymupdf.open(PDF)
        return doc, doc[page_no - 1]
    doc = pymupdf.open(PAGES_DIR / f"p{page_no}.pdf")
    return doc, doc[0]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="pymupdf")
    parser.add_argument("--source", choices=["full", "pages"], default="full",
                        help="full: 원본 전체 PDF(운영과 같음) / pages: 단쪽 PDF")
    parser.add_argument("--pages", nargs="*", type=int, help="기본값: 정답 표가 있는 쪽")
    parser.add_argument("--make-page-pdfs", action="store_true", help="다른 파서 입력용 단쪽 PDF 생성")
    args = parser.parse_args()

    goldens = load_goldens()
    pages = args.pages or sorted({g["source"]["pdf_page"] for g in goldens.values()})
    out_dir = RESULTS / args.name
    started = time.perf_counter()
    tables = {}
    for page_no in pages:
        doc, page = open_page(args.source, page_no)
        found = page.find_tables().tables
        save_json(out_dir / "raw" / f"p{page_no}_all_tables.json",
                  [dict(to_common(t), bbox_pt=[round(v, 1) for v in t.bbox]) for t in found])
        for tid, golden in goldens.items():
            if golden["source"]["pdf_page"] != page_no or not found:
                continue
            target = golden["source"]["table_bbox_pt"]
            best = max(found, key=lambda t: iou(t.bbox, target))
            entry = to_common(best)
            entry.update({"id": tid, "page": page_no, "bbox_pt": [round(v, 1) for v in best.bbox],
                          "match_iou": round(iou(best.bbox, target), 3), "tables_on_page": len(found)})
            tables[tid] = entry
        doc.close()

    if args.make_page_pdfs:
        with pymupdf.open(PDF) as doc:
            for page_no in pages:
                single = pymupdf.open()
                single.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
                PAGES_DIR.mkdir(parents=True, exist_ok=True)
                single.save(PAGES_DIR / f"p{page_no}.pdf")
                single.close()

    elapsed = time.perf_counter() - started
    save_json(out_dir / "tables.json", {
        "parser": "PyMuPDF",
        "version": pymupdf.__doc__.split(":")[0],
        "config": {"method": "page.find_tables() 기본값", "spans": "rows[].cells 좌표에서 복원",
                   "source": "원본 전체 PDF" if args.source == "full" else "단쪽 PDF"},
        "elapsed_sec": round(elapsed, 2),
        "tables": tables,
    })
    for tid, t in tables.items():
        print(f"{tid} p{t['page']} IoU={t['match_iou']} 격자 {t['n_rows']}x{t['n_cols']} 셀 {len(t['cells'])}")
    print(f"소요 {elapsed:.2f}초 → {out_dir / 'tables.json'}")


if __name__ == "__main__":
    main()
