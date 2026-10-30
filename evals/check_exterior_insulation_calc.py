"""Source-based checks for exterior-wall insulation labor and materials."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit

ROOT = Path(__file__).resolve().parents[1]
reader = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
source = re.sub(r"\s+", "", reader.pages[657].extract_text() or "")
assert all(s in source for s in ("0.060", "0.063", "0.081", "0.038", "0.052", "0.031", "0.042", "0.076", "0.025", "1.10", "3.84", "1.60", "1.44", "1.21", "4층이하", "1%"))
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "5-4-9.json"))
         if any(t.get("id") == "p658-t1" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
fields = {x["name"]: x for x in d["inputs"]}
inputs = {"area": "100", "bottom_reinforcement": False, "thickness": fields["thickness"]["allowed_values"][0], "floor_count": 4, "fire_spread_prevention_structure": True}
base = per_unit(d, inputs)
assert base["status"] == "computed", base
base_labor = {x["name"]: Fraction(x["exact"]) * 100 for x in base["unit_lines"] if x["kind"] == "labor"}
assert base_labor == {"내장공": 6, "미장공": Fraction(19, 5), "보통인부": Fraction(31, 10)}
base_material = {x["name"]: Fraction(x["exact"]) * 100 for x in base["unit_lines"] if x["kind"] == "material"}
assert base_material == {"단열판": 110, "접착제": 384, "시멘트": 384, "표준보강메시": 144}
reinforced = per_unit(d, {**inputs, "bottom_reinforcement": True})
assert reinforced["status"] == "computed", reinforced
labor = {}
for x in reinforced["unit_lines"]:
    if x["kind"] == "labor": labor[x["name"]] = labor.get(x["name"], Fraction(0)) + Fraction(x["exact"]) * 100
assert labor == {"내장공": 6, "미장공": Fraction(57, 5), "보통인부": Fraction(28, 5)}
materials = {}
for x in reinforced["unit_lines"]:
    if x["kind"] == "material": materials[x["name"]] = materials.get(x["name"], Fraction(0)) + Fraction(x["exact"]) * 100
assert materials == {"단열판": 110, "접착제": 544, "시멘트": 544, "표준보강메시": 144, "고강도메시": 121}
assert per_unit(d, {**inputs, "floor_count": 5})["status"] == "blocked"
assert per_unit(d, {**inputs, "fire_spread_prevention_structure": False})["status"] == "blocked"
print("PASS source p.602: 100㎡ base labor and external-wall material coefficients match independent multiplication.")
print("PASS optional lower reinforcement adds separate labor/material rows; >4 stories and out-of-scope work are blocked.")
