"""Source-derived rate checks for 9-1-5 and 9-3-2."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit
ROOT=Path(__file__).resolve().parents[1]
def spec(sec):
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if json.loads(p.read_text(encoding="utf-8"))["draft"]["section_no"]==sec); return json.loads(p.read_text(encoding="utf-8"))["draft"]
def main():
 pdf=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf")))
 p625=re.sub(r"\s+","",pdf.pages[680].extract_text() or ""); p627=re.sub(r"\s+","",pdf.pages[682].extract_text() or "")
 assert "9-1-5" in p625 and "0.14" in p625 and "10" in p625
 assert "9-3-2" in p627 and "0.08" in p627 and "0.03" in p627 and "10m" in p627
 a=spec("9-1-5"); assert a["quantity_model"]["name"]=="per_unit"; r=per_unit(a,{"area":"100"},labor_only=True); assert r["status"]=="computed",r; assert Fraction(r["unit_lines"][0]["exact"])==Fraction("0.014")
 b=spec("9-3-2"); assert b["quantity_model"]["name"]=="per_unit"; r=per_unit(b,{"length":"25"},labor_only=True); assert r["status"]=="computed",r; got={x["name"]:Fraction(x["exact"]) for x in r["unit_lines"]}; assert sorted(got.values())==sorted([Fraction("0.008"),Fraction("0.003")])
 assert per_unit(a,{"area":"0"},labor_only=True)["status"]!="computed"; assert per_unit(b,{"length":"0"},labor_only=True)["status"]!="computed"
 assert all(line.get("citations") for line in r["unit_lines"])
 print("PASS source p.625 9-1-5: 100 m2: 0.014 person-days/m2; p.627 9-3-2: 25m: rates 0.008/0.003 person-days/m; zero quantities rejected")
 return 0
if __name__=="__main__": raise SystemExit(main())
