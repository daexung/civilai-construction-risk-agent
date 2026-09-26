"""PaddleOCR-VL(파이프라인 v1.6)로 5개 표를 공통 표 형식으로 저장한다. CPU 실행.

- 입력은 extract_pymupdf.py가 만든 단쪽 PDF(results/pages/pNNN.pdf). PaddleOCR-VL이 PDF를 이미지로 렌더링해 읽는다.
- 표 블록(block_label=table)의 HTML을 rowspan·colspan을 살려 공통 표로 바꾼다.
- 블록 좌표는 렌더링 이미지 픽셀 단위라, 쪽 크기(pt)와 이미지 크기의 비율로 pt로 환산해 정답 bbox와 비교한다.
- 원시 결과(JSON·마크다운), 쪽 전체 글자(오독 점검용), 쪽별 시간·최대 메모리를 남긴다.

실행(PaddleOCR-VL 전용 환경):
  .venv-paddle/Scripts/python.exe experiments/parser_bench/extract_paddle.py --name paddle_vl16 --pages 193
"""
import argparse
import ctypes
import ctypes.wintypes
import html
import importlib.metadata as md
import json
import re
import time
from html.parser import HTMLParser

from common import PAGES_DIR, RESULTS, iou, load_goldens, save_json


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_kernel32 = ctypes.WinDLL("kernel32")
_psapi = ctypes.WinDLL("psapi")
_kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(_PMC), ctypes.wintypes.DWORD]


def memory_mb() -> dict:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    _psapi.GetProcessMemoryInfo(_kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return {"peak_working_set_mb": round(pmc.PeakWorkingSetSize / 2**20),
            "peak_commit_mb": round(pmc.PeakPagefileUsage / 2**20),
            "page_faults": pmc.PageFaultCount}


class TableHTML(HTMLParser):
    """<table> HTML → 행 목록. 각 셀은 (text, rowspan, colspan)."""

    def __init__(self):
        super().__init__()
        self.rows, self.cell, self.depth = [], None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.depth += 1
        elif tag == "tr" and self.depth == 1:
            self.rows.append([])
        elif tag in ("td", "th") and self.depth == 1:
            self.cell = {"text": "", "rs": int(a.get("rowspan") or 1), "cs": int(a.get("colspan") or 1)}
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.depth == 1 and self.cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(self.cell)
            self.cell = None
        elif tag == "table":
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data


def html_to_common(table_html: str) -> dict:
    parser = TableHTML()
    parser.feed(table_html)
    occupied, cells = set(), []
    for r, row in enumerate(parser.rows):
        c = 0
        for cell in row:
            while (r, c) in occupied:
                c += 1
            for dr in range(cell["rs"]):
                for dc in range(cell["cs"]):
                    occupied.add((r + dr, c + dc))
            cells.append({"r0": r, "r1": r + cell["rs"], "c0": c, "c1": c + cell["cs"],
                          "text": html.unescape(cell["text"]).strip()})
            c += cell["cs"]
    n_rows = max((x["r1"] for x in cells), default=0)
    n_cols = max((x["c1"] for x in cells), default=0)
    return {"n_rows": n_rows, "n_cols": n_cols, "cells": cells}


def plain_text(block_content: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", block_content)
    text = re.sub(r"</t[dh]>", " | ", text)
    text = re.sub(r"</tr>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--pages", nargs="*", type=int)
    args = parser.parse_args()

    goldens = load_goldens()
    all_pages = sorted({g["source"]["pdf_page"] for g in goldens.values()})
    pages = args.pages or all_pages
    out_dir = RESULTS / args.name
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "tables.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"tables": {}, "page_sec": {}}

    from paddleocr import PaddleOCRVL

    t0 = time.perf_counter()
    pipeline = PaddleOCRVL(pipeline_version="v1.6", device="cpu",
                           use_doc_orientation_classify=False, use_doc_unwarping=False)
    init_sec = time.perf_counter() - t0
    print(f"초기화 {init_sec:.1f}초 {memory_mb()}", flush=True)

    # 쪽 크기(pt)는 기존 .venv에서 미리 뽑아 둔 파일을 읽는다(이 환경에는 PyMuPDF가 없다)
    page_sizes = json.loads((PAGES_DIR / "sizes.json").read_text(encoding="utf-8"))
    for page_no in pages:
        pdf = PAGES_DIR / f"p{page_no}.pdf"
        t1 = time.perf_counter()
        results = list(pipeline.predict(str(pdf)))
        page_sec = time.perf_counter() - t1
        res = results[0]
        res.save_to_json(save_path=str(raw_dir / f"p{page_no}"))
        res.save_to_markdown(save_path=str(raw_dir / f"p{page_no}"))
        data = res.json.get("res", res.json)

        blocks = data.get("parsing_res_list", [])
        img_w = data.get("width")
        page_w = page_sizes[str(page_no)][0]
        scale = page_w / img_w if img_w else 1.0

        (raw_dir / f"p{page_no}_page_text.txt").write_text(
            "\n".join(plain_text(b.get("block_content", "")) for b in blocks), encoding="utf-8")

        found = []
        for b in blocks:
            if b.get("block_label") != "table":
                continue
            box = [v * scale for v in b["block_bbox"]]
            found.append((b, box))
        for tid, golden in goldens.items():
            if golden["source"]["pdf_page"] != page_no:
                continue
            target = golden["source"]["table_bbox_pt"]
            scored = sorted(((iou(box, target), b, box) for b, box in found), key=lambda x: x[0], reverse=True)
            meta.setdefault("match_candidates", {})[tid] = [
                {"iou": round(s, 3), "bbox_pt": [round(v, 1) for v in box]} for s, _, box in scored[:3]]
            if not scored or scored[0][0] < 0.3:
                meta["tables"].pop(tid, None)
                continue
            best_iou, best, box = scored[0]
            entry = html_to_common(best["block_content"])
            entry.update({"id": tid, "page": page_no, "bbox_pt": [round(v, 1) for v in box],
                          "match_iou": round(best_iou, 3), "tables_on_page": len(found)})
            meta["tables"][tid] = entry

        meta["page_sec"][str(page_no)] = round(page_sec, 1)
        meta.setdefault("memory_after_page", {})[str(page_no)] = memory_mb()
        meta.update({
            "parser": "PaddleOCR-VL",
            "version": md.version("paddleocr"),
            "versions": {p: md.version(p) for p in ("paddleocr", "paddlex", "paddlepaddle")},
            "config": {"pipeline_version": "v1.6", "device": "cpu",
                       "use_doc_orientation_classify": False, "use_doc_unwarping": False,
                       "input": "단쪽 PDF (PaddleOCR-VL 내부 렌더링)", "vl_rec_backend": "기본값(Paddle 네이티브)"},
            "image_to_pt_scale": {str(page_no): scale} | meta.get("image_to_pt_scale", {}),
            "init_sec_last_run": round(init_sec, 1),
        })
        meta["elapsed_sec"] = round(sum(meta["page_sec"].values()), 1)
        save_json(meta_path, meta)
        print(f"p{page_no}: {page_sec:.1f}초, 표 블록 {len(found)}개, {memory_mb()}", flush=True)


if __name__ == "__main__":
    main()
