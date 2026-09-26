"""Check P5 fixes against cached pre-P5 development data without ODL reruns."""
import json

import pymupdf

import p4_eval
from common import PDF, RESULTS
from odl_tables import read_tables
from table_guard import guard

P4 = RESULTS / "p4_assemble"


def main() -> None:
    previous = json.loads((P4 / "p4_report.json").read_text(encoding="utf-8"))
    pages = previous["pages"]
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
        p4_eval.SHADES.update({p: p4_eval.assemble.header_shades(doc[p - 1]) for p in pages})
    tables, _ = guard(PDF, read_tables(P4 / "raw" / f"{PDF.stem}.json", heights, split_rows=True))

    gt = json.loads((RESULTS / "blind20/ground_truth.json").read_text(encoding="utf-8"))
    base = json.loads((RESULTS / "blind20/baseline.json").read_text(encoding="utf-8"))
    now = {t["id"]: p4_eval.failed(t, tables, p4_eval.new_records) for t in gt["tables"]}
    regressions = [(tid, i) for tid, fails in now.items()
                   for i in sorted(set(fails) - set(previous["blind20_still_failing"].get(tid, [])))]
    production_regressions = [(tid, i) for tid, fails in now.items()
                              for i in sorted(set(fails) - set(base["tables"][tid]["pymupdf.extract.failed"]))]
    print("blind20", sum(len(t["facts"]) - len(now[t["id"]]) for t in gt["tables"]),
          "/", sum(len(t["facts"]) for t in gt["tables"]))
    print("regressions_vs_previous", regressions)
    print("regressions_vs_production", production_regressions)
    print("still_failing", {k: v for k, v in now.items() if v})

    failures = json.loads((RESULTS / "validation/ground_truth_failures.json").read_text(encoding="utf-8"))
    print("development_failures", {t["id"]: f"{len(t['facts']) - len(p4_eval.failed(t, tables, p4_eval.new_records))}/{len(t['facts'])}"
                                   for t in failures["tables"]})
    goldens = p4_eval.golden5(tables)
    for kind, summary in goldens["summary"].items():
        print("golden5", kind, "own", summary["expected_own"], "shared", summary["expected_shared"],
              "format_failures", summary["old_golden_failures_by_type"],
              "interpretation", summary["interpretation_checks"], "estimate", summary["estimate"])
    print("golden_parse_ODL", p4_eval.check_23_new(tables).splitlines()[0])
    if regressions or production_regressions:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
