from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
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

SPEC = ROOT / "data/drafts/specs/기계설비/13-11-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TABLE = "p906-t1"
SOURCE_RATES = [
    ("기술관리 : 공사기간중", "기계산업기사", "인/일", "1.0", "duration"),
    ("기초 Check : 기초 check", "기계설비공", "인/㎡", "0.41", "base_area"),
    ("Chipping 및 Grouting", "특별인부", "인/㎡", "0.595", "base_area"),
    ("표면손질 : Eliminator 및 구동부", "특별인부", "인/㎡", "0.2", "surface_area"),
    ("본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 철골공", "철골공", "인/ton", "4.18", "weight"),
    ("본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 비계공", "비계공", "인/ton", "3.0", "weight"),
    ("본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 특별인부", "특별인부", "인/ton", "0.3", "weight"),
    ("Drift-Eliminator 설치 / 건축목공", "건축목공", "인/㎡", "3.1", "eliminator_area"),
    ("Drift-Eliminator 설치 / 보통인부", "보통인부", "인/㎡", "0.698", "eliminator_area"),
    ("스레이트 잇기 / 스레이트공", "스레이트공", "인/㎡", "0.05", "slate_area"),
    ("스레이트 잇기 / 보통인부", "보통인부", "인/㎡", "0.04", "slate_area"),
    ("충전물충전 : 충전물을 규격별 순서로 충전 작업함", "보통인부", "인/㎥", "0.6", "filler_volume"),
]
INPUTS = {"duration": "2", "base_area": "100", "surface_area": "50", "weight": "3",
          "eliminator_area": "20", "slate_area": "30", "filler_volume": "15"}
EXPECT_NUMERIC = [entry[3] for entry in SOURCE_RATES]
EXPECT_UNITS = ["인/일", "인/㎡", "〃", "인/㎡", "인/ton", "〃", "〃",
                "인/㎡", "〃", "인/㎡", "〃", "인/㎥"]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == TABLE)
    expected_values = {row: {"직종": trade, "단위": unit, "수량": value}
                       for row, trade, unit, value, _ in SOURCE_RATES}
    assert table["values"] == expected_values
    field_units = {f["name"]: f["unit"] for f in spec["inputs"]}

    # Extract the original rate and unit columns by page coordinates; profession/task placement was
    # independently transcribed from the rendered PDF, including the table's vertical merged cells.
    with pymupdf.open(PDF) as document:
        page = document[905]
        words = page.get_text("words")
        rate_cells = sorted((w[1], w[4]) for w in words
                            if 460 < w[1] < 670 and w[0] > 480
                            and re.fullmatch(r"\d+(?:\.\d+)?", w[4]))
        assert [value for _, value in rate_cells] == EXPECT_NUMERIC, rate_cells
        unit_cells = sorted((w[1], w[4]) for w in words
                            if 460 < w[1] < 670 and 390 < w[0] < 450
                            and ("/" in w[4] or w[4] == "〃"))
        assert [unit for _, unit in unit_cells] == EXPECT_UNITS, unit_cells
        page_text = page.get_text()
        assert "기초 Check : 기초 check" in page_text and "Chipping 및 Grouting" in page_text
        assert "기술관리를 제외한 전 품의 10%" in page_text
        assert "가공품은 제외되었다" in page_text

    result = per_unit(spec, INPUTS, labor_only=True)
    assert result["status"] == "computed", result
    source_lines = [line for line in result["unit_lines"] if line["name"] != "검사 및 교정"]
    assert len(source_lines) == 12, len(source_lines)
    actual = {}
    for line in source_lines:
        cell = line["citations"][0]
        assert cell["internal_id"] == TABLE and cell["column"] == "수량"
        actual[cell["row"]] = (line["name"], line["unit"], Fraction(line["exact"]),
                                line.get("quantity_input"))
    for row, trade, basis, rate, qname in SOURCE_RATES:
        quantity_input = qname if row != "기초 Check : 기초 check" else None
        expected_unit = f"인/{field_units[qname]}"
        assert actual[row] == (trade, expected_unit, Fraction(rate), quantity_input), (row, actual[row])
    actual_base_total = sum((Fraction(line["exact"]) * Fraction(INPUTS[line.get("quantity_input") or "base_area"])
                             for line in source_lines), Fraction())
    assert actual_base_total == Fraction("222.6")

    inspection = [line for line in result["unit_lines"] if line["name"] == "검사 및 교정"]
    expected_inspection = [(trade, qname, Fraction(rate) / 10)
                           for row, trade, _, rate, qname in SOURCE_RATES
                           if trade != "기계산업기사"]
    assert len(inspection) == len(expected_inspection) == 11
    got_inspection = [(line.get("quantity_input"), Fraction(line["exact"])) for line in inspection]
    assert got_inspection == [(qname, rate) for _, qname, rate in expected_inspection]
    assert all(any(c.get("quote") == "검사 및 교정 | 기술관리를 제외한 전 품의 10%"
                       for c in line["citations"]) for line in inspection)
    assert sum((Fraction(line["exact"]) * Fraction(INPUTS[line["quantity_input"]])
                for line in inspection), Fraction()) == Fraction("22.06")

    # Independently sum the source rates after applying each distinct work quantity.
    expected_work_totals = defaultdict(Fraction)
    for _, trade, _, rate, qname in SOURCE_RATES:
        expected_work_totals[trade] += Fraction(rate) * Fraction(INPUTS[qname])
    expected_work_totals["검사 및 교정"] = Fraction("22.06")
    assert sum(expected_work_totals.values(), Fraction()) == Fraction("244.66")
    assert actual_base_total + sum((Fraction(line["exact"]) * Fraction(INPUTS[line["quantity_input"]])
                                    for line in inspection), Fraction()) == Fraction("244.66")

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    rate_version = select_rate_version("2026-10-19")
    priced = price_unit(spec, result["unit_lines"], rate_version, INPUTS, basis_date="2026-10-19")
    assert priced.get("rate_version", {}).get("id") == rate_version["id"]
    # Unavailable local wage mappings remain visibly unpriced; no substitute rates are injected.
    unpriced_inspection = [x for x in priced.get("unpriced", []) if x.get("name") == "검사 및 교정"]
    assert len(unpriced_inspection) == 11
    node_status = "not_registered"
    if spec["id"] in load_specs():
        node = compute({"spec_id": spec["id"], "inputs": INPUTS})
        assert node["status"] == "COMPUTED", node
        node_status = node["status"]
    report = {
        "id": spec["id"], "status": "pass", "physical_page": 906, "printed_page": 850,
        "source_numeric_rate_cells": 12, "source_unit_cells_including_ditto_marks": 12,
        "task_trade_rate_routes": len(source_lines), "heterogeneous_input_units": ["일", "㎡", "ton", "㎥"],
        "source_inspection_rule": "10% of each labor task/trade rate except 기술관리",
        "inspection_derived_lines": len(inspection), "inspection_total_for_test_inputs": "22.06인",
        "independent_expected_total_for_test_inputs": "244.66인",
        "ditto_unit_inheritance_checked": True,
        "fabricated_drift_eliminator_material": "excluded by source note and retained not_calculated",
        "local_rate_version": rate_version["id"], "unpriced_inspection_lines": len(unpriced_inspection),
        "validator_ok": validation["ok"], "calculation_node": node_status,
        "full_rule_verification": False,
    }
    output = ROOT / "evals/runtime_validation/mechanical-13-11-2-cooling-tower-mixed-unit-source-audit-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
