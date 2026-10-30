"""Source-derived labor, material, and explicit dash checks for 2-11-1."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if any(t.get("id")=="p117-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"]["tables"])); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[116].extract_text() or "")
 for token in ("2-11-1","0.003","0.01","0.03","1.10","1.20","0.06","0.007","0.02","100%"): assert token in src,token
 operations=spec["inputs"][0]["allowed_values"]; expected=[(["0.003"],["1.10"]),(["0.01"],["1.20","0.06"]),(["0.03"],["0.007","0.02"])]
 for op,case in zip(operations,expected):
  r=per_unit(spec,{"protection_type":op,"area":"100"},labor_only=True); assert r["status"]=="computed",r
  labor=[Fraction(x["exact"]) for x in r["unit_lines"] if x["kind"]=="labor"]; materials=[Fraction(x["exact"]) for x in r["unit_lines"] if x["kind"]=="material"]
  assert sorted(labor)==sorted(Fraction(v) for v in case[0]); assert sorted(materials)==sorted(Fraction(v) for v in case[1])
  excluded=r["provenance"]["excluded_resources"]; assert excluded and all(c["value"]=="-" for e in excluded for c in e["citations"])
 assert per_unit(spec,{"protection_type":"invalid","area":"100"},labor_only=True)["status"]=="rejected"
 print("PASS p.61 source rates for all three protection types, labor and material unit rates, source 100% loss-rate citation, and '-' preserved as cited resource exclusions")
 return 0
if __name__=="__main__": raise SystemExit(main())
