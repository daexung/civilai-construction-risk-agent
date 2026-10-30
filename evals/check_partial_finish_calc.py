"""Source-derived daily crew checks for 9-2-2 partial concrete finish."""
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json") if json.loads(p.read_text(encoding="utf-8"))["draft"]["section_no"]=="9-2-2"); spec=json.loads(p.read_text(encoding="utf-8"))["draft"]; f={x["name"]:x for x in spec["inputs"]}; h=f["height_band"]["allowed_values"]
 source=re.sub(r"\s+","",PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[680].extract_text() or "")
 assert "9-2-2" in source and "170" in source and "155" in source and "17%" in source
 base={"volume":"170","height_band":h[0],"is_ceiling":False,"scaffold_used":False}
 low=adjusted_daily_crew(spec,base,labor_only=True); assert low["status"]=="computed" and low["daily_volume_m3"]=="170" and sorted(low["person_days"].values())==["1","2"]
 ceiling=adjusted_daily_crew(spec,{**base,"volume":"100","is_ceiling":True},labor_only=True); assert ceiling["status"]=="computed" and ceiling["daily_volume_m3"]=="141.1" and "17%" in ceiling["provenance"]["daily_volume_m3"]["output_adjustments"][0]["citations"][0]["quote"]
 med=adjusted_daily_crew(spec,{**base,"height_band":h[1],"volume":"155"},labor_only=True); assert med["status"]=="computed" and med["daily_volume_m3"]=="155" and sorted(med["person_days"].values())==["2","2"]
 high=adjusted_daily_crew(spec,{**base,"height_band":h[2]},labor_only=True); assert high["status"]=="blocked",high
 print("PASS p.625 source 170/155 m2 daily output, 2/1 and 2/2 crew, 17% ceiling deduction, >7.2m outside-table block")
 return 0
if __name__=="__main__": raise SystemExit(main())
