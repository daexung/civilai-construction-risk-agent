"""Original-page source and daily-output/rate audit for mechanical 1-5-3."""
from __future__ import annotations
import json
from fractions import Fraction
from pathlib import Path
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import load_chunks, validate_one
ROOT=Path(__file__).resolve().parents[1]
SPEC_PATH=ROOT/"data/drafts/specs/기계설비/1-5-3.json"
AUDIT_PATH=ROOT/"evals/runtime_validation/mechanical-1-5-3-rubber-pipe-source-audit-2026-10-19.json"
PKG=json.loads(SPEC_PATH.read_text(encoding="utf-8")); SPEC=PKG["draft"]
RATES={"50":"75","65":"65","75":"50","100":"38","125":"32","150":"25","200":"20"}
TABLE=next(t for t in SPEC["tables"] if t["id"]=="p712-t0")
assert TABLE["values"]=={"배관공":{"단위":"인","수량":"3"},"보통인부":{"단위":"인","수량":"1"},"시공량":RATES,"비고":{"시공량 가산":"26%"}}
assert len(PKG["citations"])==9
for citation in PKG["citations"]:
 assert citation["table_id"]=="p712-t0" and citation["value"]==TABLE["values"][citation["row"]][citation["column"]]
methods={"인력시공":Fraction(1),"자체 추진 고소작업대(시저형)시공":Fraction(126,100)}
checked=0
for size,raw in RATES.items():
 base=Fraction(raw)
 for method,multiplier in methods.items():
  output=base*multiplier
  result=adjusted_daily_crew(SPEC,{"pipe_size":size,"quantity":str(output),"construction_method":method})
  assert result["status"]=="computed",(size,method,result)
  assert Fraction(result["daily_volume_m3"])==output
  assert Fraction(result["work_days"])==1
  assert result["person_days"]=={"배관공":"3","보통인부":"1"}
  source=result["provenance"]["daily_volume_m3"]["base_output"]
  assert (source["row"],source["column"],source["value"])==("시공량",size,raw),source
  adjustments=result["provenance"]["daily_volume_m3"]["output_adjustments"]
  if multiplier==1:
   assert adjustments==[],adjustments
  else:
   assert len(adjustments)==1 and adjustments[0]["before"]==raw and Fraction(adjustments[0]["after"])==output
   cite=adjustments[0]["citations"][0]
   assert (cite["internal_id"],cite["row"],cite["column"],cite["value"])==("p712-t0","비고","시공량 가산","26%")
  checked+=1
# Verify price-rule routing with the local offline rate catalogue only; where no current wage
# version exists, the cost is retained as unpriced instead of inventing a rate.
rate_version=select_rate_version("2026-10-19")
pricing=[]
for method,expected_rate in [("인력시공","0.02"),("자체 추진 고소작업대(시저형)시공","0.10")]:
 result=adjusted_daily_crew(SPEC,{"pipe_size":"50","quantity":"75","construction_method":method})
 priced=price_unit(SPEC,result["unit_lines"],rate_version,{"construction_method":method,"pipe_size":"50","quantity":"75"},basis_date="2026-10-19")
 active=[x for x in priced["cost_lines"] if x["name"].startswith("공구손료") ]
 assert len(active)==1 and active[0]["rate"]==expected_rate,(method,priced.get("costs"))
 assert active[0]["citations"] and active[0]["citations"][0]["internal_id"]=="p712-x11"
 if rate_version is None:
  assert active[0]["amount"] is None and "노무비 소계 미완성" in active[0]["reason"]
 pricing.append({"method":method,"source_rate":expected_rate,"amount_status":"unpriced_local_wage_or_trade_rate_gap" if active[0]["amount"] is None else "computed_offline"})
validation=validate_one(SPEC_PATH,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None)
assert validation["ok"],validation
node_status="not_registered_in_active_execution_index"
if SPEC["id"] in load_specs():
 node=compute({"spec_id":SPEC["id"],"inputs":{"pipe_size":"50","quantity":"94.5","construction_method":"자체 추진 고소작업대(시저형)시공"}})
 assert node["status"]=="COMPUTED",node
 node_status=node["status"]
audit={"id":SPEC["id"],"status":"pass","independent_source_numeric_cells_checked":9,"pipe_size_rows_checked":7,"calculation_routes_checked":checked,"source_pages_reviewed":{"physical_pdf":[712],"printed":[656],"render":"evals/runtime_validation/source-followup-physical-712.png"},"verified":{"labor_rows":{"배관공":"3인","보통인부":"1인"},"source_daily_output_m":{"50":"75","65":"65","75":"50","100":"38","125":"32","150":"25","200":"20"},"self_propelled_scissor_output":"source base × 1.26; all seven rows checked","cost_rates_by_method":{"인력시공":"2% of labor subtotal","자체 추진 고소작업대(시저형)시공":"10% of labor subtotal"},"price_path":pricing},"separately_accounted":["단열 지지대 및 관 지지대","시저형 작업대 이동용 크레인/지게차 비용"],"full_rule_verification":False,"calculation_node":node_status,"validator_ok":validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(audit,ensure_ascii=False,indent=2))
