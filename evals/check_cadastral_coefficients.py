"""Source-value check for the 9-15-1/2 worked coefficient examples."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit


def run(section: str) -> dict:
    path = next((ROOT / "data/drafts/specs").rglob(f"{section}.json"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    inputs = {}
    for field in spec["inputs"]:
        name = field["name"]
        if name in ("parcel_count", "quantity"):
            inputs[name] = "2"
        elif name in ("area", "area_per_parcel"):
            inputs[name] = "7000"
        elif name == "land_type":
            inputs[name] = field["allowed_values"][0]
        elif name in ("region", "region_type"):
            inputs[name] = field["allowed_values"][-1]
        elif name == "division_display":
            inputs[name] = field["allowed_values"][0]
        elif field["type"] == "boolean":
            inputs[name] = False
    return per_unit(spec, inputs)


def main() -> int:
    expected = {
        "9-15-1": {"지적기사": "1.36", "지적산업기사": "1.44", "지적기능사": "0.84"},
        "9-15-2": {"지적기사": "1.22", "지적산업기사": "1.3", "지적기능사": "0.74"},
        # 9-15-3 says to multiply each coefficient; unlike the first two
        # sections it has no worked numerical example, so this is clause-level.
        "9-15-3": {"지적기사": "1.4112", "지적산업기사": "1.9936", "지적기능사": "0.7616"},
    }
    # The source's 7,000 m² / 1,500 m² example explicitly yields area delta .60,
    # region delta .40 and total coefficient 2.00; both schedules use that example.
    for section, values in expected.items():
        result = run(section)
        lines = result.get("unit_lines", [])
        observed = {line["name"].split(" (")[0]: line["applied"] for line in lines}
        assert result["status"] == "computed", (section, result)
        assert observed == values, (section, observed, values)
        assert all(len(line["citations"]) >= 3 for line in lines), section
        print(f"PASS {section} source worked example: {observed}")
    print("Source coverage: 9-15-1/2 worked example (additive total 2.00); 9-15-3 source clauses (multiplicative coefficients).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
