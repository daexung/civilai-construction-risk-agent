"""Source-derived 2-11-5 tanker-hour rate and area-basis checks."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")=="p118-t1" for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[117].extract_text() or "")
 for token in ("2-11-5","0.008","30,000"): assert token in src,token
 for water in (False,True):
  r=per_unit(spec,{"spray_area":"30000","water_supply_needed":water},labor_only=True); assert r["status"]=="computed",r
  assert Fraction(r["unit_lines"][0]["exact"])==Fraction("0.008")/100
  assert Fraction(r["unit_lines"][0]["exact"])*30000==Fraction("2.4")
  assert r["unit_lines"][0]["kind"]=="equipment" and r["not_calculated"]
  assert r["unit_lines"][0]["citations"][0]["value"]=="0.008"
 assert per_unit(spec,{"spray_area":"0","water_supply_needed":False},labor_only=True)["status"]!="computed"
 print("PASS printed p.62 source 0.008 hr/100?, cumulative example 30,000? ? 2.4 tanker-hours, separate water-supply cost, invalid-area rejection")
 return 0
if __name__=="__main__": raise SystemExit(main())
