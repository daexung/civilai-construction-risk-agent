from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/13-11-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
INSTALL = {
    "기계산업기사": "0.50", "비계공": "1.255", "특별인부": "5.270", "제관공": "1.470",
    "용접공": "0.882", "기계설비공": "0.882", "측량사": "0.167", "검사시험": "0.975",
}
INSTALL_PROCESS_VALUES = ["0.500", "0.667", "0.333", "3.3", "0.588", "0.588", "0.588",
                          "0.882", "0.882", "0.588", "0.294", "0.882", "0.167", "0.167", "0.975"]
INSTALL_PROCESS_TRADE = ["기계산업기사", "비계공", "특별인부", "특별인부", "제관공", "용접공", "특별인부",
                         "기계설비공", "제관공", "비계공", "용접공", "특별인부", "측량사", "특별인부", "검사시험"]
REPAIR_DIRECT = ["0.785", "1.830", "2.041", "4.972", "0.962", "10.590"]
REPAIR_PROCESS = ["0.785", "1.830", "0.549", "1.067", "0.320", "3.905", "1.172", "0.962"]


def main() -> int:
    pkg = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = pkg["draft"]
    assert spec["quantity_model"]["name"] == "per_unit"
    assert spec["tables"][0]["values"] == {trade: {"수량": value} for trade, value in INSTALL.items()}

    with pymupdf.open(PDF) as document:
        page = document[906]
        # Independent page-coordinate extraction of all eight direct labor cells.
        direct_words = [(round(w[1], 2), w[0], w[4]) for w in page.get_text("words")
                        if 123.4 <= w[1] < 206.6 and 270 < w[0] < 510
                        and re.fullmatch(r"\d+(?:\.\d+)?", w[4])]
        direct_words.sort()
        expected_direct_by_row = [("0.50", "0.882"), ("1.255", "0.882"),
                                  ("5.270", "0.167"), ("1.470", "0.975")]
        assert len(direct_words) == 8, direct_words
        for i, (left, right) in enumerate(expected_direct_by_row):
            row = direct_words[i * 2:i * 2 + 2]
            assert [cell[2] for cell in row] == [left, right], row

        # The process table is a second, independently laid-out presentation of the same labor.
        process_words = [(round(w[1], 2), w[4]) for w in page.get_text("words")
                         if 263 <= w[1] < 546 and w[0] > 450
                         and re.fullmatch(r"\d+(?:\.\d+)?", w[4])]
        process_words.sort()
        assert [w[1] for w in process_words] == INSTALL_PROCESS_VALUES, process_words
        by_trade: dict[str, Fraction] = defaultdict(Fraction)
        for trade, value in zip(INSTALL_PROCESS_TRADE, INSTALL_PROCESS_VALUES):
            by_trade[trade] += Fraction(value)
        assert dict(by_trade) == {trade: Fraction(value) for trade, value in INSTALL.items()}
        # Independent derivation of the source's 10% inspection row, then source-precision truncation.
        inspection_basis = sum((Fraction(v) for trade, v in zip(INSTALL_PROCESS_TRADE, INSTALL_PROCESS_VALUES)
                                if trade not in ("기계산업기사", "검사시험")
                                and not (trade == "특별인부" and v == "0.167")), Fraction())
        # The excluded 0.167 is the final clean-up row; the other 0.167 is survey labor.
        inspection_exact = inspection_basis * Fraction(1, 10)
        assert inspection_exact == Fraction("0.9759")
        assert int(inspection_exact * 1000) == int(Fraction("0.975") * 1000)

        page_repair = document[907]
        repair_direct = [(round(w[1], 2), w[4]) for w in page.get_text("words")
                        if 592.8 <= w[1] < 709.4 and w[0] > 380
                         and re.fullmatch(r"\d+(?:\.\d+)?", w[4])]
        repair_direct.sort()
        assert [w[1] for w in repair_direct] == REPAIR_DIRECT, repair_direct
        repair_process = [(round(w[1], 2), w[4]) for w in page_repair.get_text("words")
                          if 70 < w[1] < 250 and w[0] > 400
                          and re.fullmatch(r"\d+(?:\.\d+)?", w[4])]
        repair_process.sort()
        assert [w[1] for w in repair_process] == REPAIR_PROCESS, repair_process
        assert sum(map(Fraction, REPAIR_DIRECT[:-1])) == Fraction(REPAIR_DIRECT[-1])
        assert sum(map(Fraction, REPAIR_PROCESS)) == Fraction(REPAIR_DIRECT[-1])
        note = "".join(page_repair.get_text().split())
        assert all(token in note for token in ("파손및마모부분의제작설치에만적용", "전기배관,배선및도장품은포함되어있지않다"))

    cases = []
    for quantity in ("1", "5", "25.5"):
        result = per_unit(spec, {"quantity": quantity}, labor_only=True)
        assert result["status"] == "computed", result
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        assert actual == {trade: Fraction(value) for trade, value in INSTALL.items()}, actual
        assert all(line["unit"] == "인/ton" and line["citations"][0]["internal_id"] == "p907-t0"
                   for line in result["unit_lines"])
        cases.append(quantity)

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    version = select_rate_version("2026-10-19")
    priced = price_unit(spec, per_unit(spec, {"quantity": "1"}, labor_only=True)["unit_lines"],
                        version, {"quantity": "1"}, basis_date="2026-10-19")
    indexed = spec["id"] in load_specs()
    node_status = "not_registered"
    if indexed:
        node = compute({"spec_id": spec["id"], "inputs": {"quantity": "1"}})
        assert node["status"] == "COMPUTED", node
        node_status = node["status"]
    report = {
        "id": spec["id"], "status": "pass", "physical_pages": [907, 908], "printed_pages": [851, 852],
        "direct_install_source_rate_cells": 8, "process_breakdown_numeric_cells": 15,
        "process_by_trade_sums_equal_direct_table": True,
        "inspection_10pct_basis_exact": str(inspection_basis),
        "inspection_exact_before_source_precision": str(inspection_exact),
        "inspection_source_cell": "0.975", "source_precision_relation": "truncated to the table's displayed 0.001 place",
        "repair_cells_independently_checked_but_not_added": 14,
        "repair_direct_sum": REPAIR_DIRECT[-1], "repair_breakdown_sum": REPAIR_DIRECT[-1],
        "quantities_checked_ton": cases, "local_price_version": version["id"],
        "unpriced_local_wage_rows": [x.get("name") for x in priced.get("unpriced", [])],
        "validator_ok": validation["ok"], "calculation_node": node_status,
        "scope": "Basic direct installation labor only; repair, reference equipment/material, transport and excluded work remain separately itemized.",
        "full_rule_verification": False,
    }
    out = ROOT / "evals/runtime_validation/mechanical-13-11-3-batcher-install-labor-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
