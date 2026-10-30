"""Source-backed rail quantities with independent stage-to-trade totals."""
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
PATH=ROOT/"data/drafts/specs/기계설비/13-10-4.json"
AUDIT=ROOT/"evals/runtime_validation/mechanical-13-10-4-overhead-rail-source-audit-2026-10-19.json"
PKG=json.loads(PATH.read_text(encoding="utf-8"));SPEC=PKG["draft"]
SOURCE={"레일":"1","레일체결구":"1","준비작업/궤도공":"0.014","준비작업/목도":"0.007","준비작업/보통인부":"0.012","본작업/궤도공":"0.013","본작업/목도":"0.007","본작업/보통인부":"0.002","뒷정리/궤도공":"0.026","뒷정리/목도":"0.006","뒷정리/보통인부":"0.013"}
TABLE=next(t for t in SPEC["tables"] if t["id"]=="p905-t2")
assert len(SOURCE)==11 and len(PKG["citations"])==11
for cite in PKG["citations"]:assert cite["table_id"]=="p905-t2" and cite["value"]==SOURCE[cite["row"]]
expected_totals={"궤도공":Fraction(53,1000),"목도":Fraction(20,1000),"보통인부":Fraction(27,1000)}
price_version=select_rate_version("2026-10-19");assert price_version and price_version["id"]=="2026H2"
route_count=0
for length in ("1","20","43.5"):
 inputs={"length":length,"reference_basis":"50kg/m 레일·ℓ=20m 원문 기준"}
 result=per_unit(SPEC,inputs);assert result["status"]=="computed",result
 lines=result["unit_lines"];assert len(lines)==11,lines
 labor_totals={name:Fraction(0) for name in expected_totals}
 source_line_count=0
 for line in lines:
  assert line["citations"][0]["internal_id"]=="p905-t2"
  source_cell=next((row for row in TABLE["values"] if row in SOURCE and row==line["citations"][0]["row"]),None)
  assert source_cell and line["citations"][0]["value"]==SOURCE[source_cell]
  if line["kind"]=="labor":
   labor_totals[line["name"]]+=Fraction(line["exact"]);source_line_count+=1
 assert labor_totals==expected_totals,labor_totals
 assert source_line_count==9
 materials={line["name"]:Fraction(line["exact"]) for line in lines if line["kind"]=="material"}
 assert materials=={"레일":Fraction(1),"레일체결구":Fraction(1)},materials
 priced=price_unit(SPEC,lines,price_version,inputs,basis_date="2026-10-19")
 assert all(line["reason"] is None for line in priced["lines"] if line["kind"]=="labor" and line["name"]!="목도"),priced["lines"]
 assert all(line["reason"]=="노임 직종 대응 없음: 목도" for line in priced["lines"] if line["kind"]=="labor" and line["name"]=="목도"),priced["lines"]
 assert {x["name"] for x in priced["unpriced"]}=={"목도","레일","레일체결구","구멍뚫기 또는 용접","레일운반용 장비 및 운반비"},priced["unpriced"]
 route_count+=1
blocked=per_unit(SPEC,{"length":"20","reference_basis":"기준 외"});assert blocked["status"]=="blocked",blocked
validation=validate_one(PATH,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None);assert validation["ok"],validation
node_status="not_registered_in_active_execution_index"
if SPEC["id"] in load_specs():
 node=compute({"spec_id":SPEC["id"],"inputs":{"length":"20","reference_basis":"50kg/m 레일·ℓ=20m 원문 기준"}});assert node["status"]=="COMPUTED",node;node_status=node["status"]
audit={"id":SPEC["id"],"status":"pass","source_numeric_cells_independently_checked":11,"source_cells":SOURCE,"source_page":{"physical_pdf":905,"printed":849,"render":"evals/runtime_validation/source-followup-physical-905.png"},"length_cases_checked":route_count,"independent_trade_totals_per_m":{"궤도공":"0.053","목도":"0.020","보통인부":"0.027"},"source_basis_block":"50kg/m rail and 20m basis; other basis blocked","separately_accounted":["drilling or welding","rail transport equipment and transport costs"],"local_price_check":{"wage_version":price_version["id"],"local_wage_mapping":"궤도공·보통인부 priced; 목도 has no matching local trade code and remains unpriced without substitution","rail_material_rates":"quantities verified; current material catalog missing and preserved as unpriced"},"full_rule_verification":False,"calculation_node":node_status,"validator_ok":validation["ok"]}
AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(audit,ensure_ascii=False,indent=2))
