"""Source-derived checks for reinforced concrete block masonry."""
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
text = re.sub(r"\s+", "", (reader.pages[637].extract_text() or "") + (reader.pages[638].extract_text() or ""))
assert all(x in text for x in ("18", "17", "22", "21", "26", "25", "3%", "5%", "2.5hr", "0.027", "0.019", "0.012"))
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "2-2-2.json"))
         if any(t.get("id") == "p638-t2" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
f = {x["name"]: x for x in d["inputs"]}
height, block, finish = f["height"]["allowed_values"], f["block_size"]["allowed_values"], f["finish"]["allowed_values"]
base = {"height": height[0], "block_size": block[0], "finish": finish[0], "sachum_400mm": False,
        "forklift_used": False, "quantity": "100", "scaffold_used": False, "extra_scaffold_lifts": 0}
normal = adjusted_daily_crew(d, base)
assert normal["status"] == "computed", normal
assert Fraction(normal["daily_volume_m3"]) == 18 and Fraction(normal["work_days"]) == Fraction(50, 9)
assert {k: Fraction(v) for k, v in normal["person_days"].items()} == {"조적공": Fraction(50, 3), "보통인부": Fraction(50, 9)}
mortar = next(x for x in normal["unit_lines"] if x["kind"] == "material")
assert Fraction(mortar["exact"]) == Fraction(27, 10) and mortar["unit"] == "㎥"
grouted = adjusted_daily_crew(d, {**base, "sachum_400mm": True})
assert Fraction(grouted["daily_volume_m3"]) == Fraction(171, 10)
forklift = adjusted_daily_crew(d, {**base, "forklift_used": True})
assert forklift["status"] == "computed" and Fraction(forklift["person_days"]["보통인부"]) == 0
assert Fraction(forklift["equipment_days"]["지게차"]) == Fraction(50, 9)
high = adjusted_daily_crew(d, {**base, "height": height[-1], "scaffold_used": True, "extra_scaffold_lifts": 1})
assert high["status"] == "computed" and Fraction(high["daily_volume_m3"]) == Fraction(1649, 100)
assert adjusted_daily_crew(d, {**base, "height": height[-1], "scaffold_used": True, "extra_scaffold_lifts": 0})["status"] == "blocked"
assert adjusted_daily_crew(d, {**base, "extra_scaffold_lifts": 1})["status"] == "blocked"
print("PASS source p.582-583: 18㎡/day, 3+1 crew and 0.027㎥/㎡ reproduce independent 100㎡ values.")
print("PASS 5% grout reduction, forklift helper substitution/2.5hr per workday, and scaffold 3% per 3.6m interval.")
print("PASS missing scaffold interval declaration and interval use outside >7.2m scope are blocked.")
