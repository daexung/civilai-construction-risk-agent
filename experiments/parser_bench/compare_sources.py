"""입력 차이 점검: 원본 전체 PDF와 단쪽 PDF에서 뽑은 공통 표가 같은지 비교한다.

쌍: (원본, 단쪽). PyMuPDF는 원래 원본 PDF를 써서 'pymupdf'가 원본, 'pymupdf__pages'가 단쪽이다.
다른 파서는 기존 결과가 단쪽이고 '__fullpdf'가 원본이다.

실행(저장소 루트, 기존 .venv): python experiments/parser_bench/compare_sources.py
"""
import json

from common import RESULTS, save_json

PAIRS = [
    ("pymupdf", "pymupdf__pages"),
    ("docling_accurate__fullpdf", "docling_accurate"),
    ("docling_accurate_nomatch__fullpdf", "docling_accurate_nomatch"),
    ("odl_local__fullpdf", "odl_local"),
    ("odl_local_cluster__fullpdf", "odl_local_cluster"),
    ("odl_hybrid_auto__fullpdf", "odl_hybrid_auto"),
    ("odl_hybrid_full__fullpdf", "odl_hybrid_full"),
]


def cell_key(c):
    return (c["r0"], c["r1"], c["c0"], c["c1"], c["text"])


def compare(full: dict, pages: dict) -> dict:
    out = {}
    for tid in sorted(set(full) | set(pages)):
        a, b = full.get(tid), pages.get(tid)
        if not a or not b:
            out[tid] = {"same": False, "note": f"한쪽에만 있음 (원본 {'있음' if a else '없음'}, 단쪽 {'있음' if b else '없음'})"}
            continue
        ca, cb = {cell_key(c) for c in a["cells"]}, {cell_key(c) for c in b["cells"]}
        bbox_delta = max(abs(x - y) for x, y in zip(a["bbox_pt"], b["bbox_pt"]))
        same = (a["n_rows"], a["n_cols"]) == (b["n_rows"], b["n_cols"]) and ca == cb
        out[tid] = {
            "same": same,
            "shape": [f"{a['n_rows']}x{a['n_cols']}", f"{b['n_rows']}x{b['n_cols']}"],
            "only_in_full": sorted(ca - cb)[:5],
            "only_in_pages": sorted(cb - ca)[:5],
            "bbox_max_delta_pt": round(bbox_delta, 2),
        }
    return out


def main() -> None:
    report = {}
    for full_run, pages_run in PAIRS:
        fa, fb = RESULTS / full_run / "tables.json", RESULTS / pages_run / "tables.json"
        if not fa.exists() or not fb.exists():
            report[f"{full_run} vs {pages_run}"] = "결과 없음"
            continue
        a = json.loads(fa.read_text(encoding="utf-8"))["tables"]
        b = json.loads(fb.read_text(encoding="utf-8"))["tables"]
        res = compare(a, b)
        report[f"{full_run} vs {pages_run}"] = res
        diff = [tid for tid, r in res.items() if not r["same"]]
        print(f"{full_run:36s} vs {pages_run:26s}: " + ("5표 모두 동일" if not diff else f"다름 {diff}"))
        for tid in diff:
            print(f"     {tid}: {res[tid]}")
    save_json(RESULTS / "source_comparison.json", report)


if __name__ == "__main__":
    main()
