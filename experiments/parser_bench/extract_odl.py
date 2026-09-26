"""OpenDataLoader PDF로 5개 표를 공통 표 형식으로 저장한다.

- 입력은 extract_pymupdf.py가 만든 단쪽 PDF(results/pages/pNNN.pdf).
- Java CLI(jar)를 직접 호출한다. 실행한 명령줄, 콘솔 로그, 원시 JSON·HTML을 모두 보존한다.
- ODL 좌표는 왼쪽 아래 원점이라 쪽 높이로 뒤집어 정답 bbox(왼쪽 위 원점)와 비교한다.

실행(저장소 루트 기준, 기존 .venv의 Python으로 스크립트를 돌리고 Java는 .venv-odl/jre를 쓴다):
  local : python experiments/parser_bench/extract_odl.py --name odl_local
  hybrid: (서버 먼저) .venv-odl/Scripts/opendataloader-pdf-hybrid --port 5002 --no-ocr --device cpu
          python experiments/parser_bench/extract_odl.py --name odl_hybrid_auto --hybrid auto
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import pymupdf

from common import PAGES_DIR, PDF, RESULTS, ROOT, iou, load_goldens, save_json

# ODL JSON에서 자식 노드가 들어가는 키. 목록('list items') 안에 표나 문장이 중첩되는 경우가 있다
# (예: 185쪽 비고 칸의 '- ' 문장들, 188쪽 [주] ② 목록 항목 안의 층별 할증률 표).
CHILD_KEYS = ("kids", "rows", "cells", "list items")

ODL_ENV = ROOT / ".venv-odl"
JAVA = ODL_ENV / "jre/bin/java.exe"
JAR = ODL_ENV / "Lib/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar"


def cell_text(node) -> str:
    """셀 안 kids를 따라가며 content를 모은다. 중첩 표가 있으면 그 글자도 이어 붙는다."""
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("content"), str):
                parts.append(n["content"])
            for key in CHILD_KEYS:
                for child in n.get(key, []) or []:
                    walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    for key in CHILD_KEYS:
        for kid in node.get(key, []) or []:
            walk(kid)
    return "\n".join(parts)


def find_tables(node, found=None, depth=0) -> list[tuple[dict, int]]:
    """문서 트리 전체에서 표 노드를 찾는다. depth > 0이면 다른 표의 칸 안에 들어 있는 중첩 표다."""
    found = [] if found is None else found
    if isinstance(node, dict):
        is_table = node.get("type") == "table"
        if is_table:
            found.append((node, depth))
        for key in CHILD_KEYS:
            for child in node.get(key, []) or []:
                find_tables(child, found, depth + (1 if is_table else 0))
    elif isinstance(node, list):
        for child in node:
            find_tables(child, found, depth)
    return found


def to_common(table) -> dict:
    cells = []
    for row in table.get("rows", []):
        for cell in row.get("cells", []):
            r0 = cell["row number"] - 1
            c0 = cell["column number"] - 1
            cells.append({
                "r0": r0, "r1": r0 + cell.get("row span", 1),
                "c0": c0, "c1": c0 + cell.get("column span", 1),
                "text": cell_text(cell),
            })
    return {"n_rows": table["number of rows"], "n_cols": table["number of columns"], "cells": cells}


def top_left_bbox(box, page_height) -> list[float]:
    x0, y0, x1, y1 = box
    return [x0, page_height - y1, x1, page_height - y0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--hybrid", choices=["off", "auto", "full"], default="off")
    parser.add_argument("--hybrid-url", default="http://localhost:5002")
    parser.add_argument("--table-method", choices=["default", "cluster"], default="default")
    parser.add_argument("--content-safety-off", default=None,
                        help="진단용. 예: background. 기본값(None)은 ODL 안전 필터를 모두 켠 상태")
    parser.add_argument("--source", choices=["pages", "full"], default="pages",
                        help="pages: 단쪽 PDF들 / full: 원본 전체 PDF에 --pages로 해당 쪽만")
    parser.add_argument("--pages", nargs="*", type=int, help="기본값: 정답 표가 있는 쪽")
    parser.add_argument("--include-nested", action="store_true",
                        help="칸 안의 중첩 표도 별도 표로 저장(PyMuPDF 어댑터와 같은 조건). 기본은 바깥 표만(기존 5표 실험 조건)")
    args = parser.parse_args()

    goldens = load_goldens()
    pages = args.pages or sorted({g["source"]["pdf_page"] for g in goldens.values()})
    out_dir = RESULTS / args.name
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(JAVA), "-jar", str(JAR), "-f", "json,html", "--keep-line-breaks",
           "--table-method", args.table_method, "-o", str(raw_dir)]
    if args.hybrid != "off":
        cmd += ["--hybrid", "docling-fast", "--hybrid-mode", args.hybrid, "--hybrid-url", args.hybrid_url]
    if args.content_safety_off:
        cmd += ["--content-safety-off", args.content_safety_off]
    if args.source == "full":
        cmd += ["--pages", ",".join(str(p) for p in pages), str(PDF)]
    else:
        cmd += [str(PAGES_DIR / f"p{p}.pdf") for p in pages]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - t0
    (raw_dir / "console.log").write_text(
        f"$ {' '.join(cmd)}\n\n[exit {proc.returncode}]\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
        encoding="utf-8")

    java_version = subprocess.run([str(JAVA), "-version"], capture_output=True, text=True).stderr.splitlines()[0]
    tables, candidates, nested = {}, {}, {}
    full_json = raw_dir / f"{PDF.stem}.json"
    full_tables = find_tables(json.loads(full_json.read_text(encoding="utf-8"))) if args.source == "full" and full_json.exists() else []
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
    for page_no in pages:
        height = heights[page_no]
        if args.source == "full":
            # 원본 PDF 출력은 한 파일이며 표마다 원래 쪽 번호가 붙는다
            found = [(t, d) for t, d in full_tables if t.get("page number") == page_no]
        else:
            json_path = raw_dir / f"p{page_no}.json"
            if not json_path.exists():
                continue
            found = find_tables(json.loads(json_path.read_text(encoding="utf-8")))
        boxes = [(t, depth, top_left_bbox(t["bounding box"], height)) for t, depth in found]
        nested[page_no] = sum(1 for _, d, _ in boxes if d > 0)
        save_json(raw_dir / f"p{page_no}_all_tables.json",
                  [dict(to_common(t), bbox_pt=[round(v, 1) for v in b]) for t, d, b in boxes if d == 0 or args.include_nested])
        for tid, golden in goldens.items():
            if golden["source"]["pdf_page"] != page_no:
                continue
            target = golden["source"]["table_bbox_pt"]
            scored = sorted(((iou(b, target), t, d, b) for t, d, b in boxes if d == 0),
                            key=lambda x: x[0], reverse=True)
            candidates[tid] = [{"iou": round(s, 3), "bbox_pt": [round(v, 1) for v in b]} for s, _, _, b in scored[:3]]
            if not scored or scored[0][0] < 0.3:
                continue
            best_iou, best, _, box = scored[0]
            entry = to_common(best)
            entry.update({"id": tid, "page": page_no, "bbox_pt": [round(v, 1) for v in box],
                          "match_iou": round(best_iou, 3), "tables_on_page": sum(1 for _, d, _ in boxes if d == 0)})
            tables[tid] = entry

    hybrid_note = None
    if args.hybrid != "off":
        hybrid_note = ("hybrid 백엔드 'docling-fast'는 opendataloader-pdf-hybrid 서버이며, 내부에서 Docling "
                       "DocumentConverter(TableFormer ACCURATE, 셀 매칭 기본값=켬)를 쓴다. "
                       "서버는 --no-ocr --device cpu로 띄웠다(디지털 원문, 앞선 Docling 실험과 OCR 조건을 맞춤).")
    save_json(out_dir / "tables.json", {
        "parser": "OpenDataLoader PDF",
        "version": "2.5.11",
        "config": {
            "mode": "local" if args.hybrid == "off" else f"hybrid ({args.hybrid})",
            "table_method": args.table_method,
            "keep_line_breaks": True,
            "content_safety_off": args.content_safety_off,
            "hybrid_backend": "docling-fast" if args.hybrid != "off" else None,
            "hybrid_backend_note": hybrid_note,
            "java": java_version,
            "command": cmd,
            "source": "원본 전체 PDF (--pages)" if args.source == "full" else "단쪽 PDF",
        },
        "elapsed_sec": round(elapsed, 2),
        "elapsed_note": f"{len(pages)}쪽을 한 번의 JVM 실행으로 처리한 전체 시간(JVM 기동 포함). hybrid는 서버 모델 로딩 시간 제외.",
        "exit_code": proc.returncode,
        "nested_tables_found": nested,
        "match_candidates": candidates,
        "tables": tables,
    })
    print(f"exit {proc.returncode}, {elapsed:.1f}초")
    for tid in goldens:
        t = tables.get(tid)
        print(f"{tid}: " + (f"IoU={t['match_iou']} 격자 {t['n_rows']}x{t['n_cols']} 셀 {len(t['cells'])}" if t else f"매칭 실패 {candidates.get(tid)}"))


if __name__ == "__main__":
    main()
