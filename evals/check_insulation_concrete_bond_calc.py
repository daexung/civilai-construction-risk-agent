"""Source-derived checks for concrete-cast insulation attachment."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]
reader = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
table_text = re.sub(r"\s+", "", reader.pages[655].extract_text() or "")
material_text = re.sub(r"\s+", "", reader.pages[656].extract_text() or "")
assert all(s in table_text for s in ("50이하", "75", "100이하", "70", "200이하", "65", "300이하", "60"))
assert "1.1" in material_text and "2%" in material_text and "1겹" in material_text
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "5-4-6.json"))
         if any(t.get("id") == "p656-t3" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
fields = {x["name"]: x for x in d["inputs"]}
result = adjusted_daily_crew(d, {"thickness": fields["thickness"]["allowed_values"][0], "quantity": "100",
                                 "insulation_type": fields["insulation_type"]["allowed_values"][0], "layers": 1})
assert result["status"] == "computed", result
assert Fraction(result["work_days"]) == Fraction(4, 3)
assert {k: Fraction(v) for k, v in result["person_days"].items()} == {"내장공": Fraction(8, 3), "보통인부": Fraction(4, 3)}
material = next(x for x in result["unit_lines"] if x["kind"] == "material")
assert Fraction(material["exact"]) == 110 and material["unit"] == "m2"
assert adjusted_daily_crew(d, {"thickness": fields["thickness"]["allowed_values"][0], "quantity": "100",
                               "insulation_type": fields["insulation_type"]["allowed_values"][-1], "layers": 1})["status"] == "blocked"
assert adjusted_daily_crew(d, {"thickness": fields["thickness"]["allowed_values"][0], "quantity": "100",
                               "insulation_type": fields["insulation_type"]["allowed_values"][0], "layers": 2})["status"] == "blocked"
print("PASS source p.600-601: 75㎡/day and 2+1 crew yield 4/3 workdays and 8/3, 4/3 person-days for 100㎡; material 110㎡.")
print("PASS specified insulation types and single-layer scope; invalid source scope/conditions are blocked.")
