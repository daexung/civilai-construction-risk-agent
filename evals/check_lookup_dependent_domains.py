"""PDF-transcribed source check for a lookup with dependent table axes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.lookup import lookup  # noqa: E402


def main() -> int:
    package = json.loads((ROOT / "data/drafts/specs/건축/1-2-3.json").read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(row for row in spec["tables"] if row["id"] == "p629-t0")

    # Independently transcribed from the page-573 PDF image, table 1-2-3.
    expected = {
        ("크레인 (무한궤도/타이어)", "창고소규모건물,"): "15",
        ("크레인 (무한궤도/타이어)", "공장대규모건물,"): "15",
        ("크레인 (무한궤도/타이어)", "트러스, 거더류"): "15",
        ("크레인 (무한궤도/타이어)", "기둥, 크레인거더"): "25",
        ("크레인 (무한궤도/타이어)", "기타"): "8",
        ("타워크레인 트럭탑재형크레인", "고층건물"): "15",
        ("타워크레인 트럭탑재형크레인", "소규모건물"): "10",
        ("굴착기", "탑다운공법 지하 거더류"): "12",
    }
    first = lookup(spec, {})
    assert first["status"] == "ask", first
    equipment_q = first["questions"][0]
    assert equipment_q["name"] == "equipment_type", equipment_q
    assert set(equipment_q["allowed_values"]) == {equipment for equipment, _ in expected}, equipment_q

    checked = 0
    for equipment in equipment_q["allowed_values"]:
        second = lookup(spec, {"equipment_type": equipment})
        assert second["status"] == "ask", (equipment, second)
        q = second["questions"][0]
        assert q["name"] == "building_type", (equipment, q)
        expected_options = {building for (kind, building) in expected if kind == equipment}
        assert set(q["allowed_values"]) == expected_options, (equipment, q, expected_options)
        for building in q["allowed_values"]:
            result = lookup(spec, {"equipment_type": equipment, "building_type": building})
            value = expected[(equipment, building)]
            assert result["status"] == "computed", (equipment, building, result)
            assert result["value"] == value == table["values"][equipment][building]
            assert result["unit"] == table["unit"] == "ton/일"
            citation = result["provenance"]["citations"][0]
            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"],
                    citation["pdf_page"], citation["printed_page"]) == (
                        "p629-t0", equipment, building, value, 629, 573)
            checked += 1

    impossible = lookup(spec, {"equipment_type": "굴착기", "building_type": "기타"})
    assert impossible["status"] == "unresolvable", impossible
    assert checked == len(expected) == 8
    print("PASS PDF p.573 dependent lookup: 8/8 source cells, units and citations; impossible pair not computed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
