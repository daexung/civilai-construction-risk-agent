"""Independent source and daily-crew verification for common 6-6-6."""
from __future__ import annotations
import json
from pathlib import Path
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one
ROOT=Path(__file__).resolve().parents[1]
SPEC_PATH=ROOT/"data/drafts/specs/공통/6-6-6.json"
AUDIT_PATH=ROOT/"evals/runtime_validation/common-6-6-6-source-daily-crew-audit-2026-10-19.json"
PKG=json.loads(SPEC_PATH.read_text(encoding="utf-8")); SPEC=PKG["draft"]
EXPECTED={"철공":{"단위":"인","수량":"3"},"보통인부":{"단위":"인","수량":"1"},"크레인":{"단위":"대","수량":"1"},"고소작업차":{"단위":"대","수량":"1"},"시공량":{"높이 20m이하":"17","높이 40m이하":"15"}}
TABLE=next(t for t in SPEC["tables"] if t["id"]=="p210-t0")
assert TABLE["values"]==EXPECTED, TABLE["values"]
assert PKG["citations"] and len(PKG["citations"])==6
for citation in PKG["citations"]:
 assert citation["table_id"]=="p210-t0" and citation["value"]==EXPECTED[citation["row"]][citation["column"]]
computed=0
for height, productivity, area in [("20m이하",17,170),("20m이하",17,85),("40m이하",15,150),("40m이하",15,75)]:
 inputs={"height":height,"area":str(area),"crane_access":True,"work_location":"육상"}
 result=adjusted_daily_crew(SPEC,inputs)
 assert result["status"]=="computed",(inputs,result)
 days=area/productivity
 assert result["daily_volume_m3"]==str(productivity)
 from fractions import Fraction
 assert Fraction(result["work_days"])==Fraction(area,productivity)
 assert result["person_days"]=={"철공":str(Fraction(3*area,productivity)),"보통인부":str(Fraction(area,productivity))}
 assert result["equipment_days"]=={"크레인":str(Fraction(area,productivity)),"고소작업차":str(Fraction(area,productivity))}
 selected=result["provenance"]["daily_volume_m3"]["base_output"]
 assert (selected["row"],selected["column"],selected["value"])==("시공량",f"높이 {height}",str(productivity)), selected
 assert selected["citations"][0]["internal_id"]=="p210-t0"
 assert all(c.get("internal_id")=="p210-t0" for line in result["unit_lines"] for c in line.get("citations",[]))
 computed+=1
for changed in [{"crane_access":False},{"work_location":"해상"},{"work_location":"교량상판 위"}]:
 inputs={"height":"20m이하","area":"100","crane_access":True,"work_location":"육상"}; inputs.update(changed)
 result=adjusted_daily_crew(SPEC,inputs)
 assert result["status"]=="blocked",(inputs,result)
validation=validate_one(SPEC_PATH,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None)
assert validation["ok"],validation
node_status="not_registered_in_active_execution_index"
if SPEC["id"] in load_specs():
 node=compute({"spec_id":SPEC["id"],"inputs":{"height":"20m이하","area":"170","crane_access":True,"work_location":"육상"}})
 assert node["status"]=="COMPUTED",node
 node_status=node["status"]
audit={"id":SPEC["id"],"status":"pass","source_numeric_cells_independently_checked":6,"source_cells":EXPECTED,"source_pages_reviewed":{"physical_pdf":[210],"printed":[154],"render":"evals/runtime_validation/source-6-6-6-210-followup.png"},"computed_routes":computed,"blocked_policy_routes":3,"independent_expected":"work_days=area/source_output; ironworker=3*work_days; general_worker=work_days; crane_days=work_days; aerial_lift_days=work_days","verified_source_rules":["section scope and included activities [주] ①~③","land + crane access standard and mandatory separate accounting exceptions [주] ④","crane/lift specifications depend on height/location/load/radius and are not selected here [주] ⑤","tool/light-equipment cost is 3% of labor cost, retained as a separate cost rule [주] ⑥"],"unresolved":"equipment specifications and price/cost aggregation are not calculated by this quantity route","full_rule_verification":False,"calculation_node":node_status,"validator_ok":validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(audit,ensure_ascii=False,indent=2))
