"""Audit 2-2-6 transposed labor axes and reconstructed material rows."""
import hashlib,json,os,sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.estimate import tools as et
from backend.agent.nodes import select as sn
from backend.agent.tools.source import citation as cr
from pipeline.validate_drafts import chunks_by_id_from_list,check_table_citation,validate_one
SPEC=ROOT/"data/drafts/specs/기계설비/2-2-6.json";PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf";IMAGE=ROOT/"evals/runtime_validation/source-p719-mech-2-2-6-smoke-damper.png";OUT=ROOT/"evals/runtime_validation/per-unit-2-2-6-damper-labor-and-materials-2026-10-19.json"
LABOR={"수직덕트 연결방식":{"덕트공":"2.041","보통인부":"0.588"},"승강로 연결방식":{"덕트공":"1.216","보통인부":"0.350"}}
MATERIALS=[("앵커 | 규격 1/2〃","앵커 1/2〃","개","20"),("블라인드리벳","블라인드리벳","개","75"),("철물 | 규격 D22 철근","철물 D22 철근","㎏","12.5"),("실리콘","실리콘","㎏","1.25")]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def flow(spec,connection):
 hit={"rank":1,"section_no":"2-2-6","division":"기계설비","section":spec["title"],"page":663,"table_id":"p719-t3","text":spec["title"],"chunk_id":"p719-t3"};sm={("기계설비","2-2-6"):[spec]}
 with patch.object(cr,"_pages",return_value=defaultdict(lambda:{"printed_page":663,"division":"기계설비"})),patch.object(et,"specs_by_section",return_value=sm),patch.object(et,"load_specs",return_value={spec["id"]:spec}),patch.object(sn,"specs_by_section",return_value=sm):
  s=et.new_estimate("제연댐퍼 설치");et.find_work(s,hits=[hit]);first=et.compute_labor(s);assert any(x["field"]=="connection_type" for x in first["missing"]),first
  et.set_conditions(s,connection,values={"connection_type":{"value":connection,"evidence":connection}},source="answer");asked=et.compute_labor(s);q=next(x for x in asked.get("missing",[]) if x["field"]=="quantity");assert q.get("unit")=="㎡",q
  et.set_conditions(s,"2㎡",quantity={"value":"2","unit":"㎡","evidence":"2㎡"},source="text");result=et.compute_labor(s);assert result.get("status")=="ok",result
  lines=result["data"]["unit_lines"];assert len(lines)==6
  observed={x["name"]:Fraction(x["exact"]) for x in lines};expected={**{k:Fraction(v) for k,v in LABOR[connection].items()},**{name:Fraction(value) for _,name,_,value in MATERIALS}}
  assert observed==expected,(observed,expected)
  return {"connection_type":connection,"quantity_prompt_unit":"㎡","quantity":"2","status":"ok","unit_rates":{k:str(v) for k,v in observed.items()},"additional_source_cost_rules":"equipment cost rule remains separately represented in cost_rules"}
def main():
 os.environ.update(AGENT_MODE="tools",AGENT_LLM="off",AGENT_OFFLINE="1")
 pkg=json.loads(SPEC.read_text(encoding="utf-8"));d=pkg["draft"];tables={t["id"]:t for t in d["tables"]};chunks=[json.loads(x) for x in (ROOT/"data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()];ci=chunks_by_id_from_list(chunks);page=pymupdf.open(PDF)[718].get_text("text");assert "2.041" in page and "12.5" in page and "기계경비는 인력품의 2%" in page
 assert d["quantity_model"]["params"]["unit_rate_table"]["row_input"] is None
 checked=[]
 for connection,rates in LABOR.items():
  row={trade:value for trade,value in rates.items()}
  for trade,value in row.items():
   table=tables["p719-t3"];assert table["values"][trade][connection]==value
   cite={"table_id":"p719-t3","row":trade,"column":connection,"value":value};assert check_table_citation(ci,cite) is None,cite;checked.append(cite)
 for row,name,unit,value in MATERIALS:
  assert tables["p719-t4"]["values"][row]=={"단위":unit,"수량":value}
  for column,raw in (("단위",unit),("수량",value)):
   cite={"table_id":"p719-t4","row":row,"column":column,"value":raw};assert check_table_citation(ci,cite) is None,cite;checked.append(cite)
 for row,spec_value in (("앵커 | 규격 1/2〃","1/2〃"),("철물 | 규격 D22 철근","D22 철근")):
  cite={"table_id":"p719-t4","row":row,"column":"규격","value":spec_value};assert check_table_citation(ci,cite) is None,cite;checked.append(cite)
 direct={}
 for connection,rates in LABOR.items():
  got=per_unit(d,{"connection_type":connection,"quantity":"2"});assert got.get("status")=="computed",got
  lines={x["name"]:Fraction(x["exact"]) for x in got["unit_lines"]};expected={**{k:Fraction(v) for k,v in rates.items()},**{name:Fraction(value) for _,name,_,value in MATERIALS}};assert lines==expected,(connection,lines,expected)
  direct[connection]={k:str(v) for k,v in lines.items()}
 validation=validate_one(SPEC,ROOT/"data/drafts/specs",ci,None);assert not validation.get("issues"),validation
 flows=[flow(d,c) for c in LABOR]
 report={"id":d["id"],"status":"source_transposed_labor_and_material_rows_verified","source":{"physical_page":719,"printed_page":663,"visual_image":str(IMAGE.relative_to(ROOT)),"image_sha256":sha(IMAGE),"independent_source_cells_checked":14,"labor_rate_cells":4,"material_quantity_cells":4,"material_unit_cells":4,"material_spec_cells":2,"source_transcription":"p.663 smoke-damper labor table compared by row trade and connection column; separate reference material table visually transcribed item/spec/unit/quantity rows; source note ② separate electrical conduit/wiring retained; note ③ 2% equipment-cost rule retained in cost_rules"},"runtime":{"direct_exact_routes":direct,"estimate_flows":flows,"citations_checked":len(checked),"validation_issues":validation.get("issues",[])},"rule_scope":{"labor_and_reference_material_coefficients_verified":True,"cost_rule_2_percent_source_preserved":True,"cost_amount_evaluation_and_separate electrical conduit/wiring remain outside this labor/material route; all_rules_fully_verified":False},"spec_sha256":sha(SPEC),"chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py"),"runtime_fill_sha256":sha(ROOT/"backend/agent/nodes/fill.py")}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({"status":report["status"],"source_cells":14,"estimate_flows":len(flows),"citations":len(checked),"fully_verified_rules":False},ensure_ascii=False))
if __name__=="__main__":main()
