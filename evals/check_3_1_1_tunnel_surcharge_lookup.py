"""Original-cell and range-boundary audit for tunnel entrance surcharge lookup."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.lookup import lookup  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/토목/3-1-1.json").read_text(encoding="utf-8"))["draft"]
EXPECTED = [("갱구에서 500m 까지", "-"),
            ("500m∼1,000m 까지", "10"), ("1,000m∼1,500m 까지", "20"),
            ("1,500m∼2,000m 까지", "30"), ("2,000m∼2,500m 까지", "40"),
            ("2,500m∼3,000m 까지", "50"), ("3,000m∼3,500m 까지", "60"),
            ("3,500m∼4,000m 까지", "70"), ("4,000m∼4,500m 까지", "80"),
            ("4,500m∼5,000m 까지", "90"), ("5,000m 이상", "100")]


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'} {label}")
    if not condition:
        raise SystemExit(1)


table = next(item for item in SPEC["tables"] if item["id"] == "p393-t1")
check([(column, table["values"]["할증률(%)"][column]) for column, _ in EXPECTED] == EXPECTED,
      "all 11 printed range cells independently match p.337")
formulas = next(item for item in SPEC["tables"] if item["id"] == "p393-t0")["values"]
check(formulas == {"노임합계": {"구분": "PW", "산정식": "P+PO"},
                    "기본노임": {"구분": "P", "산정식": "P"},
                    "할증노임": {"구분": "PO", "산정식": "P×β"}},
      "PW=P+PO, PO=P×β and base P source formula cells match")

inside = [("100", "-", "갱구에서 500m 까지"), ("501", "10", "500m∼1,000m 까지"),
          ("1001", "20", "1,000m∼1,500m 까지"), ("1501", "30", "1,500m∼2,000m 까지"),
          ("2001", "40", "2,000m∼2,500m 까지"), ("2501", "50", "2,500m∼3,000m 까지"),
          ("3001", "60", "3,000m∼3,500m 까지"), ("3501", "70", "3,500m∼4,000m 까지"),
          ("4001", "80", "4,000m∼4,500m 까지"), ("4501", "90", "4,500m∼5,000m 까지"),
          ("5001", "100", "5,000m 이상")]
for distance, value, column in inside:
    result = lookup(SPEC, {"distance": distance})
    check(result.get("status") == "computed" and result.get("value") == value,
          f"distance {distance}m exact source route -> {value}")
    provenance = result["provenance"]
    check(provenance["table"] == "p393-t1" and provenance["column"] == column,
          f"distance {distance}m citation uses source interval column")

boundaries = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]
statuses = [lookup(SPEC, {"distance": str(distance)}).get("status") for distance in boundaries]
check(statuses == ["blocked"] * len(boundaries),
      "all shared interval boundaries stay blocked under declared source review policy")

out = ROOT / "evals/runtime_validation/3-1-1-tunnel-surcharge-lookup-audit-2026-10-19.json"
out.write_text(json.dumps({"id": SPEC["id"], "source_page": 393, "printed_page": 337,
                           "source_cells_independently_checked": 14,
                           "interval_cells": len(EXPECTED), "formula_cells": 3,
                           "interior_routes_checked": len(inside),
                           "shared_boundaries_blocked": boundaries,
                           "output_scope": "β surcharge percentage lookup only; base P and final PW are not calculated by this spec",
                           "all_rules_fully_verified": False,
                           "spec_sha256": hashlib.sha256((ROOT / "data/drafts/specs/토목/3-1-1.json").read_bytes()).hexdigest()},
                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved {out.relative_to(ROOT)}; source rules outside β lookup remain unverified.")
