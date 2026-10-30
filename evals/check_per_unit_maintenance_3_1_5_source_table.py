"""Rebuild and verify 3-1-5's lost table, mixed quantity units and source gates."""
import hashlib,itertools,json,sys
from fractions import Fraction
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table
PATH=ROOT/"data/drafts/specs/유지관리/3-1-5.json"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE=ROOT/"evals/runtime_validation/source-p969-3-1-5.png"
OUT=ROOT/"evals/runtime_validation/per-unit-maintenance-3-1-5-source-table-2026-10-19.json"
EXPECTED={
 "메쌓기 뒷길이 45∼60㎝":("㎡",("-","0.2")),
 "메쌓기 뒷길이 60∼90㎝":("㎡",("-","0.3")),
 "찰쌓기":("㎡",("-","0.6")),
 "절석 (마름돌) 쌓기":("㎥",("0.1","1.1")),
}
TRADES=("할석공","보통인부"); COLUMNS=("할석공(인)","보통인부(인)")
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(PATH.read_text(encoding="utf8"))["draft"];table=next(t for t in spec["tables"] if t["id"]=="p969-t0")
 cells=[]
 for row,(unit,values) in EXPECTED.items():
  assert row in table["values"]
  for col,value in zip(COLUMNS,values):
   assert table["values"][row][col]==value,(row,col,table["values"][row][col],value)
   c=cite_table("p969-t0",row,col,value)
   assert c.get("value")==value and c.get("pdf_page")==969 and c.get("printed_page")==913,c
   cells.append({"row":row,"column":col,"value":value,"quantity_unit":unit})
 assert len(cells)==8
 doc=pymupdf.open(PDF);page=doc[968];text=page.get_text("text")
 for token in ("3-1-5","45∼60㎝","60∼90㎝","0.2","0.3","0.6","0.1","1.1","3.6m","5%이내"):
  assert token in text,token
 routes=[]
 for work,(unit,values) in EXPECTED.items():
  inp={"work_type":work,"quantity":"2","height":"3.6","reuse_generated":False,"in_place_leveling":False}
  got=per_unit(spec,inp);assert got.get("status")=="computed",(inp,got)
  lines={x["name"]:x for x in got["unit_lines"]}
  has_stonemason=values[0]!="-"
  assert set(lines)==({"할석공","보통인부"} if has_stonemason else {"보통인부"})
  for trade,col,value in zip(TRADES,COLUMNS,values):
   if value=="-":
    continue
   assert Fraction(lines[trade]["exact"])==Fraction(value)
   citation=lines[trade]["citations"][0]
   assert citation.get("row")==work and citation.get("column")==col and citation.get("value")==value
  assert all(x["unit"].endswith(f"/{unit}") for x in lines.values())
  routes.append({"work_type":work,"quantity":"2","source_quantity_unit":unit,"status":"computed",
                 "unit_rates":{k:v["exact"] for k,v in lines.items()},"source_exclusions":[x["trade"] for x in got.get("excluded_resources",[])]})
 # Source-exact restrictions: the 3.6m baseline is inclusive; any special case is blocked.
 states={"computed":0,"blocked":0}
 for work in EXPECTED:
  for height,reuse,level in itertools.product(("3.6","3.61"),(False,True),(False,True)):
   got=per_unit(spec,{"work_type":work,"quantity":"1","height":height,"reuse_generated":reuse,"in_place_leveling":level})
   expected="computed" if height=="3.6" and not reuse and not level else "blocked"
   assert got.get("status")==expected,(work,height,reuse,level,got)
   states[expected]+=1
 audit={"id":spec["id"],"status":"original_sparse_table_and_mixed_unit_routes_verified",
  "source":{"physical_page":969,"printed_page":913,"visual_image":str(IMAGE.relative_to(ROOT)),"pdf_sha256":sha(PDF),"image_sha256":sha(IMAGE),"unique_cells_checked":len(cells),"cells":cells,
            "layout":"Visual source comparison restored four task rows, m²/m³ denominators, three explicit stoneworker dashes and five numerical labor rates. Source states 3.6m baseline, special work separate, and miscellaneous materials within 5% without selecting a rate."},
  "runtime":{"exact_work_type_routes":len(routes),"routes":routes,"preflight_combinations":32,"preflight_statuses":states},
  "open_source_policy":{"miscellaneous_materials":"Not applied: source only states within 5%; no fixed rate selected. Kept in not_calculated for review."},
  "scope":"Eight unique cells and all four task types; exact task-dependent area/volume units; 32 height/reuse/leveling combinations with 4 computed base routes and 28 source-policy blocks.",
  "spec_sha256":sha(PATH),"per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
 OUT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"cells":len(cells),"routes":len(routes),"preflight":states,"audit":str(OUT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__":main()
