"""Restore the source-declared one-map-sheet basis for civil 9-18-4."""
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

SPEC = ROOT / "data/drafts/specs/토목/9-18-4.json"
EXPECTED = {"지적기사": "0.004", "지적산업기사": "0.040", "지적기능사": "0.001"}


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p620-t1")
    assert table["values"]["합계"] == EXPECTED
    field = next(item for item in draft["inputs"] if item["name"] == "quantity")
    assert field["unit"] == "도곽"
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["basis_by_row"] = {"합계": "인/도곽"}
    rate["basis_cites_by_row"] = {"합계": {"chunk_id": "p621-x0",
                                              "quote": "본 품은 지적(임야)도 1도곽을 기준한 것이다."}}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for amount in ("1", "10"):
        inputs = {"quantity": amount}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", result
        actual = {line["name"]: line["applied"] for line in result["unit_lines"]}
        normalized_expected = {"지적기사": "0.004", "지적산업기사": "0.04", "지적기능사": "0.001"}
        assert actual == normalized_expected, (actual, normalized_expected)
        assert all(any(c.get("value") == EXPECTED[line["name"]] for c in line["citations"])
                   for line in result["unit_lines"])
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        assert priced["reference_amounts"]["volume"] == amount
        cases.append({"inputs": inputs, "unit_rates": actual,
                      "reference_amounts": priced["reference_amounts"],
                      "price_status": priced["status"]})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-18-4.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        report[key] += int(bool(validation[key.replace("with_", "")])) - int(bool(old[key.replace("with_", "")]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    artifact = {"id": ident, "source": {"physical_page": 620, "printed_page": 564,
                "table": "p620-t1", "exact_total_cells": EXPECTED,
                "basis_quote": "본 품은 지적(임야)도 1도곽을 기준한 것이다.",
                "visual_checked": "tmp/9-18-4-source-p620.png"}, "cases": cases,
                "focused_validation_ok": validation["ok"],
                "scope": "three exact total cells, 1-map-sheet basis, quantity 1/10 and offline price route verified; all-rule inventory coverage not claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-9-18-4-map-basis-source-audit-2026-10-19.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "source_cells": len(EXPECTED), "routes": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
