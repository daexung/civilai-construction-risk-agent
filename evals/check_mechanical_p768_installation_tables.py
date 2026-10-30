"""Independent restored-source and offline pricing audit for the paired p768 tables."""
from __future__ import annotations
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
ROOT=Path(__file__).resolve().parents[1]
CASES=[("10-8-2","data/drafts/specs/기계설비/10-8-2.json","p768-t0",{"기계설비공":"0.212","보통인부":"0.117"}),("10-9-1","data/drafts/specs/기계설비/10-9-1.json","p768-t1",{"기계설비공":"0.094","보통인부":"0.046"})]
results=[]
for sec,rel,table_id,rates in CASES:
 path=ROOT/rel;pkg=json.loads(path.read_text(encoding="utf-8"));spec=pkg["draft"]
 table=next(t for t in spec["tables"] if t["id"]==table_id)
 expected={trade:{"수량":rate} for trade,rate in rates.items()}
 assert table["values"]==expected
 assert len(pkg["citations"])==2
 for cite in pkg["citations"]:assert cite["value"]==expected[cite["row"]][cite["column"]]
 validator=validate_one(path,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None)
 assert validator["ok"],validator
 price_version=select_rate_version("2026-10-19");assert price_version and price_version["id"]=="2026H2"
 checked=0
 for quantity in (1,10,37):
  inputs={"quantity":quantity}
  calc=per_unit(spec,inputs);assert calc["status"]=="computed",(sec,inputs,calc)
  assert {line["name"]:Fraction(line["exact"]) for line in calc["unit_lines"]}=={name:Fraction(value) for name,value in rates.items()}
  for line in calc["unit_lines"]:
   assert line["citations"][0]["internal_id"]==table_id
  priced=price_unit(spec,calc["unit_lines"],price_version,inputs,basis_date="2026-10-19")
  assert priced["labor_subtotal"] is not None and all(line["reason"] is None for line in priced["lines"]),(sec,priced["lines"])
  allowed_unpriced={item["item"] for item in spec.get("not_calculated",[])}
  assert {item["name"] for item in priced["unpriced"]}==allowed_unpriced,(sec,priced["unpriced"])
  assert sum(Decimal(line["amount"]) for line in priced["lines"])==Decimal(priced["labor_subtotal"])
  checked+=1
 node_status="not_registered_in_active_execution_index"
 if spec["id"] in load_specs():
  node=compute({"spec_id":spec["id"],"inputs":{"quantity":10}});assert node["status"]=="COMPUTED",(sec,node);node_status=node["status"]
 results.append({"id":spec["id"],"status":"pass","source_numeric_cells_checked":2,"rates":rates,"quantity_cases_checked":checked,"source_page":{"physical_pdf":768,"printed":712},"offline_price_version":price_version["id"],"scope_notes":(["제어배관·입선 및 가스차단 밸브 별도 계상"] if sec=="10-8-2" else ["원문에 열거된 완강기 지지대·보호함·안전표시 포함"]),"full_rule_verification":False,"calculation_node":node_status,"validator_ok":validator["ok"]})
audit={"status":"pass","source_tables_checked":2,"source_numeric_cells_checked":4,"original_page_reviewed":"evals/runtime_validation/source-followup-physical-768.png","items":results}
(ROOT/"evals/runtime_validation/mechanical-p768-installation-source-audit-2026-10-19.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(audit,ensure_ascii=False,indent=2))
