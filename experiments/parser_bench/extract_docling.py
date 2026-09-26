"""Docling으로 5개 표를 공통 표 형식으로 저장한다.

- 입력은 extract_pymupdf.py가 만든 단쪽 PDF(results/pages/pNNN.pdf). 원문과 쪽 크기·좌표가 같다.
- 디지털 원문이라 OCR은 끈다. 표 구조 인식(TableFormer)은 켠다.
- 원시 DoclingDocument를 쪽별로 보관하고, 정답 bbox와 겹침(IoU)이 가장 큰 표를 대상 표로 고른다.

실행(Docling 전용 환경):
  .venv-docling/Scripts/python.exe experiments/parser_bench/extract_docling.py --name docling_accurate
  .venv-docling/Scripts/python.exe experiments/parser_bench/extract_docling.py --name docling_accurate_nomatch --no-cell-matching
"""
import argparse
import importlib.metadata as md
import time

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

from common import PAGES_DIR, PDF, RESULTS, iou, load_goldens, save_json


def table_bbox_top_left(table, doc) -> list[float]:
    prov = table.prov[0]
    height = doc.pages[prov.page_no].size.height
    box = prov.bbox.to_top_left_origin(page_height=height)
    return [box.l, box.t, box.r, box.b]


def to_common(table) -> dict:
    cells = []
    for cell in table.data.table_cells:
        cells.append({
            "r0": cell.start_row_offset_idx, "r1": cell.end_row_offset_idx,
            "c0": cell.start_col_offset_idx, "c1": cell.end_col_offset_idx,
            "text": cell.text or "",
            "column_header": bool(cell.column_header), "row_header": bool(cell.row_header),
        })
    return {"n_rows": table.data.num_rows, "n_cols": table.data.num_cols, "cells": cells}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--mode", choices=["accurate", "fast"], default="accurate")
    parser.add_argument("--no-cell-matching", action="store_true")
    parser.add_argument("--source", choices=["pages", "full"], default="pages",
                        help="pages: 단쪽 PDF / full: 원본 전체 PDF에서 page_range로 해당 쪽만")
    parser.add_argument("--pages", nargs="*", type=int, help="기본값: 정답 표가 있는 쪽")
    args = parser.parse_args()

    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE if args.mode == "accurate" else TableFormerMode.FAST
    options.table_structure_options.do_cell_matching = not args.no_cell_matching

    t0 = time.perf_counter()
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    converter.initialize_pipeline(InputFormat.PDF)
    init_sec = time.perf_counter() - t0

    goldens = load_goldens()
    out_dir = RESULTS / args.name
    tables, page_times, candidates = {}, {}, {}
    pages = args.pages or sorted({g["source"]["pdf_page"] for g in goldens.values()})
    for page_no in pages:
        t1 = time.perf_counter()
        if args.source == "full":
            doc = converter.convert(str(PDF), page_range=(page_no, page_no)).document
        else:
            doc = converter.convert(str(PAGES_DIR / f"p{page_no}.pdf")).document
        page_times[page_no] = round(time.perf_counter() - t1, 2)
        save_json(out_dir / "raw" / f"p{page_no}.json", doc.export_to_dict())
        (out_dir / "raw" / f"p{page_no}.md").write_text(doc.export_to_markdown(), encoding="utf-8")

        found = [(t, table_bbox_top_left(t, doc)) for t in doc.tables]
        save_json(out_dir / "raw" / f"p{page_no}_all_tables.json",
                  [dict(to_common(t), bbox_pt=[round(v, 1) for v in box]) for t, box in found])
        for tid, golden in goldens.items():
            if golden["source"]["pdf_page"] != page_no:
                continue
            target = golden["source"]["table_bbox_pt"]
            scored = sorted(((iou(box, target), t, box) for t, box in found), key=lambda x: x[0], reverse=True)
            candidates[tid] = [{"iou": round(s, 3), "bbox_pt": [round(v, 1) for v in b]} for s, _, b in scored[:3]]
            if not scored or scored[0][0] < 0.3:
                continue
            best_iou, best, box = scored[0]
            entry = to_common(best)
            entry.update({"id": tid, "page": page_no, "bbox_pt": [round(v, 1) for v in box],
                          "match_iou": round(best_iou, 3), "tables_on_page": len(found)})
            tables[tid] = entry

    save_json(out_dir / "tables.json", {
        "parser": "Docling",
        "version": md.version("docling"),
        "versions": {p: md.version(p) for p in ("docling", "docling-core", "docling-ibm-models", "docling-parse", "torch")},
        "config": {
            "do_ocr": options.do_ocr,
            "do_table_structure": options.do_table_structure,
            "table_mode": str(options.table_structure_options.mode),
            "do_cell_matching": options.table_structure_options.do_cell_matching,
            "table_structure_options": repr(options.table_structure_options),
            "device": "cpu",
            "source": "원본 전체 PDF (page_range)" if args.source == "full" else "단쪽 PDF",
        },
        "init_sec": round(init_sec, 2),
        "page_sec": page_times,
        "elapsed_sec": round(init_sec + sum(page_times.values()), 2),
        "match_candidates": candidates,
        "tables": tables,
    })
    print(f"초기화 {init_sec:.1f}초, 쪽별 {page_times}")
    for tid in goldens:
        t = tables.get(tid)
        print(f"{tid}: " + (f"IoU={t['match_iou']} 격자 {t['n_rows']}x{t['n_cols']} 셀 {len(t['cells'])}" if t else f"매칭 실패 {candidates.get(tid)}"))


if __name__ == "__main__":
    main()
