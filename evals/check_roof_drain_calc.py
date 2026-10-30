"""Source-derived labor and applicability checks for loop drains."""
from __future__ import annotations
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
pdf=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf")))
text=pdf.pages[670].extract_text() or ""
compact=re.sub(r"\s+","",text)
assert all(token in compact for token in ("0.17","0.04","100","150","2%"))
p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json")
       if any(t.get("id")=="p671-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"].get("tables",[])))
d=json.loads(p.read_text(encoding="utf-8"))["draft"]
for diameter in ("100","150"):
 out=per_unit(d,{"quantity":"10","drain_diameter":diameter})
 assert out["status"]=="computed",out
 lines={line["name"]:line for line in out["unit_lines"]}
 trades=d["quantity_model"]["params"]["unit_rate_table"]["trades"]
 assert Fraction(lines[trades[0]]["exact"])*10==Fraction(17,10)
 assert Fraction(lines[trades[1]]["exact"])*10==Fraction(2,5)
 assert all(line["citations"] for line in out["unit_lines"])
for diameter in ("99","151"):
 assert per_unit(d,{"quantity":"10","drain_diameter":diameter})["status"]=="blocked"
assert d["cost_rules"][0]["base"]=="material_subtotal"
print("PASS source p.615: 0.17/0.04 labor per location yields 1.7/0.4 person-days for 10 drains.")
print("PASS 100-150mm boundaries and source exclusion; material cost percentage retains its material-cost basis.")
