"""P5 보류 표본 채점 (G7). 정답(results/holdout/ground_truth.json)을 커밋한 뒤 **한 번만** 실행한다.

  새 경로  = ODL + 칸 안 행 분리(P2) + 선 기반 누락 감시·대체 추출(P3) + 새 조립(P4)
  현행 경로 = 운영 parse.py와 같은 PyMuPDF find_tables().extract() + parse.clean_table·table_to_records
채점 규칙은 SCORING_RULES.md 3절(blind_eval.py 함수 그대로).
G7: 사실 95% 이상, 수량 누락 0, 잘못 붙음 0. 실패는 모두 원인별로 분류한다.
오탐(정답에 없는 표)은 무작위 쪽에서만 센다.

실행: python experiments/parser_bench/p5_eval.py
원시 출력(results/p5_holdout/)은 커밋하지 않는다. 결과 요약만 따로 기록한다.
"""
import json
import sys
import time

import pymupdf

from blind_eval import area, exclusive_ok, fact_ok, inter, other_row_tokens, row_token_in, value_anywhere
from common import PDF, RESULTS, ROOT, save_json
from p1_reproduce import candidates

sys.path.insert(0, str(ROOT / "pipeline"))
import assemble  # noqa: E402
import parse  # noqa: E402
from odl_tables import read_tables, run_odl  # noqa: E402
from table_guard import guard  # noqa: E402

GT = RESULTS / "holdout" / "ground_truth.json"
RUN_DIR = RESULTS / "p5_holdout"


def classify(fact, cands, recs) -> str:
    cell_texts = [c["text"] or "" for t in cands for c in t["cells"]]
    if not cands:
        return "표 미탐지"
    if not all(value_anywhere(v, cell_texts) for _, v in fact[1]):
        return "수량 누락"
    if not all(value_anywhere(tok, cell_texts) for tok in fact[0]):
        return "행 라벨 누락"
    if not recs:
        return "레코드 없음(조립)"
    return "잘못 붙음"


def score(gt_tables, tables, builder) -> dict:
    out = {}
    for t in gt_tables:
        cands = candidates(t, tables.get(t["page"], []))
        recs = [r for c in cands for r in builder(c)]
        facts = t["facts"]
        fails = []
        for i, f in enumerate(facts):
            if any(fact_ok(f, r) and exclusive_ok(f, r.split(" | "), other_row_tokens(f, facts)) for r in recs):
                continue
            near = [r for r in recs if f[0] and all(row_token_in(tok, r) for tok in f[0])][:2]
            fails.append({"fact": i, "row": f[0], "kind": classify(f, cands, recs), "records_with_row_label": near})
        out[t["id"]] = {"n_facts": len(facts), "passed": len(facts) - len(fails), "found": bool(cands),
                        "shapes": [f"{c['n_rows']}x{c['n_cols']}" for c in cands],
                        "extractors": [c.get("extractor", "odl") for c in cands], "fails": fails}
    return out


def production_tables(pages) -> dict:
    """운영 parse.py와 같은 추출: 쪽마다 find_tables().extract() 격자와 bbox."""
    out = {}
    with pymupdf.open(PDF) as doc:
        for p in pages:
            out[p] = [{"page": p, "bbox_pt": list(t.bbox), "n_rows": len(t.extract()), "n_cols": t.col_count,
                       "grid": t.extract(),
                       "cells": [{"r0": r, "r1": r + 1, "c0": c, "c1": c + 1, "text": v or ""}
                                 for r, row in enumerate(t.extract()) for c, v in enumerate(row)]}
                      for t in doc[p - 1].find_tables().tables]
    return out


def main() -> None:
    gt = json.loads(GT.read_text(encoding="utf-8"))
    random_pages = gt["random_pages_used"]
    pages = sorted(set(random_pages) | set(gt["targeted_pages"]))

    started = time.perf_counter()
    run = run_odl(PDF, pages, RUN_DIR / "raw")
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
        shades = {p: assemble.header_shades(doc[p - 1]) for p in pages}
    new_tables, guard_log = guard(PDF, read_tables(run["json_path"], heights, split_rows=True))
    new_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    prod_tables = production_tables(pages)
    prod_elapsed = time.perf_counter() - started

    new = score(gt["tables"], new_tables,
                lambda t: [r["text"] for r in assemble.table_to_records(t, shades[t["page"]], "S", 0)])
    prod = score(gt["tables"], prod_tables,
                 lambda t: [r["text"] for r in parse.table_to_records(parse.clean_table(t["grid"]), "S", 0)])

    def fp(tables):
        rows = []
        for p in random_pages:
            gts = [t for t in gt["tables"] if t["page"] == p]
            for t in tables[p]:
                if not any(inter(t["bbox_pt"], g["bbox_pt"]) / area(g["bbox_pt"]) >= 0.3
                           or inter(t["bbox_pt"], g["bbox_pt"]) / max(area(t["bbox_pt"]), 1) >= 0.5 for g in gts):
                    rows.append({"page": p, "bbox_pt": t["bbox_pt"], "shape": f"{t['n_rows']}x{t['n_cols']}"})
        return rows

    def totals(res, kind=None):
        sel = [(tid, v) for tid, v in res.items()
               if kind is None or next(t["kind"] for t in gt["tables"] if t["id"] == tid).startswith(kind)]
        n = sum(v["n_facts"] for _, v in sel)
        ok = sum(v["passed"] for _, v in sel)
        kinds = {}
        for _, v in sel:
            for f in v["fails"]:
                kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        return {"passed": ok, "facts": n, "rate": round(ok / n, 3) if n else None, "fail_kinds": kinds,
                "tables_found": sum(v["found"] for _, v in sel), "tables": len(sel)}

    regressions = [{"table": tid, "fact": f["fact"], "row": f["row"], "kind": f["kind"]}
                   for tid, v in new.items() for f in v["fails"]
                   if f["fact"] not in [g["fact"] for g in prod[tid]["fails"]]]
    report = {
        "pages": pages, "odl_elapsed_sec": run["elapsed_sec"], "new_path_elapsed_sec": round(new_elapsed, 2),
        "production_elapsed_sec": round(prod_elapsed, 2),
        "new": {"all": totals(new), "random": totals(new, "random"), "targeted": totals(new, "targeted")},
        "production": {"all": totals(prod), "random": totals(prod, "random"), "targeted": totals(prod, "targeted")},
        "new_fails_where_production_passes": regressions,
        "false_positives": {"new": fp(new_tables), "production": fp(prod_tables)},
        "guard_log": [e for e in guard_log if e["status"] != "covered"],
        "per_table": {"new": new, "production": prod},
    }
    rate = report["new"]["all"]["rate"]
    kinds = report["new"]["all"]["fail_kinds"]
    report["G7"] = {"rate_ge_95": bool(rate is not None and rate >= 0.95),
                    "no_missing_quantity": kinds.get("수량 누락", 0) == 0,
                    "no_misattached": kinds.get("잘못 붙음", 0) == 0}
    save_json(RUN_DIR / "p5_report.json", report)

    print(f"ODL {run['elapsed_sec']}초 / 새 경로 전체 {new_elapsed:.1f}초 / 현행 경로 {prod_elapsed:.1f}초 ({len(pages)}쪽)")
    for path in ("new", "production"):
        for part in ("all", "random", "targeted"):
            print(f"{path:10} {part:8}", report[path][part])
    print("G7:", report["G7"])
    print("현행 경로가 맞히는데 새 경로가 틀린 사실:", regressions)
    print("오탐(무작위 쪽):", report["false_positives"])
    print("감시 경고:", report["guard_log"])
    for tid, v in new.items():
        pv = prod[tid]
        print(f"  {tid:9} 새 {v['passed']:2}/{v['n_facts']:2} {v['shapes']}{v['extractors']} | 현행 {pv['passed']:2}/{pv['n_facts']:2}"
              + ("" if not v["fails"] else f" | 실패 {[(f['fact'], f['kind']) for f in v['fails']]}"))


if __name__ == "__main__":
    main()
