"""Source and runtime check for resource-in-column matrix 4-1-1."""
import hashlib, json, sys
from fractions import Fraction
from pathlib import Path
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table
PATH=ROOT/"data/drafts/specs/유지관리/4-1-1.json"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE=ROOT/"evals/runtime_validation/source-p977-4-1-1.png"
OUT=ROOT/"evals/runtime_validation/per-unit-maintenance-4-1-1-trade-columns-2026-10-19.json"
TRADES=("배관공","보통인부")
PIPE_TYPES=("강관","동관")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 spec=json.loads(PATH.read_text(encoding="utf8"))["draft"]
 table=next(t for t in spec["tables"] if t["id"]=="p977-t0")
 cells=[]
 for row,cols in table["values"].items():
  for col,raw in cols.items():
   assert raw not in ("","-",None)
   c=cite_table("p977-t0",row,col,raw)
   assert c.get("value")==raw and c.get("pdf_page")==977 and c.get("printed_page")==921,c
   cells.append({"row":row,"column":col,"value":raw})
 assert len(cells)==58
 doc=pymupdf.open(PDF); page=doc[976]; text=page.get_text("text")
 assert "4-1-1" in text and "배관 해체" in text and "ø15이하" in text
 assert all(v in text for v in {x["value"] for x in cells})
 routes=[]
 common_rows=[r for r,c in table["values"].items() if any(k.startswith("동관") for k in c)]
 for pipe in PIPE_TYPES:
  allowed=common_rows if pipe=="동관" else list(table["values"])
  for row in allowed:
   size="ø15이하" if row.startswith("ø") else row
   result=per_unit(spec,{"pipe_type":pipe,"pipe_size":size,"quantity":"1","is_reused":False})
   assert result.get("status")=="computed",(pipe,size,result)
   lines={x["name"]:x for x in result["unit_lines"]}
   assert set(lines)==set(TRADES),(pipe,size,lines)
   for trade in TRADES:
    column=f"{pipe} {trade}(인)"
    expected=Fraction(table["values"][row][column])
    line=lines[trade]
    assert Fraction(line["exact"])==expected,(pipe,size,trade,line,expected)
    cite=line["citations"][0]
    assert cite.get("row")==row and cite.get("column")==column and Fraction(cite.get("value"))==expected
   routes.append({"pipe_type":pipe,"pipe_size":size,"status":"computed",
                  "rates":{k:v["exact"] for k,v in lines.items()}})
 # The PDF leaves copper values blank for 300-400mm; do not treat them as zero or interpolate.
 for size in ("300","350","400"):
  blocked=per_unit(spec,{"pipe_type":"동관","pipe_size":size,"quantity":"1","is_reused":False})
  assert blocked.get("status")=="unresolvable",(size,blocked)
 audit={"id":spec["id"],"status":"visual_source_table_and_resource_columns_verified",
        "source":{"physical_page":977,"printed_page":921,"visual_image":str(IMAGE.relative_to(ROOT)),
                  "pdf_sha256":sha(PDF),"image_sha256":sha(IMAGE),"unique_cells_checked":len(cells),"cells":cells,
                  "layout":"The original page visually confirms size rows; grouped pipe-type headers (steel/copper); labor subcolumns (pipe fitter/general laborer); copper blank cells at 300,350,400. No blank was converted to zero."},
        "runtime":{"exact_routes":len(routes),"computed_resource_outputs":len(routes)*2,"routes":routes,
                    "out_of_source_copper_routes_blocked":3},
        "scope":"58 nonblank source cells, 29 exact size/type routes and 58 rates; three source-blank copper routes stay unresolvable.",
        "spec_sha256":sha(PATH),"per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
 OUT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"cells":len(cells),"routes":len(routes),"rates":len(routes)*2,"blank_routes_blocked":3,"audit":str(OUT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__":main()
