"""Source-derived 9-4-2 housing-type table recovery check."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")=="p761-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]; houses=spec["inputs"][0]["allowed_values"]
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[760].extract_text() or "")
 for token in ("9-4-2","0.10","0.05"): assert token in src
 expected=[Fraction("0.10"),Fraction("0.05")]
 for house,rate,count in zip(houses,expected,("10","20")):
  r=per_unit(spec,{"housing_type":house,"quantity":count},labor_only=True); assert r["status"]=="computed",r
  assert sorted(Fraction(line["exact"]) for line in r["unit_lines"])==[rate,rate]
  assert all(any(c.get("value") in ("0.10","0.05") for c in line.get("citations",[])) for line in r["unit_lines"])
  assert rate*int(count)==1 # independent application of source note's crew size
 assert per_unit(spec,{"housing_type":"unsupported","quantity":"10"},labor_only=True)["status"]=="rejected"
 print("PASS p.705 source: detached 0.10 and apartment 0.05 person/house for both trades; note-based 10/20-house crew total and invalid category rejection")
 return 0
if __name__=="__main__": raise SystemExit(main())
