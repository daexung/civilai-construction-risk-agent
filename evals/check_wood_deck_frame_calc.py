"""Source-derived checks for wood deck frame daily-crew calculation."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]
pdf = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
source = re.sub(r"\s+", "", pdf.pages[647].extract_text() or "")
assert all(token in source for token in ("0.40", "0.32", "4%", "H-Beam", "\uac01\uad00", "\ud3c9\uad6c\uc870", "\uacc4\ub2e8\uad6c\uc870"))

path = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "4-3-3.json"))
            if any(t.get("id") == "p648-t0" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
spec = json.loads(Path(path).read_text(encoding="utf-8"))["draft"]
cases = {
    "\ud3c9\uad6c\uc870": {"\ucca0\uacf5": Fraction(75), "\uc6a9\uc811\uacf5": Fraction(25), "\ubcf4\ud1b5\uc778\ubd80": Fraction(25)},
    "\uacc4\ub2e8\uad6c\uc870": {"\ucca0\uacf5": Fraction(125), "\uc6a9\uc811\uacf5": Fraction(125, 4), "\ubcf4\ud1b5\uc778\ubd80": Fraction(125, 2)},
}
for structure, expected in cases.items():
    result = adjusted_daily_crew(spec, {"structure_type": structure, "quantity": "10", "deck_frame_scope": "\uac01\uad00\ubc0f\ud615\uac15"})
    assert result["status"] == "computed", result
    assert {k: Fraction(v) for k, v in result["person_days"].items()} == expected, result["person_days"]
    assert all(v["citations"] for v in result["provenance"]["person_days"].values())
assert adjusted_daily_crew(spec, {"structure_type": "\ud3c9\uad6c\uc870", "quantity": "10", "deck_frame_scope": "H-Beam\ub4f1\ucca0\uace8\ub958"})["status"] == "blocked"
assert spec["not_calculated"][0]["item"] == "\uae30\ucd08\ucf58\ud06c\ub9ac\ud2b8 \uc124\uce58"
assert spec["cost_rules"][0]["rate"] == "0.04" and spec["cost_rules"][0]["base"] == "labor_subtotal"
print("PASS source p.592: 0.40/0.32 ton/day and crew rates reproduce flat/stair person-days for 10t.")
print("PASS H-Beam exclusion blocks; foundation concrete is separately accounted; 4% cost rule retained.")
