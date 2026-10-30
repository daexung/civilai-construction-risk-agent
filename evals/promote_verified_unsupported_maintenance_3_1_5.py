"""Promote 3-1-5 after restoring and verifying its original sparse table."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipeline.validate_drafts import load_chunks,validate_one
ID="2026-정오표1차/유지관리/3-1-5/석축헐기"
INDEX=ROOT/"data/drafts/executable.json"
SPEC=ROOT/"data/drafts/specs/유지관리/3-1-5.json"
SOURCE=ROOT/"evals/runtime_validation/source-extraction-3-1-5-restoration-2026-10-19.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-maintenance-3-1-5-source-table-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-maintenance-3-1-5-source-table-promotion-2026-10-19.json"
sour=json.loads(SOURCE.read_text(encoding="utf8"));a=json.loads(AUDIT.read_text(encoding="utf8"))
assert sour["status"]=="original_source_table_extraction_restored" and sour["source"]["visually_checked_cells"]==8
assert a["status"]=="original_sparse_table_and_mixed_unit_routes_verified" and a["source"]["unique_cells_checked"]==8
assert a["runtime"]["preflight_statuses"]=={"computed":4,"blocked":28}
validation=validate_one(SPEC,ROOT/"data/drafts/specs",load_chunks(ROOT/"data/processed/chunks.all.jsonl"),None)
assert validation["ok"],validation
i=json.loads(INDEX.read_text(encoding="utf8"))
if ID not in i["executable"]:
    skipped=[x for x in i["skipped"] if x.get("id")==ID]
    assert len(skipped)==1 and skipped[0].get("calc_type")=="not_calculable",skipped
    i["skipped"]=[x for x in i["skipped"] if x.get("id")!=ID]
    i["executable"]=sorted([*i["executable"],ID])
    summary=i["summary"]
    summary["skipped_without_compatible_calculator"]-=1
    summary["executable"]=len(i["executable"])
    summary["by_calc_type"]["per_unit"]["attempted"]+=1
    summary["by_calc_type"]["per_unit"]["executable"]+=1
    summary["by_scope"]["기타"]["attempted"]+=1
    summary["by_scope"]["기타"]["executable"]+=1
    INDEX.write_text(json.dumps(i,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
else:
    assert ID not in [x.get("id") for x in i["skipped"]]
summary=i["summary"]
record={"id":ID,"previous_status":"unsupported/not_calculable","current_status":"executable",
 "verification":[str(SOURCE.relative_to(ROOT)),str(AUDIT.relative_to(ROOT))],
 "scope":"Restored all eight cells from the visually checked source table on physical p969/printed p913; four task routes use exact ㎡/㎥ denominators; 28 of 32 height/reuse/leveling preflight combinations stay blocked. Miscellaneous materials remain unapplied because the source only says within 5%.",
 "runtime_changes":["opt-in trade_in_columns","opt-in quantity_unit_selector"],
 "previously_passing_results_affected":0,
 "focused_regressions":{"check_per_unit.py":"44/44","maintenance_4_1_1":"58 cells / 29 routes / 58 rates","maintenance_2_2_4":"96 cells / 96 routes / 192 labor outputs","maintenance_3_1_5":"8 cells / 4 base routes / 28 blocked policy variants"},
 "current_counts":{"executable":len(i["executable"]),"failed":len(i["failed"]),"unsupported":summary["skipped_without_compatible_calculator"],"excluded":summary["excluded_from_execution"]},
 "full_rule_verification":False}
RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print(json.dumps(record["current_counts"],ensure_ascii=True))
