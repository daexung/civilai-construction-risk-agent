"""Source-based quantity validation for pressing metal installation."""
from __future__ import annotations
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
text=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[659].extract_text() or ""
compact=re.sub(r"\s+","",text)
assert compact.count("0.011")==2
p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json")
       if any(t.get("id")=="p660-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"].get("tables",[])))
d=json.loads(p.read_text(encoding="utf-8"))["draft"]
out=per_unit(d,{"quantity":"10","sheet_or_protection_layer":True})
assert out["status"]=="computed",out
assert [Fraction(x["exact"])*10 for x in out["unit_lines"]]==[Fraction(11,100),Fraction(11,100)]
assert all(x["citations"] for x in out["unit_lines"])
assert per_unit(d,{"quantity":"10","sheet_or_protection_layer":False})["status"]=="blocked"
print("PASS source p.604: each trade is 0.011 person-day/m; 10m yields 0.11 each.")
print("PASS the source surface scope is enforced and both table cells are cited.")
