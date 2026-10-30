"""Promote maintenance 2-2-6 after original-cell and route verification."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ID="2026-정오표1차/유지관리/2-2-6/침목교환(인력)"
INDEX=ROOT/"data/drafts/executable.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-maintenance-2-2-6-compound-headers-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-maintenance-2-2-6-compound-headers-promotion-2026-10-19.json"
a=json.loads(AUDIT.read_text(encoding="utf8"))
assert a["status"]=="original_cells_and_compound_header_routes_verified"
assert a["source"]["unique_cells_checked"]==32 and a["runtime"]["exact_work_block_site_routes"]==16
i=json.loads(INDEX.read_text(encoding="utf8"))
assert ID not in i["executable"]
f=[x for x in i["failed"] if x.get("id")==ID]
assert len(f)==1 and "열 후보 0개" in f[0].get("reason","") and "block_time_and_site_condition" in f[0].get("reason",""),f
reason=f[0]["reason"]
i["failed"]=[x for x in i["failed"] if x.get("id")!=ID]
i["executable"]=sorted([*i["executable"],ID])
s=i["summary"]
s["executable"],s["failed"]=len(i["executable"]),len(i["failed"])
s["by_calc_type"]["per_unit"]["executable"]+=1
s["by_scope"]["기타"]["executable"]+=1
s["failure_reasons_top10"]=[[r,n-1 if r==reason else n] for r,n in s["failure_reasons_top10"] if r!=reason or n>1]
INDEX.write_text(json.dumps(i,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
record={"id":ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":reason,
        "verification":str(AUDIT.relative_to(ROOT)),"scope":"All 32 original source cells on physical p952/printed p896 and all 16 exact work×block-time×site routes; no system rule was applied to the supplemental field table.",
        "runtime_changes":[],"previously_passing_results_affected":0,
        "current_counts":{"executable":len(i["executable"]),"failed":len(i["failed"]),"unsupported":s["skipped_without_compatible_calculator"],"excluded":s["excluded_from_execution"]},
        "full_rule_verification":False}
RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print(json.dumps(record["current_counts"],ensure_ascii=True))
