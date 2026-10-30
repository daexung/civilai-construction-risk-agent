"""Original-table numeric, unit and applicability validation for roof joints."""
from __future__ import annotations
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
source=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[664].extract_text() or ""
compact=re.sub(r"\s+","",source)
assert all(token in compact for token in ("0.005","0.001","0.017","320~400","2%"))
def spec_for(table):
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json")
        if any(t.get("id")==table for t in json.loads(p.read_text(encoding="utf-8"))["draft"].get("tables",[])))
 return json.loads(p.read_text(encoding="utf-8"))["draft"]
cut=spec_for("p665-t0");install=spec_for("p665-t1")
for width in ("320","400"):
 out=per_unit(cut,{"quantity":"200","roof_protection_concrete":True,"cutter_width":width})
 assert out["status"]=="computed",out
 rows={line["name"]:line for line in out["unit_lines"]}
 params=cut["quantity_model"]["params"]["unit_rate_table"]
 assert Fraction(rows[params["trades"][0]]["exact"])*200==1
 assert Fraction(rows[params["trades"][1]]["exact"])*200==Fraction(1,5)
 machine=next(line for line in out["unit_lines"] if line["kind"]=="equipment")
 assert Fraction(machine["exact"])*200==Fraction(34,10) and machine["unit"]=="hr/m"
 assert all(line["citations"] for line in out["unit_lines"])
for width in ("319","401"):
 out=per_unit(cut,{"quantity":"200","roof_protection_concrete":True,"cutter_width":width})
 assert out["status"]=="blocked",(width,out)
assert per_unit(cut,{"quantity":"200","roof_protection_concrete":False,"cutter_width":"320"})["status"]=="blocked"
out=per_unit(install,{"quantity":"200","roof_protection_concrete":True})
assert out["status"]=="computed",out
assert [Fraction(line["exact"])*200 for line in out["unit_lines"]]==[Fraction(1),Fraction(1,5)]
assert per_unit(install,{"quantity":"200","roof_protection_concrete":False})["status"]=="blocked"
assert cut["cost_rules"][0]["rate"]=="0.02"
print("PASS source p.609: 0.005/0.001 labor and 0.017 hr per meter produce 1, 0.2 person-day and 3.4 cutter-hours per 200m.")
print("PASS 6-6-3 source crew for 200m: 1 and 0.2 person-day.")
print("PASS 320-400mm and roof-protective-concrete scope; out-of-scope inputs block; 2% tool cost retained.")
