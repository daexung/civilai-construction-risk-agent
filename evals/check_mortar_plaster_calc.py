"""Source-derived 9-1-2 mortar-plaster calculation and scope checks."""
from __future__ import annotations
import json, re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
def main():
    package=json.loads(next((ROOT/"data/drafts/specs").rglob("9-1-2.json")).read_text(encoding="utf-8")); spec=package["draft"]
    assert package["calc_type"]=="daily_crew"
    fields={f["name"]:f for f in spec["inputs"]}; heights=fields["height"]["allowed_values"]; coats=fields["coats"]["allowed_values"]; mortar=fields["mortar_type"]["allowed_values"]
    source_path=next((ROOT/"data/raw/standard_estimation").glob("*.pdf")); text=PdfReader(source_path).pages[678].extract_text() or ""; compact=re.sub(r"\s+","",text)
    for value in ("40","29","20","37","27","19","17%"): assert value in compact, value
    base={"height":heights[0],"coats":coats[0],"area":"100","narrow_or_column":False,"scaffold_used":False,"thickness_under_24mm":True,"mortar_type":mortar[0],"extra_scaffold_lifts":0}
    low=adjusted_daily_crew(spec,base,labor_only=True); assert low["status"]=="computed" and low["daily_volume_m3"]=="40" and low["work_days"]=="2.5"
    assert sorted(low["person_days"].values())==["2.5","5"]
    mid=adjusted_daily_crew(spec,{**base,"height":heights[1],"coats":coats[1],"narrow_or_column":True},labor_only=True)
    assert mid["status"]=="computed" and mid["daily_volume_m3"]=="22.41" and Fraction(mid["work_days"])==Fraction(100,1)/Fraction("22.41")
    assert sorted(mid["person_days"].values())==["20000/2241","20000/2241"]
    high=adjusted_daily_crew(spec,{**base,"height":heights[2],"scaffold_used":True,"extra_scaffold_lifts":2},labor_only=True)
    assert high["status"]=="computed" and high["daily_volume_m3"]=="34.78" # source mid-height 37 x (1 - 2*3%)
    adjustment_cites=[c for a in high["provenance"]["daily_volume_m3"]["output_adjustments"] for c in a["citations"]]
    note_row=next(k for k,v in spec["tables"][0]["values"].items() if any("17%" in str(z) for z in v.values()))
    assert adjustment_cites and all(c["row"]==note_row and c["column"]==note_row for c in adjustment_cites)
    for invalid in ({**base,"thickness_under_24mm":False},{**base,"mortar_type":mortar[1]}): assert adjusted_daily_crew(spec,invalid,labor_only=True)["status"]=="blocked"
    inactive=adjusted_daily_crew(spec,{**base,"extra_scaffold_lifts":-1},labor_only=True); assert inactive["status"]!="computed"
    print("PASS 9-1-2 source table rates/crew, 17% narrow-surface adjustment, scaffold count adjustment, source citations, thickness and mortar-scope blocks")
    return 0
if __name__=="__main__": raise SystemExit(main())
