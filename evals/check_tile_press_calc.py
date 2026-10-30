"""Source-derived verification for compression tile setting."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]
source = re.sub(r"\s+", "", PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[641].extract_text() or "")
assert all(s in source for s in ("18", "15", "21", "16", "22", "20%", "26~33%", "0.005", "0.008", "3%"))
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "3-2-2.json"))
         if any(t.get("id") == "p642-t1" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
fields = {x["name"]: x for x in d["inputs"]}
size = fields["tile_size"]["allowed_values"][0]
surface = fields["surface_type"]["allowed_values"][0]
thickness = fields["thickness"]["allowed_values"][0]
ordinary, mosaic_name, special_name = fields["tile_type"]["allowed_values"]
regular_shape, excluded_shape = fields["tile_shape"]["allowed_values"]
base = {"tile_size": size, "surface_type": surface, "tile_shape": regular_shape, "quantity": "100", "thickness": thickness}
normal = adjusted_daily_crew(d, {**base, "tile_type": ordinary})
assert normal["status"] == "computed", normal
assert Fraction(normal["work_days"]) == Fraction(100, 18)
assert {k: Fraction(v) for k, v in normal["person_days"].items()} == {"타일공": Fraction(100, 9), "보통인부": Fraction(50, 9)}
mortar = next(x for x in normal["unit_lines"] if x["kind"] == "material")
assert Fraction(mortar["exact"]) == Fraction(1, 2) and mortar["unit"] == "m3"
mosaic = adjusted_daily_crew(d, {**base, "tile_type": mosaic_name, "special_reduction": "26"})
assert mosaic["status"] == "computed" and Fraction(mosaic["daily_volume_m3"]) == Fraction(72, 5)
special = adjusted_daily_crew(d, {**base, "tile_type": special_name, "special_reduction": "26"})
assert special["status"] == "computed" and Fraction(special["daily_volume_m3"]) == Fraction(333, 25)
assert adjusted_daily_crew(d, {**base, "tile_type": special_name, "special_reduction": "25"})["status"] == "blocked"
assert adjusted_daily_crew(d, {**base, "tile_type": special_name, "special_reduction": "34"})["status"] == "blocked"
assert adjusted_daily_crew(d, {**base, "tile_type": ordinary, "tile_shape": excluded_shape})["status"] == "blocked"
assert all(line.get("citations") for line in normal["unit_lines"])
print("PASS source p.586: 18㎡/day, 2+1 crew and 0.005㎥/㎡ produce independent 100㎡ benchmark.")
print("PASS source adjustments: mosaic 20%; special reduction 26-33% user-selected; out-of-range and separately-accounted tile block.")
