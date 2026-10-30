"""Restore the eight protection-column dashes visible in original PDF p.735."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = next(p for p in (ROOT / "data/drafts/specs").rglob("*.json")
            if (lambda d: d.get("division") == "기계설비" and d.get("section_no") == "6-1-1")
            (json.loads(p.read_text(encoding="utf8"))["draft"]))
spec = json.loads(PATH.read_text(encoding="utf-8"))
draft = spec["draft"]
table = next(t for t in draft["tables"] if t["id"] == "p735-t0")
sizes = ("65~80", "100~125", "150~200", "250~300")
for size in sizes:
    table["values"][size]["보호통 배관공(인)"] = "-"
    table["values"][size]["보호통 보통인부(인)"] = "-"
params = draft["quantity_model"]["params"]
exclusions = params.setdefault("excluded_resources", [])
for size in sizes:
    for trade in ("배관공", "보통인부"):
        rule = next((x for x in exclusions if x.get("trade") == trade
                     and x.get("when") == {"meter_size": size, "install_item": "보호통"}), None)
        if rule is None:
            rule = {"trade": trade, "when": {"meter_size": size, "install_item": "보호통"},
                    "source": "PDF printed p.679 (physical p.735), protection columns are explicit dashes"}
            exclusions.append(rule)
        rule["source"] = "PDF printed p.679 (physical p.735), protection columns are explicit dashes"
        rule["cite"] = {"table_id": "p735-t0", "row": size,
                        "column": f"보호통 {trade}(인)", "value": "-"}
PATH.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("restored eight explicit source dashes and exact source-cited resource exclusions")
