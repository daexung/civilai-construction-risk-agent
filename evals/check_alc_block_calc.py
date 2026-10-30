"""Offline source-value check for the ALC block laying schedule."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("2-3-1.json")
                if "p639-t1" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    inputs = {}
    for field in spec["inputs"]:
        if field["name"] == "height":
            inputs[field["name"]] = field["allowed_values"][0]
        elif field["name"] == "block_size":
            inputs[field["name"]] = field["allowed_values"][0]
        elif field["name"] == "quantity":
            inputs[field["name"]] = "100"
        elif field["type"] == "boolean":
            inputs[field["name"]] = False
    source_row = next(row for row in spec["tables"] if row["id"] == "p639-t1")["values"]
    production = next(iter(source_row.values()))
    rate = next(value for key, value in production.items() if "시공량" in key)
    assert rate == "23", rate  # PDF p.583, 600x400x100, <=3.6m
    result = adjusted_daily_crew(spec, inputs)
    assert result["status"] == "computed", result
    lines = {line["name"].split("_")[-1]: line for line in result["unit_lines"]}
    assert lines["조적공"]["exact"] == "3/23", lines
    assert lines["보통인부"]["exact"] == "1/23", lines
    mortar = next(line for line in result["unit_lines"] if line["kind"] == "material")
    assert mortar["exact"] == "600" and mortar["citations"][0]["internal_id"] == "p639-t2", mortar

    forklift = adjusted_daily_crew(spec, {**inputs, "use_forklift": True})
    assert forklift["status"] == "computed", forklift
    fork_lines = {line["name"].split("_")[-1]: line for line in forklift["unit_lines"]}
    assert fork_lines["보통인부"]["exact"] == "0", fork_lines
    equipment = next(line for line in forklift["unit_lines"] if line["kind"] == "equipment")
    assert equipment["exact"] == "5/46", equipment
    out_of_scope = adjusted_daily_crew(spec, {**inputs, "height": spec["inputs"][0]["allowed_values"][-1]})
    assert out_of_scope["status"] == "blocked", out_of_scope
    print("PASS PDF p.583 source base: 23㎡/day, 3 masons, 1 helper; material 6 kg/㎡.")
    print("PASS forklift adjustment: helper removed, 2.5hr/day; >7.2m remains blocked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
