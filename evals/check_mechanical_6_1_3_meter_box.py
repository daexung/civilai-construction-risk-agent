"""Source visual, boundaries, unit rates and offline price path for 6-1-3."""
from __future__ import annotations
import json
from fractions import Fraction
from pathlib import Path
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
ROOT=Path(__file__).resolve().parents[1]
SPEC_PATH=ROOT/"data/drafts/specs/기계설비/6-1-3.json"
AUDIT_PATH=ROOT/"evals/runtime_validation/mechanical-6-1-3-meter-box-source-audit-2026-10-19.json"
PKG=json.loads(SPEC_PATH.read_text(encoding="utf-8"));SPEC=PKG["draft"]
EXPECTED={"배관공":{"수량":"0.086"},"보통인부":{"수량":"0.086"}}
TABLE=next(t for t in SPEC["tables"] if t["id"]=="p736-t0")
assert TABLE["values"]==EXPECTED and len(PKG["citations"])==2
for x in PKG["citations"]:assert x["value"]==EXPECTED[x["row"]][x["column"]]
count_cases=0
for quantity in (1,2,10,25):
 inputs={"meter_diameter_class":"32mm 이하","box_tier":"2단 이하","quantity":quantity}
 result=per_unit(SPEC,inputs);assert result["status"]=="computed",(inputs,result)
 assert len(result["unit_lines"])==2
 for line in result["unit_lines"]:
  assert Fraction(line["exact"])==Fraction(86,1000)
  assert line["citations"][0]["internal_id"]=="p736-t0"
 priced=price_unit(SPEC,result["unit_lines"],select_rate_version("2026-10-19"),inputs,basis_date="2026-10-19")
 assert len(priced["cost_lines"])==1 and priced["cost_lines"][0]["rate"]=="0.02"
 assert priced["cost_lines"][0]["citations"][0]["internal_id"]=="p736-x2"
 assert priced["cost_lines"][0]["amount"] is not None
 from decimal import Decimal
 assert Decimal(priced["cost_lines"][0]["amount_exact"])==Decimal(priced["labor_subtotal"])*Decimal("0.02")
 for line in priced["lines"]:
  assert Fraction(line["quantity"])==Fraction(86,1000),(line,quantity)
 count_cases+=1
for inputs in [
 {"meter_diameter_class":"32mm 초과","box_tier":"2단 이하","quantity":1},
 {"meter_diameter_class":"32mm 이하","box_tier":"3단 이상","quantity":1}]:
 result=per_unit(SPEC,inputs);assert result["status"]=="blocked",(inputs,result)
validation=validate_one(SPEC_PATH,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None);assert validation["ok"],validation
node_status="not_registered_in_active_execution_index"
if SPEC["id"] in load_specs():
 node=compute({"spec_id":SPEC["id"],"inputs":{"meter_diameter_class":"32mm 이하","box_tier":"2단 이하","quantity":10}});assert node["status"]=="COMPUTED",node;node_status=node["status"]
audit={"id":SPEC["id"],"status":"pass","independent_source_numeric_cells_checked":2,"expected_source_rates":EXPECTED,"source_pages_reviewed":{"physical_pdf":[736],"printed":[680],"render":"evals/runtime_validation/source-followup-physical-736.png"},"quantity_cases_checked":count_cases,"source_scope":"유량계 ø32mm 이하 및 계량기함 2단 이하; 앵커 구멍·지지대·보호통 포함; 연결배관·밸브·계량기 설치 별도","blocked_policy_cases":2,"tool_and_light_equipment_rate":"2% of labor subtotal; source-cited and applied by offline local wage/equipment pricing path","full_rule_verification":False,"calculation_node":node_status,"validator_ok":validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(audit,ensure_ascii=False,indent=2))
