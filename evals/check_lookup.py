"""Focused source-cell and scope checks for the declarative lookup calculator."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from backend.agent.tools.calc.lookup import lookup  # noqa: E402


def main() -> int:
    path = ROOT / "data/drafts/specs/공통/2-1-1.json"
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    table = next(item for item in spec["tables"] if item["id"] == "p91-t0")
    checks = 0
    for row, columns in table["values"].items():
        for column, expected in columns.items():
            result = lookup(spec, {"direct_labor_cost_band": row, "facility_type": column})
            assert result["status"] == "computed", (row, column, result)
            assert result["value"] == expected, (row, column, expected, result)
            assert result["unit"] == table["unit"] == "㎡"
            cite = result["provenance"]["citations"][0]
            assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                "p91-t0", row, column, expected)
            assert result["scope_notes"]["open_questions"] == spec.get("open_questions", [])
            checks += 1
    invalid = lookup(spec, {"direct_labor_cost_band": "50억",
                            "facility_type": spec["inputs"][1]["allowed_values"][0]})
    assert invalid["status"] == "rejected", invalid
    print(f"PASS p91-t0 원문 셀·단위·인용·적용조건 {checks}/{checks}; 적용범위 밖 입력 차단")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
