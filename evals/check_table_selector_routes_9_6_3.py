"""Verify 9-6-3 condition-routed source tables, exact totals and one-tenth basis."""
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
SPEC=ROOT/"data/drafts/specs/토목/9-6-3.json";PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf";OUT=ROOT/"evals/runtime_validation/per-unit-9-6-3-exact-table-routes-2026-10-19.json"
EXPECTED={"p580-t0":{"지적기사":"5.69","지적산업기사":"4.33"},"p580-t1":{"지적기사":"0.30","지적산업기사":"0.21"}}
ROUTES=[("지적삼각점",False,"p580-t0"),("지적도근점",False,"p580-t1"),("지적삼각보조점",False,"p580-t1"),("지적삼각보조점",True,"p580-t0")]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def flow(spec,point,mountainous,table):
 hit={"rank":1,"section_no":"9-6-3","division":"토목","section":spec["title"],"page":524,"table_id":table,"text":spec["title"],"chunk_id":table}; sm={("토목","9-6-3"):[spec]}
 with patch.object(cr,"_pages",return_value=defaultdict(lambda:{"printed_page":524,"division":"토목"})),patch.object(et,"specs_by_section",return_value=sm),patch.object(et,"load_specs",return_value={spec["id"]:spec}),patch.object(sn,"specs_by_section",return_value=sm):
  s=et.new_estimate("지적기준점 현황조사");et.find_work(s,hits=[hit]);res=et.compute_labor(s)
  answers={"point_type":point,"is_mountainous":mountainous}
  et.set_conditions(s,"지적기준점 조건 확인",values={k:{"value":v,"evidence":str(v)} for k,v in answers.items()},source="answer")
  res=et.compute_labor(s);q=next(x for x in res.get("missing",[]) if x["field"]=="quantity");assert q.get("unit")=="점",q
  et.set_conditions(s,"10점",quantity={"value":"10","unit":"점","evidence":"10점"},source="answer");res=et.compute_labor(s);assert res.get("status")=="ok",res
  lines={x["name"]:Fraction(x["exact"]) for x in res["data"]["unit_lines"]};assert lines=={n:Fraction(v)/10 for n,v in EXPECTED[table].items()},lines
  return {"table":table,"quantity_prompt_unit":"점","quantity":"10","total_labor":{k:str(v) for k,v in lines.items()},"status":"ok"}
def main():
 os.environ.update(AGENT_MODE="tools",AGENT_LLM="off",AGENT_OFFLINE="1")
 package=json.loads(SPEC.read_text(encoding="utf-8"));d=package["draft"];chunks=[json.loads(x) for x in (ROOT/"data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()];ci=chunks_by_id_from_list(chunks);page=pymupdf.open(PDF)[579].get_text("text")
 assert "10분의 1을 적용한다" in page and "산악지에 위치한 경우에는 지적삼각점" in page
 for tid,vals in EXPECTED.items():
  table=next(t for t in d["tables"] if t["id"]==tid);assert len(table["values"])==1 and "합계" in table["values"]
  for trade,rate in vals.items():
   col=next(c for c in table["values"]["합계"] if trade.replace(" ","") in "".join(c.split()));assert table["values"]["합계"][col]==rate
   cite={"table_id":tid,"row":"합계","column":col,"value":rate};assert check_table_citation(ci,cite) is None,cite
 audits=[]
 for point,mountain,tid in ROUTES:
  out=per_unit(d,{"point_type":point,"is_mountainous":mountain,"quantity":"10"});assert out.get("status")=="computed",(point,mountain,out)
  got={x["name"]:Fraction(x["exact"]) for x in out["unit_lines"]};assert got=={n:Fraction(v)/10 for n,v in EXPECTED[tid].items()},got
  audits.append({"point_type":point,"is_mountainous":mountain,"selected_table":tid,"rates_per_point":{k:str(v) for k,v in got.items()}})
 flows=[flow(d,p,m,t) for p,m,t in ROUTES]
 validation=validate_one(SPEC,ROOT/"data/drafts/specs",ci,None);assert not validation.get("issues"),validation
 report={"id":d["id"],"status":"exact_condition_table_routes_and_tenth_basis_verified","source":{"physical_page":580,"printed_page":524,"source_cells_checked":4,"source_rule":"10 points per source table; 1/10 is applied per point per note ②; auxiliary control point uses traverse-point table except mountainous locations, which may use triangular-point table per note ③","source_values":EXPECTED,"note_quote":"본 품은 지적기준점 10점을 현황조사하는데 소요되는 품으로 1점의 품셈을 산출하기 위해서는 위의 품의 10분의 1을 적용한다."},"runtime":{"condition_routes":audits,"estimate_flows":flows,"validation_issues":validation.get("issues",[])},"rule_scope":{"tables_and_route_conditions_checked":True,"note_②_and_③_checked":True,"other exclusion notes ④/⑤ are retained as separately accounted items; all_rules_fully_verified":False},"spec_sha256":sha(SPEC),"chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({"status":report["status"],"cells":4,"routes":len(audits),"estimate_flows":len(flows),"all_rules_fully_verified":False},ensure_ascii=False))
if __name__=="__main__":main()
