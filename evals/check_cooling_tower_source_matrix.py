"""Independent PDF grid and full route checks for cooling-tower installation."""
import json,sys
from fractions import Fraction
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC=ROOT/"data/drafts/specs/기계설비/8-1-3.json"
PAGES={"2층건물":746,"5층건물":747,"9층건물":748}; CAPS=["5","10","20","30","50","80","100","150","200","300","400","500","600"]
LOCS=["1회 옥상","1회 탑옥1층","1회 탑옥3층","2회 탑옥1층","2회 탑옥3층"]; TRADES=["비계공","특별인부"]
def main():
 doc=fitz.open(PDF); pkg=json.loads(SPEC.read_text(encoding="utf8")); spec=pkg["draft"]; checked=paths=0
 for floor,page in PAGES.items():
  extracted=doc[page-1].find_tables().tables[0].extract(); table=next(t for t in spec["tables"] if t["id"]==f"p{page}-t0")
  for i,cap in enumerate(CAPS):
   p_row,s_row=extracted[2+i*2],extracted[3+i*2]; key=f"구분 {cap}"
   assert p_row[0]==cap and p_row[1]=="비계공\n특별인부" and s_row[0] is None and s_row[1] is None
   for j,loc in enumerate(LOCS):
    for trade,source_row in zip(TRADES,(p_row,s_row)):
     col=f"{trade} {loc}"; expected=str(source_row[j+2]).strip(); checked+=1
     assert table["values"][key][col]==expected,(floor,key,col,table["values"][key].get(col),expected)
  # Check every usable source cell through the real per-unit runtime route.
  for cap in CAPS:
   for loc in LOCS:
    result=per_unit(spec,{"building_floors":floor,"capacity":cap,"install_location":loc,"quantity":"1"})
    expected=[table["values"][f"구분 {cap}"][f"{trade} {loc}"] for trade in TRADES]
    actual=[line["exact"] for line in result.get("unit_lines",[])]
    assert result["status"]=="computed" and actual==[str(Fraction(x)) for x in expected],(floor,cap,loc,result.get("status"),actual,expected)
    for line in result["unit_lines"]:
     c=line["citations"][0]; trade=line["name"]; raw=table["values"][f"구분 {cap}"][f"{trade} {loc}"]
     assert (c["internal_id"],c["row"],c["column"],c["value"])==(f"p{page}-t0",f"구분 {cap}",f"{trade} {loc}",raw)
    paths+=1
 chunks=load_chunks(ROOT/"data/processed/chunks.all.jsonl"); v=validate_one(SPEC,ROOT/"data/drafts",chunks,file_sha256(ROOT/"data/processed/chunks.all.jsonl")); assert not v["format_issues"] and not v["citation_issues"],v
 print(json.dumps({"status":"pass","source_tables":3,"pdf_cells_compared":checked,"exact_runtime_routes":paths,"citation_preflight":"pass","cells_per_page":130,"source_grid":"visually reviewed printed pages 690-692 and parsed as 7-column paired-trade table","unit_basis":"인/대 remains an explicit inference; see open question","all_rule_verification":False},ensure_ascii=False))
if __name__=="__main__": main()
