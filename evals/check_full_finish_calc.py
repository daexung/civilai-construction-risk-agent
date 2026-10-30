"""Source-derived 9-2-3 daily labor and scope checks."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if json.loads(p.read_text(encoding="utf-8"))["draft"]["section_no"]=="9-2-3"); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]
 src=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[681].extract_text() or "")
 for value in ("120","115","17%","14.3","22.7"): assert value in src
 base={"height_m":"3.6","area":"120","is_ceiling":False,"scaffold_used":False}
 low=adjusted_daily_crew(spec,base,labor_only=True); assert low["status"]=="computed" and low["daily_volume_m3"]=="120" and sorted(low["person_days"].values())==["1","2"]
 ceiling=adjusted_daily_crew(spec,{**base,"is_ceiling":True},labor_only=True); assert ceiling["status"]=="computed" and ceiling["daily_volume_m3"]=="99.6" and sorted(ceiling["person_days"].values())==["100/83","200/83"]
 mid=adjusted_daily_crew(spec,{**base,"height_m":"3.61","area":"115"},labor_only=True); assert mid["status"]=="computed" and mid["daily_volume_m3"]=="115" and sorted(mid["person_days"].values())==["2","2"]
 high=adjusted_daily_crew(spec,{**base,"height_m":"7.21"},labor_only=True); assert high["status"]=="blocked",high
 assert spec["not_calculated"] and "denominator" in spec["not_calculated"][0]["reason"]
 cites=ceiling["provenance"]["daily_volume_m3"]["output_adjustments"][0]["citations"]; assert cites and cites[0]["quote"] and "17%" in cites[0]["quote"]
 print("PASS p.626 source 120/115 m2 daily output, crew values, 17% ceiling deduction and note citation, >7.2m block; reference material denominator remains unstated and excluded from material totals")
 return 0
if __name__=="__main__": raise SystemExit(main())
