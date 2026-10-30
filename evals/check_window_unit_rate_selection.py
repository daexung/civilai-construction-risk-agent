"""Regression checks for separated/stacked window table selectors."""
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
wood_text = re.sub(r"\s+", "", reader.pages[684].extract_text() or "")
vinyl_text = re.sub(r"\s+", "", reader.pages[685].extract_text() or "")
assert all(x in wood_text for x in ("0.261", "0.056", "0.248", "0.054", "0.010", "문선"))
assert all(x in vinyl_text for x in ("0.169", "0.037", "0.210", "0.046", "미서기"))

def spec_for(section: str, table_id: str) -> dict:
    path = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / f"{section}.json"))
                if any(t.get("id") == table_id for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
    return json.loads(Path(path).read_text(encoding="utf-8"))["draft"]

wood = spec_for("10-1-1", "p685-t0")
wf = {x["name"]: x for x in wood["inputs"]}
base = {"window_type": wf["window_type"]["allowed_values"][0], "area": wf["area"]["allowed_values"][0],
        "quantity": "2", "has_architrave": False}
result = per_unit(wood, base)
assert result["status"] == "computed", result
rates = {x["name"]: Fraction(x["exact"]) * 2 for x in result["unit_lines"] if x["kind"] == "labor"}
assert rates == {"창호공": Fraction(261, 500), "보통인부": Fraction(28, 250)}
with_architrave = per_unit(wood, {**base, "has_architrave": True, "architrave_length": "5"})
assert with_architrave["status"] == "computed", with_architrave
extra = next(x for x in with_architrave["unit_lines"] if x["kind"] == "labor" and x["name"] == "창호공" and x["unit"] == "인/m")
assert Fraction(extra["exact"]) == Fraction(1, 100)

vinyl = spec_for("10-1-5", "p686-t1")
vf = {x["name"]: x for x in vinyl["inputs"]}
vinputs = {"window_style": vf["window_style"]["allowed_values"][0], "window_type": vf["window_type"]["allowed_values"][0],
           "area_band": vf["area_band"]["allowed_values"][1], "quantity": "3"}
vr = per_unit(vinyl, vinputs)
assert vr["status"] == "computed", vr
vrates = {x["name"]: Fraction(x["exact"]) * 3 for x in vr["unit_lines"] if x["kind"] == "labor"}
assert vrates == {"창호공": Fraction(63, 100), "보통인부": Fraction(69, 500)}
assert per_unit(vinyl, {**vinputs, "window_style": vf["window_style"]["allowed_values"][-1]})["status"] == "blocked"
assert all(x["citations"] for x in result["unit_lines"] + vr["unit_lines"])
print("PASS source p.629-630: wood sliding-single row mapping, per-size column, and 0.010 person-day/m architrave rate.")
print("PASS source vinyl size bands normalize ∼/~/line wraps without changing selected rate cells.")
