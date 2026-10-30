"""Promote the exact 9-18-5 total-row lookup after its original-table audit."""
from __future__ import annotations
import hashlib,json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KEY="2026-정오표1차/토목/9-18-5/연속지적도품질개선_임야"

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
 audit_path=ROOT/"evals/runtime_validation/per-unit-9-18-5-total-row-2026-10-19.json"
 audit=json.loads(audit_path.read_text(encoding="utf8"))
 assert audit["status"]=="pass" and audit["independent_source_cells"]==2
 assert (audit["exact_quantity_routes"],audit["exact_rate_outputs_with_citations"])==(2,4)
 idx_path=ROOT/"data/drafts/executable.json";idx=json.loads(idx_path.read_text(encoding="utf8"))
 if KEY not in idx["executable"]:
  failure=next(r for r in idx["failed"] if r["id"]==KEY)
  assert failure["stage"]=="calculator_execution_or_rule_gate"
  idx["failed"]=[r for r in idx["failed"] if r["id"]!=KEY];idx["executable"]=sorted([*idx["executable"],KEY])
  idx["summary"]["by_calc_type"]["per_unit"]["executable"]+=1
 idx["summary"]["executable"]=len(idx["executable"]);idx["summary"]["failed"]=len(idx["failed"])
 idx["summary"]["failure_reasons_top10"]=[list(p) for p in Counter(str(r.get("reason","")) for r in idx["failed"]).most_common(10)]
 idx_path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 stages=dict(Counter(r["stage"] for r in idx["failed"]))
 current={"executable":len(idx["executable"]),"failed":len(idx["failed"]),
  "unsupported":idx["summary"]["skipped_without_compatible_calculator"],
  "excluded":idx["summary"]["excluded_from_execution"],"failure_stages":stages}
 cp_path=ROOT/"evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
 cp=json.loads(cp_path.read_text(encoding="utf8"));cp["previous_active_lists"]=cp["current_active_lists"];cp["current_active_lists"]=current
 if KEY not in cp["promoted"]:cp["promoted"].append(KEY)
 cp["source_checks"]["토목/9-18-5"]=("Original PDF p.621 (printed p.565): two final total-row cells independently visually checked. "
  "The exact 합계 row selector is retained; nonexistent literal 직종 column selector was removed. Two quantities produced four exact rate/citation outputs. Equipment and materials remain separately accounted.")
 cp["validation"]["cadastral_total_row"] = audit
 added=cp.setdefault("source_evidence_added_this_continuation",{"sections":0,"cells":0,"breakdown":{}})
 key2="토목/9-18-5"
 if key2 not in added.setdefault("breakdown",{}):added["sections"]+=1;added["cells"]+=2;added["breakdown"][key2]=2
 cp["remaining_failures"]={"calculator_or_rule_gate":stages.get("calculator_execution_or_rule_gate",0),
  "source_preflight":stages.get("source_preflight",0),"format_preflight":stages.get("format_or_input_preflight",0),
  "open_policy":cp["remaining_failures"]["open_policy"]}
 base=ROOT/"data/drafts/specs";entries=[p.relative_to(base).as_posix().encode()+b"\0"+sha(p).encode() for p in sorted(base.rglob("*.json"))]
 cp["hashes"].update({"spec_count":len(entries),"spec_manifest_sha256":hashlib.sha256(b"\n".join(entries)).hexdigest(),
  "chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"executable_sha256":sha(idx_path),
  "runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py"),"validator_sha256":sha(ROOT/"pipeline/validate_drafts.py")})
 cp_path.write_text(json.dumps(cp,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 report={"promoted":KEY,"current_active_lists":current,"audit":str(audit_path.relative_to(ROOT)),
  "reused":"unaffected saved validations","rerun":"9-18-5 source total route",
  "full_replay":False,"full_rule_verification":0,"hashes":cp["hashes"]}
 (ROOT/"evals/runtime_validation/executable-9-18-5-total-row-promotion-2026-10-19.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())
