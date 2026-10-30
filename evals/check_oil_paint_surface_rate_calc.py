"""Source-derived brush and roller paint unit-rate checks."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
def spec(tid):
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")==tid for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); return json.loads(p.read_text(encoding="utf-8"))["draft"]
def main():
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[693].extract_text() or "")
 for token in ("11-2-4","11-2-5","0.020","0.004","0.024","0.011","0.002","0.013","0.003","20%"): assert token in src,token
 expected={"p694-t0":[("0.020","0.004"),("0.024","0.004"),("0.024","0.004")],"p694-t1":[("0.011","0.002"),("0.013","0.003"),("0.013","0.003")]}
 for tid,rows in expected.items():
  s=spec(tid); values=s["tables"][0]["values"]; assert s["quantity_model"]["params"]["unit_rate_table"].get("column_input") is None
  for surface,(painter,helper) in zip(next(x for x in s["inputs"] if x["name"]=="surface_type")["allowed_values"],rows):
   for ceiling,mult in ((False,Fraction(1)),(True,Fraction("1.2"))):
    r=per_unit(s,{"surface_type":surface,"quantity":"100","is_ceiling":ceiling},labor_only=True); assert r["status"]=="computed",r
    result={x["name"]:Fraction(x["exact"]) for x in r["unit_lines"]}; assert sorted(result.values())==sorted([Fraction(painter)*mult,Fraction(helper)*mult])
    if ceiling: assert all(any("20%" in (c.get("quote") or "") for c in x["citations"]) for x in r["unit_lines"])
  assert per_unit(s,{"surface_type":"outside-source","quantity":"10","is_ceiling":False},labor_only=True)["status"]=="rejected"
 print("PASS printed p.638: both paint methods, all three source surface bands, source rates, ceiling +20% and invalid-surface rejection")
 return 0
if __name__=="__main__": raise SystemExit(main())
