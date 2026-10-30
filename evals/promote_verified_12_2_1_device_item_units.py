"""Promote mechanical 12-2-1 after its focused source/runtime audit."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC_ID="2026-정오표1차/기계설비/12-2-1/자동제어기기설치"
INDEX=ROOT/"data/drafts/executable.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-12-2-1-device-item-units-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-12-2-1-device-item-units-promotion-2026-10-19.json"

def main():
    audit=json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"]=="all_mixed_device_units_and_source_rates_verified"
    assert audit["source"]["source_rows_checked"]==21 and audit["source"]["unit_and_labor_cells_checked"]==42
    assert audit["runtime"]["computed_routes"]==21 and set(audit["runtime"]["estimate_flows_by_unit"])=={"개","조","면"}
    index=json.loads(INDEX.read_text(encoding="utf-8"))
    assert SPEC_ID not in index["executable"]
    matches=[x for x in index["failed"] if x.get("id")==SPEC_ID]
    assert len(matches)==1 and matches[0].get("stage")=="calculator_execution_or_rule_gate",matches
    previous=matches[0]["reason"]
    index["failed"]=[x for x in index["failed"] if x.get("id")!=SPEC_ID]
    index["executable"]=sorted([*index["executable"],SPEC_ID])
    summary=index["summary"]
    summary["by_calc_type"]["per_unit"]["executable"]+=1
    summary["by_scope"]["기타"]["executable"]+=1
    summary["executable"]=len(index["executable"]); summary["failed"]=len(index["failed"])
    reasons=[]
    for reason,count in summary["failure_reasons_top10"]:
        if reason==previous:
            if count>1: reasons.append([reason,count-1])
        else: reasons.append([reason,count])
    summary["failure_reasons_top10"]=reasons
    INDEX.write_text(json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    counts={"executable":len(index["executable"]),"failed":len(index["failed"]),"unsupported":summary["skipped_without_compatible_calculator"],"excluded":summary["excluded_from_execution"]}
    record={"id":SPEC_ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":previous,"verification":str(AUDIT.relative_to(ROOT)),"scope":"Printed p.719; 21 exact rows, 42 unit/rate cells and all 21 computed routes; estimate quantity prompts and calculations checked for 개, 조, 면.","runtime_changes":["opt-in basis_by_selected_unit uses exact source-mapped denominator","row_map_by_column provides exact source row citations for device/spec selections","fill parser supports 면 and 조"],"previously_passing_results_affected":0,"policy_open":"Small transport is included by the source note. Separate note adjustments and all-rule verification remain outside this audit.","current_counts":counts,"full_rule_verification":False}
    RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(counts,ensure_ascii=False))

if __name__=="__main__": main()
