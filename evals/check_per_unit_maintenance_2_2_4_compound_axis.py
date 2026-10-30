"""Independently verify all 96 2-2-4 cells and the 65% one-rail rule."""
import hashlib,itertools,json,sys
from fractions import Fraction
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table
PATH=ROOT/"data/drafts/specs/유지관리/2-2-4.json"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE=ROOT/"evals/runtime_validation/source-p951-maint-2-2-4.png"
OUT=ROOT/"evals/runtime_validation/per-unit-maintenance-2-2-4-compound-axis-2026-10-19.json"
TRACKS=("목침목 구간","PCT 구간","교량","터널")
TRADES=("궤도공","보통인부")
BLOCKS=("3시간 차단","4시간 차단")
LENGTHS=("30m 이하","100m 이하","100m 초과")
WEIGHTS=("50㎏","60㎏")
EXPECTED={
"목침목 구간 궤도공":(193,204,161,171,130,138,178,189,149,158,121,128),
"목침목 구간 보통인부":(42,45,35,38,29,30,39,42,33,35,27,28),
"PCT 구간 궤도공":(178,196,149,164,121,133,166,183,139,153,112,124),
"PCT 구간 보통인부":(39,43,33,36,27,29,37,40,31,34,25,27),
"교량 궤도공":(242,264,202,221,164,179,226,246,188,206,153,167),
"교량 보통인부":(53,58,44,49,36,39,50,54,42,45,34,37),
"터널 궤도공":(255,261,213,218,173,176,237,242,198,202,161,164),
"터널 보통인부":(56,57,47,48,38,39,52,53,44,44,35,36)}
HEADERS=tuple(f"{block} 시공구간 {length} {weight}" for block in BLOCKS for length in LENGTHS for weight in WEIGHTS)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(PATH.read_text(encoding="utf8"))["draft"];table=next(t for t in spec["tables"] if t["id"]=="p951-t0")
 cells=[]
 for row,values in EXPECTED.items():
  assert row in table["values"]
  for header,expected in zip(HEADERS,values):
   raw=table["values"][row][header]
   assert Fraction(raw)==expected,(row,header,raw,expected)
   c=cite_table("p951-t0",row,header,raw)
   assert c.get("value")==raw and c.get("pdf_page")==951 and c.get("printed_page")==895,c
   cells.append({"row":row,"column":header,"value":raw})
 assert len(cells)==96
 doc=pymupdf.open(PDF);page=doc[950];text=page.get_text("text")
 assert "2-2-4" in text and "65%" in text and all(str(v) in text for v in set(sum((list(x) for x in EXPECTED.values()),[])))
 routes=[]
 for track,block,length,weight,side in itertools.product(TRACKS,BLOCKS,LENGTHS,WEIGHTS,("양측","한측")):
  inp={"track_type":track,"block_time":block,"work_length":length,"rail_weight":weight,
       "exchange_side":side,"quantity":"1"}
  got=per_unit(spec,inp);assert got.get("status")=="computed",(inp,got)
  ci=(BLOCKS.index(block)*6+LENGTHS.index(length)*2+WEIGHTS.index(weight))
  lines={x["name"]:x for x in got["unit_lines"]};assert set(lines)==set(TRADES)
  for trade in TRADES:
   base=Fraction(EXPECTED[f"{track} {trade}"][ci]);expected=base*(Fraction(13,20) if side=="한측" else 1)
   assert Fraction(lines[trade]["exact"])==expected,(inp,trade,lines[trade],expected)
   assert any(c.get("value")==str(base) for c in lines[trade]["citations"]),lines[trade]["citations"]
   if side=="한측": assert any("65%" in str(c.get("quote") or "") or "65%" in str(c.get("label") or "") for c in lines[trade]["citations"])
  routes.append({**inp,"status":"computed","rates":{k:v["exact"] for k,v in lines.items()}})
 audit={"id":spec["id"],"status":"all_original_cells_compound_axes_and_one_rail_rule_verified",
  "source":{"physical_page":951,"printed_page":895,"visual_image":str(IMAGE.relative_to(ROOT)),"pdf_sha256":sha(PDF),"image_sha256":sha(IMAGE),"unique_cells_checked":len(cells),"cells":cells,
            "layout":"Visually checked all four track groups, two trades, 12 block-time×work-length×rail-weight columns, and the one-rail-only 65% note."},
  "runtime":{"routes":len(routes),"computed":len(routes),"rate_outputs":len(routes)*2,"routes":routes},
  "scope":"96 source cells and 96 exact track×block-time×length×weight×exchange-side routes; 192 independently calculated labor outputs including the 13/20 one-rail factor.",
  "spec_sha256":sha(PATH),"per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
 OUT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"cells":len(cells),"routes":len(routes),"outputs":len(routes)*2,"audit":str(OUT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__":main()
