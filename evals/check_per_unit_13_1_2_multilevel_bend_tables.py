"""Audit recovered 13-1-2 matrices and every exact diameter/SCH/bend route."""
import hashlib,json,os,sys
from fractions import Fraction
from pathlib import Path
import pymupdf
from collections import defaultdict
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.estimate import tools as et
from backend.agent.nodes import select as sn
from backend.agent.tools.source import citation as citation_runtime
from pipeline.validate_drafts import chunks_by_id_from_list,check_table_citation,validate_one
SPEC=ROOT/"data/drafts/specs/기계설비/13-1-2.json";PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf";IMAGE1=ROOT/"evals/runtime_validation/source-p788-mech-13-1-2-bends.png";IMAGE2=ROOT/"evals/runtime_validation/source-p789-mech-13-1-2-bends.png";OUT=ROOT/"evals/runtime_validation/per-unit-13-1-2-multilevel-bend-tables-2026-10-19.json"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm_rows(row):return " ".join(str(row or "").split())
def compact(v):return "".join(str(v).split()).replace("～","∼")
def estimate_flow(spec,route):
 tid=route["table"];page=732 if tid.startswith("p788") else 733
 hit={"rank":1,"section_no":"13-1-2","division":"기계설비","section":spec["title"],"page":page,"table_id":tid,"text":spec["title"],"chunk_id":tid};sm={("기계설비","13-1-2"):[spec]}
 with patch.object(citation_runtime,"_pages",return_value=defaultdict(lambda:{"printed_page":page,"division":"기계설비"})),patch.object(et,"specs_by_section",return_value=sm),patch.object(et,"load_specs",return_value={spec["id"]:spec}),patch.object(sn,"specs_by_section",return_value=sm):
  s=et.new_estimate("관만곡 설치");et.find_work(s,hits=[hit]);et.compute_labor(s)
  values={**route["when"],"material":"탄소강관","is_field_work":False}
  et.set_conditions(s,"표 조건 확인",values={k:{"value":v,"evidence":str(v)} for k,v in values.items()},source="answer");res=et.compute_labor(s)
  q=next(x for x in res.get("missing",[]) if x["field"]=="quantity");assert q.get("unit")=="개",q
  et.set_conditions(s,"1개",quantity={"value":"1","unit":"개","evidence":"1개"},source="text");res=et.compute_labor(s);assert res.get("status")=="ok",res
  return {"table":tid,"selected_conditions":values,"quantity_prompt_unit":"개","result":"ok","labor_lines":{x["name"]:x["exact"] for x in res["data"]["unit_lines"]}}
def forward(row):
 out=[];x=""
 for v in row:
  if v is not None and str(v).strip():x=norm_rows(v)
  out.append(x)
 return out
def read_grid(doc,page,table_ix,table_id,sizes,start):
 t=doc[page].find_tables().tables[table_ix];g=t.extract();groups,sch,trades=forward(g[0]),forward(g[1]),forward(g[2]);cells=g[3];result={}
 for j in range(start,len(cells)):
  if not groups[j] or not sch[j] or not trades[j]:continue
  col=f"{groups[j]} | {sch[j]} | {trades[j]}";seq=[norm_rows(v) for v in (cells[j] or "").splitlines() if v.strip()]
  for row,val in zip(sizes,seq):result.setdefault(row,{})[col]=val
 return result
def main():
 os.environ.update(AGENT_MODE="tools",AGENT_LLM="off",AGENT_OFFLINE="1")
 package=json.loads(SPEC.read_text(encoding="utf-8"));d=package["draft"];tables={t["id"]:t for t in d["tables"]};chunks=[json.loads(x) for x in (ROOT/"data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()];ci=chunks_by_id_from_list(chunks);doc=pymupdf.open(PDF)
 expected={
  "p788-t0":read_grid(doc,787,0,"p788-t0",["ø25","32","40","50","65","80","90","100","125","150","200","250","300","350","400","450","500","600"],2),
  "p788-t1":read_grid(doc,787,1,"p788-t1",["ø25","32","40","50","65","80","90","100","125","150","200","250"],0),
  "p789-t0":read_grid(doc,788,0,"p789-t0",["300","350","400","450"],0),
  "p789-t1":read_grid(doc,788,1,"p789-t1",["ø25","32","40","50","65","80","90","100","125","150","200","250","300","350","400"],2),
 }
 assert all(tables[k]["values"]==v for k,v in expected.items()),"PDF table re-extraction differs from restored spec matrix"
 cells=0;numeric=0;dashes=[];route_results=[]
 for tid,rows in expected.items():
  assert tid in ci and ci[tid].get("extraction_recovery"),tid
  for row,cols in rows.items():
   for col,raw in cols.items():
    cells+=1
    cite={"table_id":tid,"row":row,"column":col,"value":raw};assert check_table_citation(ci,cite) is None,cite
    if raw=="-":dashes.append({"table_id":tid,"row":row,"column":col,"value":raw})
    else:
     Fraction(raw);numeric+=1
 # Independently re-execute every valid condition route. A pair of explicit dashes stays unsupported.
 rate=d["quantity_model"]["params"]["unit_rate_table"];routes=rate["table_selector"]["routes"]
 assert len(routes)==218
 for route in routes:
  cond=route["when"];args={**cond,"material":"탄소강관","is_field_work":False,"quantity":"1"}
  got=per_unit(d,args);assert got.get("status")=="computed",(cond,route["table"],got)
  row="ø25" if cond["pipe_diameter"]=="25" else cond["pipe_diameter"];source=expected[route["table"]][row]
  exp={trade:Fraction(next(raw for col,raw in source.items() if [compact(x) for x in col.split("|")]==[compact(cond["bend_type"]),compact(cond["sch_no"]),compact(trade)])) for trade in rate["trades"]}
  actual={line["name"]:Fraction(line["exact"]) for line in got["unit_lines"]}
  assert actual==exp,(cond,actual,exp)
  assert all(line["unit"]=="인/개" for line in got["unit_lines"])
  route_results.append({**cond,"table":route["table"],"rates":{k:str(v) for k,v in actual.items()}})
 # Exactly six printed dash cells form three two-trade conditions; they are not converted to zeros or routed as rates.
 assert len(dashes)==6 and len(route_results)==218
 all_conditions={tuple(sorted(r["when"].items())) for r in routes}
 dash_conditions=set()
 for c in dashes:
  parts=c["column"].split(" | ");size=c["row"].removeprefix("ø")
  dash_conditions.add((size,parts[0],parts[1]))
 assert len(dash_conditions)==3
 validation=validate_one(SPEC,ROOT/"data/drafts/specs",ci,None);assert not validation.get("issues"),validation
 representatives=[]
 for tid in expected:
  representatives.append(next(route for route in routes if route["table"]==tid))
 live=[estimate_flow(d,r) for r in representatives];assert len(live)==4
 report={"id":d["id"],"status":"multilevel_source_matrices_and_all_numeric_routes_verified","source":{"physical_pages":[788,789],"printed_pages":[732,733],"visual_images":[{"path":str(IMAGE1.relative_to(ROOT)),"sha256":sha(IMAGE1)},{"path":str(IMAGE2.relative_to(ROOT)),"sha256":sha(IMAGE2)}],"matrix_tables":[{"table_id":k,"rows":len(v),"cells":sum(len(r) for r in v.values())} for k,v in expected.items()],"source_rate_cells":cells,"numeric_rate_cells":numeric,"explicit_dash_cells":len(dashes),"dash_cells":dashes,"recovered_row_associations":{"p788-t0":"explicit diameter column","p788-t1":"continued sizes 25–250, visually aligned with preceding table","p789-t0":"continued sizes 300–450, visually aligned with p.732 table","p789-t1":"explicit diameter column"},"header_axes":"bend type × SCH No × trade, independently reviewed against page images; no row/column transposition accepted"},"runtime":{"exact_condition_table_routes":len(routes),"all_numeric_routes_computed":len(route_results),"routes":route_results,"unrouted_all-dash_conditions":[list(x) for x in sorted(dash_conditions)],"live_estimate_flows":live},"rule_scope":{"base_rates_and_table_axes_verified":True,"explicit_dashes_remain_non-rates":True,"field-work +20% and material-specific surcharge reference remain outside this audit; all_rules_fully_verified":False},"spec_sha256":sha(SPEC),"chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py"),"runtime_fill_sha256":sha(ROOT/"backend/agent/nodes/fill.py")}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({"status":report["status"],"cells":cells,"numeric":numeric,"dashes":len(dashes),"routes":len(route_results),"fully_verified_rules":False},ensure_ascii=False))
if __name__=="__main__":main()
