"""Recover 9-17-2/3/4 exact per-map bases and office-only source values."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.daily_crew import _exact_text
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

TARGETS = {
    "9-17-2": {"table": "p616-t0", "basis": "1매", "rates": {"지적기사": "(0.14)", "지적산업기사": "(0.63)"}, "factor_table": "p616-t1", "application": {"chunk_id": "p616-x10", "quote": "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."}},
    "9-17-3": {"table": "p617-t0", "basis": "1매", "rates": {"지적기사": "(0.15)", "지적산업기사": "(0.34)"}, "factor_table": "p617-t1", "application": {"chunk_id": "p617-x4", "quote": "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."}},
    "9-17-4": {"table": "p617-t2", "basis": "1장", "rates": {"지적산업기사": "(0.78)"}, "factor_table": "p617-t3", "application": {"chunk_id": "p617-x18", "quote": "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."}},
}


def default_inputs(draft: dict, quantity: str) -> dict:
    values = {}
    for field in draft["inputs"]:
        if field["name"] == "quantity":
            values[field["name"]] = quantity
        elif field.get("allowed_values") is True or field.get("allowed_values") is False:
            values[field["name"]] = False
        elif (isinstance(field.get("allowed_values"), list)
              and all(isinstance(value, bool) for value in field["allowed_values"])):
            values[field["name"]] = False
        elif isinstance(field.get("allowed_values"), list):
            values[field["name"]] = field["allowed_values"][0]
        elif field.get("type") == "boolean":
            values[field["name"]] = False
    return values


def main() -> int:
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = load_chunks(chunks_path)
    results = []
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    for section, expected in TARGETS.items():
        spec_path = ROOT / f"data/drafts/specs/토목/{section}.json"
        package = json.loads(spec_path.read_text(encoding="utf-8"))
        draft = package["draft"]
        rate = draft["quantity_model"]["params"]["unit_rate_table"]
        table_id = expected["table"]
        assert rate["table"] == table_id
        table = next(item for item in draft["tables"] if item["id"] == table_id)
        total = table["values"]["합계"]
        for trade, raw in expected["rates"].items():
            key = next((column for column in total if trade in column.replace("\n", "")), None)
            assert key and total[key] == raw, (section, trade, total)

        rate["basis_by_row"] = {"합계": expected["basis"]}
        rate.pop("column_input", None)
        rate["trades"] = list(expected["rates"])
        params = draft["quantity_model"]["params"]
        params["note_adjustments"] = [item for item in params.get("note_adjustments", [])
                                      if "land_type" not in item.get("when", {})]
        params["surcharges"] = [{"when": {"land_type": "임야"}, "rate": "1.28",
                                 "applies_to": list(expected["rates"]),
                                 "operation": "multiply",
                                 "rate_table": {"id": expected["factor_table"], "row": "계수", "column": "임야"},
                                 "application_cite": expected["application"],
                                 "source": f"PDF source factor table {expected['factor_table']}: 토지 1.00, 임야 1.28"}]
        rate["parenthetical_value_selector"] = {
            "mode": "parenthetical_only",
            "source": "PDF table note: parenthesized values indicate office work; table rates are parenthetical-only.",
            "cite": {"chunk_id": table_id, "quote": "( )는 내업임"},
        }
        spec_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        route_results = []
        for quantity in ("1", "10"):
            for land_type in ("토지", "임야"):
                inputs = default_inputs(draft, quantity)
                inputs["land_type"] = land_type
                computed = per_unit(draft, inputs)
                assert computed.get("status") == "computed", (section, inputs, computed)
                unit_rates = {line["name"]: line["applied"] for line in computed["unit_lines"]}
                factor = Fraction("1") if land_type == "토지" else Fraction("1.28")
                wanted = {trade: _exact_text(Fraction(raw.strip("()")) * factor)
                          for trade, raw in expected["rates"].items()}
                assert unit_rates == wanted, (section, wanted, unit_rates)
                priced = price_unit(draft, computed["unit_lines"], select_rate_version("2026-10-01"),
                                    inputs, "2026-10-01")
                assert priced.get("status") in ("COMPLETE", "PARTIAL"), (section, priced)
                route_results.append({"quantity": quantity, "land_type": land_type, "inputs": inputs,
                                      "unit_rates": unit_rates, "price_status": priced["status"],
                                      "price_line_quantities": {line["name"]: line["quantity"]
                                                                 for line in priced["lines"]}})

        validation = validate_one(spec_path, ROOT / "data/drafts", chunks, file_sha256(chunks_path))
        assert validation["ok"], (section, validation)
        old = next(item for item in report["results"]
                   if item["path"].replace("\\", "/") == f"specs/토목/{section}.json")
        report["ok"] += int(validation["ok"]) - int(old["ok"])
        for key in ("with_format_issues", "with_citation_issues"):
            field = key.replace("with_", "")
            report[key] += int(bool(validation[field])) - int(bool(old[field]))
        report["results"][report["results"].index(old)] = validation

        ident = draft["id"]
        index["failed"] = [item for item in index["failed"] if item["id"] != ident]
        index["executable"] = sorted(set(index["executable"]) | {ident})
        results.append({"id": ident, "table": table_id, "source_basis": expected["basis"],
                        "source_cells": {trade: total[next(column for column in total
                                                              if trade in column.replace("\n", ""))]
                                         for trade in expected["rates"]},
                        "source_note": "( )는 내업임", "routes": route_results,
                        "focused_validation_ok": validation["ok"]})

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = ROOT / "evals/runtime_validation/per-unit-9-17-map-basis-source-cluster-2026-10-19.json"
    out.write_text(json.dumps({"method": "three exact original-page table audits; explicit denominator + office-value interpretation; no fuzzy mapping",
                               "sections": results,
                               "source_visuals": ["tmp/9-17-1-source-p616.png", "tmp/9-17-1-source-p617.png"],
                               "scope": "source denominator, exact totals, selection, price routing and draft validation; remaining rules are not certified"},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promoted": [r["id"] for r in results], "focused_validation": [r["focused_validation_ok"] for r in results],
                      "source_cells": {r["id"].split("/")[-2]: r["source_cells"] for r in results}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
