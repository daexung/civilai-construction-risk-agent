"""Promote 13-1-3 after table-specific input axes pass source and runtime checks."""
from __future__ import annotations
import hashlib,json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KEY="2026-정오표1차/기계설비/13-1-3/밸브취부"

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
 audit_path=ROOT/"evals/runtime_validation/per-unit-13-1-3-table-specific-axes-2026-10-19.json"
 audit=json.loads(audit_path.read_text(encoding="utf8"))
 assert audit["status"]=="pass" and audit["independent_pdf_cells"]==32
 assert (audit["exact_diameter_pressure_routes"],audit["additional_quantity_3_routes"],
         audit["all_quantity_routes_checked"],audit["exact_rate_outputs_with_table_citations"])==(170,16,186,372)
 assert audit["format_preflight"]==audit["citation_preflight"]=="pass"
 idx_path=ROOT/"data/drafts/executable.json";idx=json.loads(idx_path.read_text(encoding="utf8"))
 if KEY not in idx["executable"]:
  failure=next(row for row in idx["failed"] if row["id"]==KEY)
  assert failure["stage"]=="calculator_execution_or_rule_gate"
  idx["failed"]=[row for row in idx["failed"] if row["id"]!=KEY]
  idx["executable"]=sorted([*idx["executable"],KEY])
  idx["summary"]["by_calc_type"]["per_unit"]["executable"]+=1
 idx["summary"]["executable"]=len(idx["executable"]);idx["summary"]["failed"]=len(idx["failed"])
 idx["summary"]["failure_reasons_top10"]=[list(pair) for pair in
   Counter(str(row.get("reason","")) for row in idx["failed"]).most_common(10)]
 idx_path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 stages=dict(Counter(row["stage"] for row in idx["failed"]))
 current={"executable":len(idx["executable"]),"failed":len(idx["failed"]),
  "unsupported":idx["summary"]["skipped_without_compatible_calculator"],
  "excluded":idx["summary"]["excluded_from_execution"],"failure_stages":stages}
 # The new runtime branch is opt-in. Confirm no previously promoted spec uses it.
 affected=[]
 for path in (ROOT/"data/drafts/specs").rglob("*.json"):
  draft=json.loads(path.read_text(encoding="utf8"))["draft"]
  table=draft.get("quantity_model",{}).get("params",{}).get("unit_rate_table",{})
  if "column_input_by_table" in table:affected.append(draft["id"])
 assert affected==[KEY],affected
 cp_path=ROOT/"evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
 cp=json.loads(cp_path.read_text(encoding="utf8"));cp["previous_active_lists"]=cp["current_active_lists"];cp["current_active_lists"]=current
 if KEY not in cp["promoted"]:cp["promoted"].append(KEY)
 cp["source_checks"]["기계설비/13-1-3"]=(
  "Original PDF pp.790-791 (printed pp.734-735): all three different pressure-header domains were visually checked, "
  "along with 32 representative labor cells. Each valve type now activates its own exact diameter and pressure "
  "inputs and selects its exact source table. All 170 diameter-pressure pairs plus 16 quantity-3 routes were "
  "computed, producing 372 rates with exact table citations. `check_per_unit.py` passed 44/44 after adding the "
  "opt-in column_input_by_table runtime branch; only this section declares that branch."
 )
 cp["validation"]["valve_type_specific_axes"]=audit
 cp["validation"]["runtime_change_impact"]=(
  "Added opt-in column_input_by_table. A full spec scan found exactly one declaration: the source-checked "
  "13-1-3 spec. The focused matrix/citation audit passed for that spec and check_per_unit.py passed 44/44; "
  "prior promoted specs do not declare or execute the new branch."
 )
 cp["validation"]["per_unit_runtime_impact_rechecked"]=sorted(set(
  cp["validation"].get("per_unit_runtime_impact_rechecked",[])+["기계설비/13-1-3"]))
 added=cp.setdefault("source_evidence_added_this_continuation",{"sections":0,"cells":0,"breakdown":{}})
 if "기계설비/13-1-3 valve axes" not in added.setdefault("breakdown",{}):
  added["sections"]+=1;added["cells"]+=32;added["breakdown"]["기계설비/13-1-3 valve axes"]=32
 cp["remaining_failures"]={"calculator_or_rule_gate":stages.get("calculator_execution_or_rule_gate",0),
  "source_preflight":stages.get("source_preflight",0),"format_preflight":stages.get("format_or_input_preflight",0),
  "open_policy":cp["remaining_failures"]["open_policy"]}
 base=ROOT/"data/drafts/specs";entries=[p.relative_to(base).as_posix().encode()+b"\0"+sha(p).encode() for p in sorted(base.rglob("*.json"))]
 cp["hashes"].update({"spec_count":len(entries),"spec_manifest_sha256":hashlib.sha256(b"\n".join(entries)).hexdigest(),
  "chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"executable_sha256":sha(idx_path),
  "runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py"),
  "validator_sha256":sha(ROOT/"pipeline/validate_drafts.py")})
 cp_path.write_text(json.dumps(cp,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 report={"promoted":KEY,"current_active_lists":current,"audit":str(audit_path.relative_to(ROOT)),
  "runtime_impact_scan":affected,"reused":"unaffected saved validations",
  "rerun":"13-1-3 only plus check_per_unit.py 44/44 after opt-in runtime branch change",
  "full_replay":False,"full_rule_verification":0,"hashes":cp["hashes"]}
 (ROOT/"evals/runtime_validation/executable-13-1-3-table-axis-promotion-2026-10-19.json").write_text(
  json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())
