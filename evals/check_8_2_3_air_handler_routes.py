from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import validate_one,chunks_by_id_from_list
p=ROOT/"data/drafts/specs/기계설비/8-2-3.json";package=json.loads(p.read_text(encoding="utf8"));draft=package["draft"]
expected={
"수냉식 패키지형 / 0.75㎾ 이하":("p750-t1","0.5","0.5"),"수냉식 패키지형 / 1.1㎾이하":("p750-t1","0.6","0.6"),"수냉식 패키지형 / 1.5㎾이하":("p750-t1","1.0","1.0"),"수냉식 패키지형 / 2.2㎾이하":("p750-t1","1.3","1.3"),"수냉식 패키지형 / 3.7㎾이하":("p750-t1","1.5","1.5"),"수냉식 패키지형 / 10.8㎾이하":("p750-t1","2.0","2.0"),"수냉식 패키지형 / 30.0㎾이하":("p750-t1","3.0","3.0"),"수냉식 패키지형 / 37.0㎾이하":("p750-t1","3.5","3.5"),
"공냉식 패키지형 / 2.2㎾이하":("p751-t0","1.0","1.0"),"공냉식 패키지형 / 3.7㎾이하":("p751-t0","1.3","1.3"),"공냉식 패키지형 / 7.5㎾이하":("p751-t0","1.5","1.5"),"핸들링유닛 / 7.5㎾이하":("p751-t0","4.0","1.2"),"핸들링유닛 / 15㎾ 이하":("p751-t0","6.0","1.8"),"핸들링유닛 / 15㎾ 이상":("p751-t0","7.0","2.5"),
"팬코일유닛(床置형) / 510㎥/hr이하":("p751-t0","1.0","0.2"),"팬코일유닛(床置형) / 680㎥/hr이상":("p751-t0","1.0","0.2"),"팬코일유닛(天井형) / 510㎥/hr이하":("p751-t0","1.5","0.5"),"팬코일유닛(天井형) / 680㎥/hr이상":("p751-t0","2.0","0.5"),
"윈도우타입 / 0.4㎾이하":("p751-t0","1.0","0.5"),"윈도우타입 / 0.55㎾ 이하":("p751-t0","1.3","0.5"),"윈도우타입 / 0.75㎾ 이하":("p751-t0","1.5","1.0")}
tables={t["id"]:t for t in draft["tables"]};checks=0
for row,(tid,m,o) in expected.items():
 assert tables[tid]["values"][row]=={"기계설비공(인)":m,"보통인부(인)":o},(row,tables[tid]["values"].get(row))
 result=per_unit(draft,{"unit_type":row,"quantity":"1"});assert result["status"]=="computed",(row,result)
 lines={x["name"]:x for x in result["unit_lines"] if x["kind"]=="labor"}
 for name,value in (("기계설비공",m),("보통인부",o)):
  assert Fraction(lines[name]["exact"])==Fraction(value),(row,name,lines[name])
  src=lines[name]["citations"][0];assert (src["internal_id"],src["row"],src["value"])==(tid,row,value),(row,src)
 checks+=1
assert expected["팬코일유닛(床置형) / 510㎥/hr이하"][1:]!=(expected["팬코일유닛(天井형) / 510㎥/hr이하"][1:])
missing=per_unit(draft,{"unit_type":"수냉식 패키지형 / 0.75㎾ 이하","quantity":"2"});assert missing["status"]=="computed"
# API active compute follows the promoted calculator route.
active=compute({"spec_id":draft["id"],"inputs":{"unit_type":"팬코일유닛(天井형) / 510㎥/hr이하","quantity":"2"}})
assert active["status"]=="COMPUTED",active
chunks_path=ROOT/"data/processed/chunks.all.jsonl";chunks=[json.loads(x) for x in chunks_path.read_text(encoding="utf8").splitlines() if x]
validation=validate_one(p,ROOT/"data/drafts/specs",chunks_by_id_from_list(chunks),hashlib.sha256(chunks_path.read_bytes()).hexdigest());assert validation["ok"],validation
record={"section":"8-2-3","result":"PASS","scope":{"original_table_rows":len(expected),"original_numeric_cells":2*len(expected),"exact_calculator_routes":checks,"fan_coil_types_separately_routed":True,"active_compute_node":"passed","draft_validation":"passed"},"source_evidence":{"original_pdf":"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf","physical_pages":[750,751],"printed_pages":[694,695],"visually_inspected_renders":["evals/runtime_validation/followup-p750.png","evals/runtime_validation/followup-p751.png"],"all_row_values_and_columns":"transcribed from original images; duplicate ditto headings expanded only by direct preceding source label"},"not_verified":["dynamic pricing against labor catalog","consultation","multi-item estimate aggregation","Excel export"],"validation":validation,"hashes":{"spec_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"chunks_all_sha256":hashlib.sha256(chunks_path.read_bytes()).hexdigest()}}
out=ROOT/"evals/runtime_validation/mechanical-8-2-3-air-handler-source-audit-2026-10-19.json";out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8");print(json.dumps(record,ensure_ascii=False,indent=2))
