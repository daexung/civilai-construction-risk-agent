"""P4 평가: 새 조립(pipeline/assemble.py)을 현행 조립과 비교한다.

추출은 두 경로 모두 같다: ODL + 칸 안 행 분리(P2) + 선 기반 누락 감시·대체 추출(P3).
  수정 전 = 현행 조립(parse.clean_table·table_to_records, 병합 칸 채움 격자)
  수정 후 = 새 조립(assemble.table_to_records)
확인:
  1. 문제별 진단: 머리글 판정, 396·500쪽, 835쪽, T3 도장공·괄호
  2. blind20 사실(수정 전 대비 퇴행, 현행 운영 경로 PyMuPDF extract 대비 퇴행 G6)
  3. 396·500쪽 사실
  4. 5표 정답(score.py의 build_records만 바꿔 끼움), 노무량
  5. 기존 23건(check_parse의 parse_pages만 바꿔 끼움. parse.py와 기본 실행 경로는 그대로)

실행: python experiments/parser_bench/p4_eval.py
원시 출력(results/p4_assemble/)은 커밋하지 않는다.
"""
import contextlib
import io
import json
import sys

import pymupdf

import score
from blind_eval import OUT, exclusive_ok, fact_ok, other_row_tokens
from common import PDF, RESULTS, ROOT, iou, load_goldens, save_json
from p1_reproduce import candidates

sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "evals"))
import assemble  # noqa: E402
import check_parse  # noqa: E402
import parse  # noqa: E402
from odl_tables import read_tables, run_odl, to_grid  # noqa: E402
from table_guard import guard  # noqa: E402

RUN_DIR = RESULTS / "p4_assemble"
FAILURES = RESULTS / "validation" / "ground_truth_failures.json"
SHADES: dict[int, list] = {}


def old_records(table, section="S", page=0) -> list[str]:
    return [r["text"] for r in parse.table_to_records(parse.clean_table(to_grid(table, fill_spans=True)), section, page)]


def new_records(table, section="S", page=0) -> list[str]:
    return [r["text"] for r in assemble.table_to_records(table, SHADES[table["page"]], section, page)]


def failed(gt_table, tables, builder) -> list[int]:
    cands = candidates(gt_table, tables.get(gt_table["page"], []))
    recs = [r for t in cands for r in builder(t)]
    facts = gt_table["facts"]
    return [i for i, f in enumerate(facts)
            if not any(fact_ok(f, r) and exclusive_ok(f, r.split(" | "), other_row_tokens(f, facts)) for r in recs)]


def header_counts(table) -> dict:
    grid = to_grid(table, fill_spans=True)
    raw, _ = assemble.to_grid(table)
    new, basis = assemble.count_header(table, [[assemble.clean(c) for c in row] for row in raw], SHADES[table["page"]])
    return {"old": parse.count_header_rows(parse.clean_table(grid)), "new": new, "basis": basis, "n_rows": table["n_rows"]}


def golden5(tables) -> dict:
    goldens = load_goldens()
    matched = {}
    for tid, g in goldens.items():
        page, target = g["source"]["pdf_page"], g["source"]["table_bbox_pt"]
        scored = sorted(((iou(t["bbox_pt"], target), t) for t in tables[page] if not t["nested"]),
                        key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 0.3:
            matched[tid] = scored[0][1]
    original = score.build_records
    out = {"old": score.score_layer_b(matched, goldens, "spanfill")}

    def build_new(table, golden, adapter):
        return assemble.table_to_records(table, SHADES[table["page"]], golden["source"]["section"],
                                         golden["source"]["pdf_page"]), None

    score.build_records = build_new
    try:
        out["new"] = score.score_layer_b(matched, goldens, "spanfill")
    finally:
        score.build_records = original
    return {"summary": score.summarize({}, out)["B"], "T3_records": {k: v["per_table"]["T3"]["records"] for k, v in out.items()}}


def check_23_new(tables) -> str:
    original = check_parse.parse_pages
    check_parse.parse_pages = lambda pdf, s, e: assemble.parse_pages(pdf, s, e, tables)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            check_parse.main()
    finally:
        check_parse.parse_pages = original
    return buf.getvalue().strip()


def check_23_old(tables) -> str:
    original = parse.read_tables
    parse.read_tables = lambda page: [(tuple(t["bbox_pt"]), to_grid(t, fill_spans=True)) for t in tables[page.number + 1]]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            check_parse.main()
    finally:
        parse.read_tables = original
    return buf.getvalue().strip()


def main() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    base = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    failures = json.loads(FAILURES.read_text(encoding="utf-8"))
    blind_pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    val_pages = json.loads((RESULTS / "validation" / "selection.json").read_text(encoding="utf-8"))["pages"]
    golden = json.loads(check_parse.GOLDEN.read_text(encoding="utf-8"))
    case_pages = sorted({c["page"] for c in golden["cases"]})
    pages = sorted(set(blind_pages) | set(val_pages) | set(range(case_pages[0], case_pages[-1] + 1))
                   | {g["source"]["pdf_page"] for g in load_goldens().values()})

    run = run_odl(PDF, pages, RUN_DIR / "raw")
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
        SHADES.update({p: assemble.header_shades(doc[p - 1]) for p in pages})
    tables, _ = guard(PDF, read_tables(run["json_path"], heights, split_rows=True))

    report = {"pages": pages, "odl_elapsed_sec": run["elapsed_sec"]}
    facts = {t["id"]: t["facts"] for t in gt["tables"]}
    res = {name: {t["id"]: failed(t, tables, b) for t in gt["tables"]} for name, b in (("old", old_records), ("new", new_records))}
    report["blind20"] = {name: sum(len(facts[k]) - len(v) for k, v in r.items()) for name, r in res.items()}
    report["blind20_regressions"] = [{"table": k, "fact": i, "row": facts[k][i][0]} for k in facts
                                     for i in sorted(set(res["new"][k]) - set(res["old"][k]))]
    report["blind20_gains"] = {k: sorted(set(res["old"][k]) - set(res["new"][k])) for k in facts
                               if set(res["old"][k]) - set(res["new"][k])}
    report["blind20_still_failing"] = {k: v for k, v in res["new"].items() if v}
    report["g6_vs_production"] = [{"table": k, "fact": i} for k in facts
                                  for i in sorted(set(res["new"][k]) - set(base["tables"][k]["pymupdf.extract.failed"]))]

    fres = {name: {t["id"]: failed(t, tables, b) for t in failures["tables"]} for name, b in (("old", old_records), ("new", new_records))}
    report["failures"] = {name: {k: f"{len(t['facts']) - len(r[k])}/{len(t['facts'])}"
                                 for t in failures["tables"] for k in [t["id"]]} for name, r in fres.items()}

    # 문제별 진단: 원시 값과 레코드
    diag_tables = {"p255_t1": 255, "p488_t1": 488, "p155_t2": 155, "p440_t1": 440, "p594_t1": 594, "p835_t1": 835,
                   "p396_t1": 396, "p500_t1": 500}
    all_gt = {t["id"]: t for t in gt["tables"] + failures["tables"]}
    report["diagnostics"] = {}
    for tid in diag_tables:
        t = all_gt[tid]
        cands = candidates(t, tables[t["page"]])
        report["diagnostics"][tid] = {
            "header": [header_counts(c) for c in cands],
            "old_records": [r for c in cands for r in old_records(c)][:3],
            "new_records": [r for c in cands for r in new_records(c)][:3],
            "old_failed": (res["old"].get(tid) if tid in res["old"] else fres["old"][tid]),
            "new_failed": (res["new"].get(tid) if tid in res["new"] else fres["new"][tid])}

    # 사실 정답이 없는 표까지 포함해 레코드 수가 달라진 표(병합·분리 변화) 목록. 사람이 원문과 대조한다
    report["record_count_changes"] = []
    for p in pages:
        for i, t in enumerate(tables[p]):
            o, n = old_records(t), new_records(t)
            if len(o) != len(n):
                report["record_count_changes"].append({"page": p, "index": i, "shape": f"{t['n_rows']}x{t['n_cols']}",
                                                       "old": len(o), "new": len(n), "new_sample": n[:2]})

    report["golden5"] = golden5(tables)
    report["check_parse"] = {"old": check_23_old(tables), "new": check_23_new(tables)}
    save_json(RUN_DIR / "p4_report.json", report)

    print(f"ODL {run['elapsed_sec']}초, {len(pages)}쪽")
    print("blind20 최종 레코드:", report["blind20"])
    print("퇴행(수정 전 대비):", report["blind20_regressions"])
    print("G6(현행 운영 경로 대비):", report["g6_vs_production"])
    print("개선:", report["blind20_gains"])
    print("남은 실패:", report["blind20_still_failing"])
    print("396·500:", report["failures"])
    print("레코드 수가 달라진 표:")
    for c in report["record_count_changes"]:
        print(f"   p{c['page']}#{c['index']} {c['shape']} {c['old']}→{c['new']} {[s[:90] for s in c['new_sample']]}")
    for tid, d in report["diagnostics"].items():
        print(f"== {tid} 머리글 {d['header']} 실패 {d['old_failed']} → {d['new_failed']}")
        print("   전:", d["old_records"][:2])
        print("   후:", d["new_records"][:2])
    for k, v in report["golden5"]["summary"].items():
        print("5표", k, "기대", v["expected_own"], "공유", v["expected_shared"], "형식", v["old_golden_failures_by_type"],
              "해석", v["interpretation_checks"], "노무량", v["estimate"], v["estimate_detail"])
    print("T3 레코드(후):", report["golden5"]["T3_records"]["new"][:4])
    for k, v in report["check_parse"].items():
        print("23건", k, v.splitlines()[0], "|", " / ".join(l for l in v.splitlines() if l.startswith("[실패]")))


if __name__ == "__main__":
    main()
