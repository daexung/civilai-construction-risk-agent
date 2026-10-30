"""Connect source-backed post-spacing rates for both safety guardrail specs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    "2-8-11": ("p110-t2", {"1.0m이하": ("11/10", "110%"), "1.5m이하": ("1", "100%"),
                            "1.5m초과": ("9/10", "90%")}),
    "2-8-13": ("p111-t1", {"1.0m이하": ("11/10", "1.10"), "1.5m이하": ("1", "1.00"),
                            "1.5m초과": ("9/10", "0.90")}),
}


def main() -> None:
    for section, (table_id, routes) in ROUTES.items():
        path = ROOT / f"data/drafts/specs/공통/{section}.json"
        package = json.loads(path.read_text(encoding="utf-8"))
        params = package["draft"]["quantity_model"]["params"]
        rate = params["unit_rate_table"]
        rate["base_rate_multipliers"] = [
            {"when": {"post_spacing": spacing}, "factor": factor,
             "cite": {"table_id": table_id, "row": "요율", "column": spacing, "value": source_value}}
            for spacing, (factor, source_value) in routes.items()
        ]
        for note in params.get("note_adjustments", []):
            note["implemented_by"] = f"unit_rate_table.base_rate_multipliers referencing {table_id}"
        path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("connected exact source spacing multipliers for 2-8-11 and 2-8-13")


if __name__ == "__main__":
    main()
