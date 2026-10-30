"""Verify the note-based material coefficient without inventing its price."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-7-22.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def main() -> None:
    page = fitz.open(PDF)[889]
    source = page.get_text()
    assert "13-7-22 노 기밀 시험" in source
    assert "④ 누설 Check용 가루비누는 ㎥당 0.04㎏ 계상한다." in source
    table = page.find_tables().tables[0].extract()
    names = ["".join(name.split()) for name in table[1][0].splitlines()]
    quantities = table[1][1].splitlines()
    assert dict(zip(names, quantities)) == {"기계기사": "0.023", "특별인부": "0.387"}

    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    material = spec["quantity_model"]["params"]["additional_materials"][0]
    assert material["source_rate"] == "0.04" and material["basis"] == "kg/㎥"
    from pipeline.validate_drafts import chunks_by_id_from_list, validate_one
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()])
    valid = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, None)
    assert valid["ok"], valid

    from backend.agent.tools.calc.per_unit import per_unit
    result = per_unit(spec, {"volume": "100"}, labor_only=True)
    assert result["status"] == "computed", result
    lines = {line["name"]: line for line in result["unit_lines"]}
    assert Fraction(lines["기계기사"]["exact"]) == Fraction(23, 1000)
    assert Fraction(lines["특별인부"]["exact"]) == Fraction(387, 1000)
    assert lines["가루비누"]["kind"] == "material"
    assert Fraction(lines["가루비누"]["exact"]) == Fraction(1, 25)
    assert "누설 Check용 가루비누" in lines["가루비누"]["citations"][0]["quote"]

    from backend.agent.tools.calc.price import price_unit, select_rate_version
    priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-06-01"), {"volume": "100"})
    soap = next(item for item in priced["lines"] if item["name"] == "가루비누")
    assert Fraction(soap["quantity"]) == Fraction(1, 25)
    assert Fraction(soap["quantity"]) * 100 == 4
    assert soap["amount_exact"] is None and "재료 단가 자료 없음" in soap["reason"]
    report = {"status": "source_labor_and_note_material_quantity_verified",
              "id": spec["id"], "source": {"physical_page": 890, "printed_page": 834,
                  "labor_cells": 2, "note_rate": "0.04 kg/㎥", "source_quote_checked": True},
              "runtime": {"cases": 1, "soap_quantity_at_100m3": "4 kg", "unit_price_status": "unpriced: no material price source supplied",
                          "existing_labor_status": " 기계기사 wage mapping missing; 특별인부 amount computed",
                          "full_rules_verified": False}}
    out = ROOT / "evals/runtime_validation/13-7-22-note-material-source-calc-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
