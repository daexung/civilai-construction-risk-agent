"""Source-derived vertical and horizontal acoustic-barrier daily rate checks."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
def spec(tid):
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")==tid for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); return json.loads(p.read_text(encoding="utf-8"))["draft"]
def main():
 pdf=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))); p98=re.sub(r"\s+","",pdf.pages[97].extract_text() or ""); p99=re.sub(r"\s+","",pdf.pages[98].extract_text() or "")
 for n in ("120","300","100","260","90","230"): assert n in p98
 for n in ("50","120","40","105","35","90"): assert n in p99
 cases={"p98-t2":[("120","300"),("100","260"),("90","230")],"p99-t0":[("50","120"),("40","105"),("35","90")]}
 for tid,rows in cases.items():
  s=spec(tid); f={x["name"]:x for x in s["inputs"]}; heights=f["height"]["allowed_values"]; works=f["work_type"]["allowed_values"]; trades=s["quantity_model"]["params"]["crew"]["trades"]
  for height,(install,remove) in zip(heights,rows):
   for work,rate in zip(works,(install,remove)):
    for multiplier in (1,2):
     r=adjusted_daily_crew(s,{"height":height,"work_type":work,"quantity":str(int(rate)*multiplier)},labor_only=True); assert r["status"]=="computed",r
     assert r["daily_volume_m3"]==rate and Fraction(r["work_days"])==multiplier
     assert sorted(r["person_days"].values())==sorted([str(3*multiplier),str(multiplier)])
     if tid=="p99-t0":
      equipment_name=s["quantity_model"]["params"]["equipment"]["name"]; assert r["equipment_days"]=={equipment_name:str(multiplier)}
     assert any(c.get("value")==rate for c in r["provenance"]["daily_volume_m3"]["base_output"]["citations"])
  assert adjusted_daily_crew(s,{"height":"outside","work_type":works[0],"quantity":"100"},labor_only=True)["status"]=="rejected"
 print("PASS printed pp.42-43 six height/operation rates per item, source crew, crane days, source citations, and invalid-band rejection")
 return 0
if __name__=="__main__": raise SystemExit(main())
