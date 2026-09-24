"""별도 검증 세트: 기존 5표 밖의 소수 쪽에서 PyMuPDF와 ODL local을 비교한다.

선정 규칙(파서를 쓰지 않고, 결과를 보기 전에 고정):
  1. 1~982쪽 중 파일럿 장(185~214쪽)을 뺀 쪽을 10개 구간으로 나눈다.
  2. 구간마다 고정 시드로 1쪽씩 뽑는다. 어느 파서의 표 탐지 결과도 선정에 쓰지 않는다.
  3. 뽑힌 쪽에서 두 파서 중 하나라도 찾은 표를 전부 비교한다.

단계:
  python experiments/parser_bench/validate_pages.py select      → results/validation/selection.json
  (두 파서로 선정된 쪽만 추출: extract_pymupdf.py / extract_odl.py --pages ...)
  python experiments/parser_bench/validate_pages.py compare     → results/validation/comparison.json

비교 항목:
  - 표 매칭: 같은 쪽에서 bbox IoU 0.5 이상. 짝이 없으면 한쪽만 찾은 표
  - 원시 구조: 행·열 수, 셀 위치·병합 범위, 셀 글자(엄격 / 공백·괄호 글리프 무시)
  - 최종 레코드: 운영 조립 로직(clean_table·table_to_records)을 두 어댑터로 돌려 비교
"""
import json
import random
import sys

from common import RESULTS, ROOT, grid_from_cells, iou, save_json, strip_brackets, ws

sys.path.insert(0, str(ROOT / "pipeline"))
from parse import clean_table, table_to_records  # noqa: E402

SEED = 20260924
N_BINS = 10
TOTAL_PAGES = 982
EXCLUDE = range(185, 215)
OUT = RESULTS / "validation"
PM_RUN, ODL_RUN = "validation_pymupdf", "validation_odl_local"


def select() -> list[int]:
    allowed = [p for p in range(1, TOTAL_PAGES + 1) if p not in EXCLUDE]
    size = len(allowed) / N_BINS
    rng = random.Random(SEED)
    pages = [rng.choice(allowed[int(i * size): int((i + 1) * size)]) for i in range(N_BINS)]
    save_json(OUT / "selection.json", {
        "rule": f"1~{TOTAL_PAGES}쪽에서 185~214쪽을 빼고 {N_BINS}구간으로 나눠 구간마다 1쪽 (random.Random({SEED}))",
        "pages": pages,
    })
    return pages


def cell_set(table, strict: bool):
    norm = (lambda t: t) if strict else (lambda t: ws(strip_brackets(t)))
    return {(c["r0"], c["r1"], c["c0"], c["c1"], norm(c["text"])) for c in table["cells"]}


def records(table, fill: bool) -> list[str]:
    try:
        recs = table_to_records(clean_table(grid_from_cells(table, fill_spans=fill)), "S", 0)
        return [r["text"] for r in recs]
    except Exception as exc:
        return [f"조립 오류: {type(exc).__name__}: {exc}"]


def compare_pair(a, b) -> dict:
    same_shape = (a["n_rows"], a["n_cols"]) == (b["n_rows"], b["n_cols"])
    loose_a, loose_b = cell_set(a, False), cell_set(b, False)
    out = {
        "shape": [f"{a['n_rows']}x{a['n_cols']}", f"{b['n_rows']}x{b['n_cols']}"],
        "same_strict": same_shape and cell_set(a, True) == cell_set(b, True),
        "same_loose": same_shape and loose_a == loose_b,
        "only_pymupdf_cells": sorted(loose_a - loose_b)[:6],
        "only_odl_cells": sorted(loose_b - loose_a)[:6],
    }
    for fill in (False, True):
        ra, rb = records(a, fill), records(b, fill)
        na = sorted(ws(strip_brackets(r)) for r in ra)
        nb = sorted(ws(strip_brackets(r)) for r in rb)
        out["records_" + ("spanfill" if fill else "extract")] = {
            "count": [len(ra), len(rb)],
            "same_strict": sorted(ra) == sorted(rb),
            "same_loose": na == nb,
            "only_pymupdf": [r for r in ra if ws(strip_brackets(r)) not in nb][:4],
            "only_odl": [r for r in rb if ws(strip_brackets(r)) not in na][:4],
        }
    return out


def load_page_tables(run, page_no):
    path = RESULTS / run / "raw" / f"p{page_no}_all_tables.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def compare() -> None:
    pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    report = {"pages": {}}
    totals = {"pages": len(pages), "pages_with_tables": 0, "pairs": 0, "same_strict": 0, "same_loose": 0,
              "records_extract_same_loose": 0, "records_spanfill_same_loose": 0,
              "records_spanfill_same_strict": 0, "only_pymupdf_tables": 0, "only_odl_tables": 0}
    for page_no in pages:
        a_list, b_list = load_page_tables(PM_RUN, page_no), load_page_tables(ODL_RUN, page_no)
        if a_list or b_list:
            totals["pages_with_tables"] += 1
        used, page_out = set(), {"pymupdf_tables": len(a_list), "odl_tables": len(b_list),
                                 "pairs": [], "only_pymupdf": [], "only_odl": []}
        for i, a in enumerate(a_list):
            scored = sorted(((iou(a["bbox_pt"], b["bbox_pt"]), j) for j, b in enumerate(b_list) if j not in used),
                            reverse=True)
            if scored and scored[0][0] >= 0.5:
                j = scored[0][1]
                used.add(j)
                res = compare_pair(a, b_list[j])
                res.update({"pymupdf_index": i, "odl_index": j, "iou": round(scored[0][0], 3),
                            "bbox_pt": a["bbox_pt"]})
                page_out["pairs"].append(res)
                totals["pairs"] += 1
                totals["same_strict"] += res["same_strict"]
                totals["same_loose"] += res["same_loose"]
                totals["records_extract_same_loose"] += res["records_extract"]["same_loose"]
                totals["records_spanfill_same_loose"] += res["records_spanfill"]["same_loose"]
                totals["records_spanfill_same_strict"] += res["records_spanfill"]["same_strict"]
            else:
                page_out["only_pymupdf"].append({"index": i, "bbox_pt": a["bbox_pt"], "shape": f"{a['n_rows']}x{a['n_cols']}"})
                totals["only_pymupdf_tables"] += 1
        for j, b in enumerate(b_list):
            if j not in used:
                page_out["only_odl"].append({"index": j, "bbox_pt": b["bbox_pt"], "shape": f"{b['n_rows']}x{b['n_cols']}"})
                totals["only_odl_tables"] += 1
        report["pages"][page_no] = page_out
    report["totals"] = totals
    save_json(OUT / "comparison.json", report)

    print(json.dumps(totals, ensure_ascii=False))
    for page_no, p in report["pages"].items():
        print(f"p{page_no}: PyMuPDF 표 {p['pymupdf_tables']}, ODL 표 {p['odl_tables']}")
        for pair in p["pairs"]:
            flags = []
            if not pair["same_loose"]:
                flags.append("구조·글자 다름")
            elif not pair["same_strict"]:
                flags.append("표기만 다름")
            if not pair["records_spanfill"]["same_loose"]:
                flags.append("레코드 다름")
            elif not pair["records_spanfill"]["same_strict"]:
                flags.append("레코드 표기만 다름")
            print(f"   표{pair['pymupdf_index']} {pair['shape']} " + (", ".join(flags) if flags else "동일"))
        for side in ("only_pymupdf", "only_odl"):
            for t in p[side]:
                print(f"   {side}: {t}")


if __name__ == "__main__":
    {"select": lambda: print(select()), "compare": compare}[sys.argv[1]]()
