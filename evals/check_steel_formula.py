"""Source-derived arithmetic checks for the shared declarative formula executor."""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

from backend.agent.tools.calc.formula import formula_quantity  # noqa: E402


def main() -> int:
    path = next(path for path in (ROOT / "data/drafts/specs").rglob("*.json")
                if json.loads(path.read_text(encoding="utf-8"))["draft"].get("section_no") == "1-1-2"
                and json.loads(path.read_text(encoding="utf-8"))["draft"].get("quantity_model", {}).get("name") == "formula")
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    page = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[624].extract_text() or ""
    compact = re.sub(r"\s+", "", page)
    for source_value in ("0.8∼0.95", "1.05∼1.2", "×0.71", "7.0", "2.8", "2.0", "6.0"):
        assert source_value in compact, source_value
    fields = {field["name"]: field for field in spec["inputs"]}
    material_type = fields["material_type"]["allowed_values"][1]
    structure = fields["structure_type"]["allowed_values"][0]
    inputs = {"total_steel_usage_band": fields["total_steel_usage_band"]["allowed_values"][0],
              "structure_type": structure, "difficulty_factor": "0.9",
              "material_type": material_type, "quantity": "2"}
    result = formula_quantity(spec, inputs)
    assert result["status"] == "computed", result
    lines = {line["name"]: line for line in result["unit_lines"]}
    # 1-1-1's 60t 미만 rate 2.48 is multiplied by the quoted H-shape 0.71.
    assert Fraction(lines["철골공수"]["exact"]) == Fraction("2.48") * Fraction("0.71") * Fraction("0.9") * 2
    # Independently multiply each original-PDF rate by 2 ton.
    expected = {"산소": (7, "㎥"), "L.P.G": (Fraction("2.8"), "㎏"),
                "서비스볼트": (2, "본"), "보조강재": (4, "㎏")}
    for name, (amount, unit) in expected.items():
        assert Fraction(lines[name]["exact"]) == amount
        assert lines[name]["unit"] == unit
        citation = lines[name]["citations"][0]
        assert citation["internal_id"] == "p625-t2" and citation["value"]
    assert lines["철골공수"]["citations"][0]["quote"] == "철골공수=기본철골공수×작업난이도"
    assert result["provenance"]["철골공수"]["references"]["base_labor"]["section_id"].endswith("/1-1-1/기본철골공수")

    invalid = formula_quantity(spec, {**inputs, "difficulty_factor": "1.0"})
    assert invalid["status"] == "rejected", invalid
    # Difficulty 0.9 and quantity 2t are synthetic inputs; base labor and
    # the H-shape multiplier are computed by the existing 1-1-1 calculator.
    print("PASS 원문 p.569 공식·참조절·범위·ton당 재료표 대조; 합성 현장입력 표시")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
