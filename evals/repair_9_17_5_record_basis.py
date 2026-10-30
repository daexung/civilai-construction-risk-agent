"""Verify and restore 9-17-5's per-record office-work source coefficient."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-17-5.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p618-t0")
    assert table["values"]["합계"]["합계 인원수 지적산업기사"] == "(0.04)"
    assert table["values"]["합계"]["일수"] == "(0.04)"
    quantity = next(field for field in draft["inputs"] if field["name"] == "quantity")
    assert quantity["unit"] == "필지"

    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["basis_by_row"] = {"합계": "인/필지"}
    rate["parenthetical_value_selector"] = {
        "mode": "parenthetical_only",
        "cite": {"chunk_id": "p618-t0", "quote": "( )는 내업임"},
    }
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for amount in ("1", "10"):
        inputs = {"quantity": amount}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", result
        assert len(result["unit_lines"]) == 1
        line = result["unit_lines"][0]
        assert line["name"] == "지적산업기사"
        assert line["exact"] == str(Fraction("0.04")), line
        selected = result["provenance"]["unit_rates"]["지적산업기사"]
        assert selected["selected_source_value"] == "0.04", selected
        assert any(cite.get("quote") == "( )는 내업임" for cite in line["citations"])
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        expected_quantity = "0.04"
        assert priced["lines"][0]["quantity"] == expected_quantity, priced["lines"]
        assert priced["reference_amounts"]["volume"] == amount
        assert int(priced["reference_amounts"]["total"]) == 10049 * int(amount)
        cases.append({"quantity_fields": inputs, "expected_unit_rate": "0.04",
                      "actual_unit_rate": line["exact"], "expected_priced_quantity": expected_quantity,
                      "reference_amounts": priced["reference_amounts"],
                      "actual_priced_quantity": priced["lines"][0]["quantity"],
                      "price_status": priced["status"]})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-17-5.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = {"id": ident, "source": {"physical_page": 618, "printed_page": 562,
             "table": "p618-t0", "table_total_cell": "(0.04)", "table_basis": "전필별 조서작성",
             "parenthetical_note": "( )는 내업임", "visual_checked": "tmp/9-17-5-source-p618.png"},
             "independent_cell_check": {"합계/일수": "(0.04)",
                                        "합계/합계 인원수 지적산업기사": "(0.04)"},
             "cases": cases, "focused_validation_ok": validation["ok"],
             "scope": "exact total row, per-parcel denominator, parenthetical office value, 1/10 parcel rates and offline pricing checked; all-rule inventory coverage not claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-9-17-5-record-source-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "cases": len(cases), "expected_unit_rate": "0.04"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
