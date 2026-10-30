"""Check 11-1-2 source-selected rates, unsupported cells, and offline costs."""
from __future__ import annotations

import itertools
import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/11-1-2.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(CHUNKS), file_sha256(CHUNKS))
    assert validation["format_issues"] == [] and validation["citation_issues"] == [], validation
    rate_table = next(t for t in spec["tables"] if t["id"] == "p769-t1")["values"]
    rate_columns = {
        "인력시공": ("배관공(인)", "보통인부(인)"),
        "기계시공": ("배관공(인)", "보통인부(인)", "크레인(hr)"),
    }
    blocked_sizes = {"ø15", "20", "25", "32", "40", "50", "65", "80", "100", "125"}
    rate_version = select_rate_version("2026-10-19")
    assert rate_version and rate_version["id"] == "2026H2"
    checked = computed = blocked = cost_checks = cost_basis_blocked = equipment_unpriced = 0

    for size, method in itertools.product(spec["inputs"][0]["allowed_values"], spec["inputs"][1]["allowed_values"]):
        inputs = {"pipe_size": size, "construction_method": method, "quantity": "100"}
        result = per_unit(spec, inputs)
        checked += 1
        if method == "기계시공" and size in blocked_sizes:
            assert result["status"] == "blocked", (size, method, result)
            blocked += 1
            continue
        assert result["status"] == "computed", (size, method, result)
        computed += 1
        selected_columns = rate_columns[method]
        expected = {}
        for column in selected_columns:
            raw = rate_table[size].get(f"{method} {column}")
            assert raw is not None, (size, method, column)
            expected_name = column.removesuffix("(인)") if column.endswith("(인)") else column
            expected[expected_name] = str(Fraction(raw))
        actual = {line["name"]: line["exact"] for line in result["unit_lines"]}
        assert actual == expected, (size, method, actual, expected)
        source_column_by_name = {
            (column.removesuffix("(인)") if column.endswith("(인)") else column): column
            for column in selected_columns
        }
        for line in result["unit_lines"]:
            cite = line["citations"][0]
            source_column = source_column_by_name[line["name"]]
            assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                "p769-t1", size, f"{method} {source_column}", rate_table[size][f"{method} {source_column}"])

        price = price_unit(spec, result["unit_lines"], rate_version, inputs=inputs, basis_date="2026-10-19")
        expected_rate = Decimal("0.01") if method == "인력시공" else Decimal("0.03")
        labor_subtotal = Decimal(price["labor_subtotal"])
        costs = [c for c in price["cost_lines"] if c["name"].startswith("공구손료 및 경장비")]
        assert len(costs) == 1 and Decimal(costs[0]["rate"]) == expected_rate
        assert costs[0]["citations"][0]["internal_id"] == "p770-t0"
        if method == "기계시공":
            assert any(row["name"] == "크레인(hr)" and row["reason"] for row in price["unpriced"]), price
            equipment_unpriced += 1
            # The source supplies crane hours but the offline wage table has no
            # crane rate. The calculator must leave the labor-based percentage
            # unpriced when its labor subtotal is incomplete.
            assert costs[0]["amount_exact"] is None and costs[0]["reason"], costs[0]
            cost_basis_blocked += 1
        else:
            assert Decimal(costs[0]["amount_exact"]) == labor_subtotal * expected_rate
            cost_checks += 1
    assert checked == 32 and computed == 22 and blocked == 10
    assert cost_checks == 16 and cost_basis_blocked == 6 and equipment_unpriced == 6
    print(json.dumps({"status": "pass", "section": "기계설비/11-1-2",
                      "source_value_cells_checked": 52, "method_size_paths": checked,
                      "computed": cost_checks, "blocked_source_dash_paths": blocked,
                      "offline_cost_paths": cost_checks, "unpriced_due_to_missing_crane_rate": cost_basis_blocked,
                      "crane_unit_price_guessed": False,
                      "every_rule_verified": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
