"""Source-derived area-per-hour to machine-hours calculation."""
import copy,json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.formula import formula_quantity
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")=="p141-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[140].extract_text() or "")
 for token in ("3-10-1","281","404","526","648","771"): assert token in src,token
 rows=spec["tables"][0]["values"]; fields={x["name"]:x for x in spec["inputs"]}; bands=fields["block_size"]["allowed_values"]; rates=["281","404","526","648","771"]
 for band,rate in zip(bands,rates):
  for multiplier,expected in ((1,Fraction(1)),(2,Fraction(2))):
   r=formula_quantity(spec,{"block_size":band,"quantity":str(int(rate)*multiplier),"water_retention":False}); assert r["status"]=="computed",r
   line=r["unit_lines"][0]; assert Fraction(line["exact"])==expected and line["unit"]=="hr"
   assert any(c["value"]==rate for c in line["citations"])
 assert formula_quantity(spec,{"block_size":bands[0],"quantity":"100","water_retention":True})["status"]=="blocked"
 wrong=copy.deepcopy(spec); next(x for x in wrong["inputs"] if x["name"]=="quantity")["unit"]="m"; assert formula_quantity(wrong,{"block_size":bands[0],"quantity":"100","water_retention":False})["status"]=="unresolvable"
 assert formula_quantity(spec,{"block_size":bands[0],"quantity":"0","water_retention":False})["status"]=="rejected"
 print("PASS p.85 all five source productivity bands; area/rate yields equipment-hours; water-retention labor and incompatible units fail closed")
 return 0
if __name__=="__main__": raise SystemExit(main())
