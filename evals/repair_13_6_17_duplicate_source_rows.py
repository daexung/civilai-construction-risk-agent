from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "data/drafts/specs/기계설비/13-6-17.json"
document = json.loads(path.read_text(encoding="utf-8"))
spec = document["draft"]
table = next(table for table in spec["tables"] if table["id"] == "p878-t0")
values = table["values"]

# The source has repeated process names. Preserve every row as its own cell.
renames = {
    "교정 · 플랜트제관공": [
        ("교정(1) · 플랜트제관공", "0.5"),
        ("교정(2) · 플랜트제관공", "0.75"),
    ],
    "용접 · 플랜트용접공": [
        ("용접(1) · 플랜트용접공", "1.0"),
        ("용접(2) · 플랜트용접공", "6.8"),
    ],
    "절단 · 산소절단공": [
        ("절단(1) · 산소절단공", "0.14"),
        ("절단(2) · 산소절단공", "0.08"),
    ],
}
for old, entries in renames.items():
    values.pop(old, None)
    for row, amount in entries:
        values[row] = {"수량": amount}

# Update every execution binding and its source citation together, selecting
# the exact original cell by the independently transcribed amount.
expected_by_old = {
    "교정 · 플랜트제관공": {"0.5": "교정(1) · 플랜트제관공", "0.75": "교정(2) · 플랜트제관공"},
    "용접 · 플랜트용접공": {"1.0": "용접(1) · 플랜트용접공", "6.8": "용접(2) · 플랜트용접공"},
    "절단 · 산소절단공": {"0.14": "절단(1) · 산소절단공", "0.08": "절단(2) · 산소절단공"},
}
params = spec["quantity_model"]["params"]
bindings = [params["unit_rate_table"], *params.get("additional_unit_rates", [])]
for binding in bindings:
    cite = binding.get("citation_overrides", {}).get("작업품", {}).get("page_source") or binding.get("cite", {}).get("page_source")
    if not cite:
        continue
    old = cite.get("row")
    if old not in expected_by_old:
        continue
    amount = cite.get("value", "").split()[0]
    if amount not in expected_by_old[old]:
        raise ValueError(f"unexpected duplicated source cell amount: {old} / {amount}")
    new = expected_by_old[old][amount]
    cite["row"] = new
    if binding.get("row_by_trade"):
        for trade in binding["row_by_trade"]:
            binding["row_by_trade"][trade] = new

path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("repaired duplicate exact-row keys in p878-t0 and runtime citations")
