"""Development-only check on the consumed P5 sample.

Reads the saved ODL JSON and original one-time report. Never invokes run_odl,
p5_eval.main, or writes a new G7 decision. This sample is no longer a holdout.
"""
import json
import sys

import pymupdf

from common import PDF, RESULTS, ROOT
from p5_eval import score

sys.path.insert(0, str(ROOT / "pipeline"))
import assemble  # noqa: E402
from odl_tables import read_tables  # noqa: E402
from table_guard import guard  # noqa: E402

GT = RESULTS / "holdout/ground_truth.json"
OLD = RESULTS / "p5_holdout/p5_report.json"
RAW = RESULTS / "p5_holdout/raw" / f"{PDF.stem}.json"


def main() -> None:
    gt = json.loads(GT.read_text(encoding="utf-8"))
    old = json.loads(OLD.read_text(encoding="utf-8"))["per_table"]["new"]
    pages = sorted({t["page"] for t in gt["tables"]})
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
        shades = {p: assemble.header_shades(doc[p - 1]) for p in pages}
    tables, _ = guard(PDF, read_tables(RAW, heights, split_rows=True))
    now = score(gt["tables"], tables,
                lambda t: [r["text"] for r in assemble.table_to_records(t, shades[t["page"]], "S", 0)])
    fixed, regressed = [], []
    for tid, current in now.items():
        before = {f["fact"] for f in old[tid]["fails"]}
        after = {f["fact"] for f in current["fails"]}
        fixed.extend((tid, i) for i in sorted(before - after))
        regressed.extend((tid, i) for i in sorted(after - before))
        if before or after:
            print(tid, f"before={len(before)} after={len(after)}",
                  "still", [(f["fact"], f["kind"]) for f in current["fails"]])
    print("development sample only: fixed", len(fixed), fixed)
    print("development sample only: regressed", len(regressed), regressed)
    print("development sample only: current", sum(v["passed"] for v in now.values()),
          "/", sum(v["n_facts"] for v in now.values()))


if __name__ == "__main__":
    main()
