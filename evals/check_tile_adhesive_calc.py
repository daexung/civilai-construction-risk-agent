"""Source-derived verification for organic tile adhesive setting."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]
source = re.sub(r"\s+", "", PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[642].extract_text() or "")
assert all(s in source for s in ("25", "26", "28", "20%", "26~33%", "벽면", "3%"))
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "3-2-3.json"))
         if any(t.get("id") == "p643-t0" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
fields = {x["name"]: x for x in d["inputs"]}
ordinary, mosaic, special, shaped = fields["tile_type"]["allowed_values"]
base = {"tile_size": fields["tile_size"]["allowed_values"][0], "quantity": "100"}
normal = adjusted_daily_crew(d, {**base, "tile_type": ordinary})
assert normal["status"] == "computed", normal
assert Fraction(normal["work_days"]) == 4
assert {k: Fraction(v) for k, v in normal["person_days"].items()} == {"타일공": 8, "보통인부": 4}
reduced = adjusted_daily_crew(d, {**base, "tile_type": mosaic})
assert reduced["status"] == "computed" and Fraction(reduced["daily_volume_m3"]) == 20
special_case = adjusted_daily_crew(d, {**base, "tile_type": special, "special_reduction": "26"})
assert special_case["status"] == "computed" and Fraction(special_case["daily_volume_m3"]) == Fraction(37, 2)
assert adjusted_daily_crew(d, {**base, "tile_type": special, "special_reduction": "34"})["status"] == "blocked"
assert adjusted_daily_crew(d, {**base, "tile_type": shaped})["status"] == "blocked"
assert all(line.get("citations") for line in normal["unit_lines"])
print("PASS source p.587: 25㎡/day, 2+1 crew yield 4 workdays and 8/4 person-days for 100㎡.")
print("PASS mosaic and special reductions; source interval limits and separately-accounted tile condition enforced.")
