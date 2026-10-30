"""Promote 2-2-4 after full cell, compound-axis and one-side rule checks."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ID="2026-정오표1차/유지관리/2-2-4/레일교환(인력)"
INDEX=ROOT/"data/drafts/executable.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-maintenance-2-2-4-compound-axis-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-maintenance-2-2-4-compound-axis-promotion-2026-10-19.json"
a=json.loads(AUDIT.read_text(encoding="utf8"));assert a["status"]=="all_original_cells_compound_axes_and_one_rail_rule_verified"
assert a["source"]["unique_cells_checked"]==96 and len(a["runtime"]["routes"])==96 and a["runtime"]["rate_outputs"]==192
i=json.loads(INDEX.read_text(encoding="utf8"));assert ID not in i["executable"]
f=[x for x in i["failed"] if x.get("id")==ID]
assert len(f)==1 and "열 후보 0개" in f[0].get("reason","")
reason=f[0]["reason"]
i["failed"]=[x for x in i["failed"] if x.get("id")!=ID]
i["executable"]=sorted([*i["executable"],ID]);s=i["summary"]
s["executable"],s["failed"]=len(i["executable"]),len(i["failed"])
s["by_calc_type"]["per_unit"]["executable"]+=1;s["by_scope"]["기타"]["executable"]+=1
s["failure_reasons_top10"]=[[r,n-1 if r==reason else n] for r,n in s["failure_reasons_top10"] if r!=reason or n>1]
INDEX.write_text(json.dumps(i,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
record={"id":ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":reason,
 "verification":str(AUDIT.relative_to(ROOT)),"scope":"All 96 cells on physical p951/printed p895, 96 exact track×block-time×length×rail-weight×exchange-side routes and 192 labor outputs; one-sided rail exchange applies the source 65% as exact 13/20.",
 "runtime_changes":[],"previously_passing_results_affected":0,"current_counts":{"executable":len(i["executable"]),"failed":len(i["failed"]),"unsupported":s["skipped_without_compatible_calculator"],"excluded":s["excluded_from_execution"]},"full_rule_verification":False}
RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print(json.dumps(record["current_counts"],ensure_ascii=True))
