"""Promote 13-1-2 after restoring and validating all four source matrices."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ID="2026-정오표1차/기계설비/13-1-2/관만곡설치"
INDEX=ROOT/"data/drafts/executable.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-13-1-2-multilevel-bend-tables-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-13-1-2-multilevel-bend-tables-promotion-2026-10-19.json"
def main():
 a=json.loads(AUDIT.read_text(encoding="utf-8"));assert a["status"]=="multilevel_source_matrices_and_all_numeric_routes_verified"
 assert a["source"]["source_rate_cells"]==442 and a["source"]["numeric_rate_cells"]==436 and a["source"]["explicit_dash_cells"]==6
 assert a["runtime"]["exact_condition_table_routes"]==218 and a["runtime"]["all_numeric_routes_computed"]==218 and len(a["runtime"]["live_estimate_flows"])==4
 x=json.loads(INDEX.read_text(encoding="utf-8"));assert ID not in x["executable"];fs=[f for f in x["failed"] if f.get("id")==ID];assert len(fs)==1 and fs[0].get("stage")=="calculator_execution_or_rule_gate",fs
 prev=fs[0]["reason"];x["failed"]=[f for f in x["failed"] if f.get("id")!=ID];x["executable"]=sorted([*x["executable"],ID]);s=x["summary"];s["by_calc_type"]["per_unit"]["executable"]+=1;s["by_scope"]["기타"]["executable"]+=1;s["executable"]=len(x["executable"]);s["failed"]=len(x["failed"])
 reasons=[]
 for reason,count in s["failure_reasons_top10"]:
  if reason==prev:
   if count>1:reasons.append([reason,count-1])
  else:reasons.append([reason,count])
 s["failure_reasons_top10"]=reasons;INDEX.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 counts={"executable":len(x["executable"]),"failed":len(x["failed"]),"unsupported":s["skipped_without_compatible_calculator"],"excluded":s["excluded_from_execution"]}
 record={"id":ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":prev,"verification":str(AUDIT.relative_to(ROOT)),"scope":"Printed p.732-733; four visually reviewed multilevel matrices, 442 exact rate/dash cells, 218 complete numeric diameter/bend/SCH routes, all per-unit routes and four live estimate flows.","runtime_changes":["source table grids and continuation row associations restored in processed chunks","opt-in exact table_selector.routes selects only source-present combinations","trade_column_selector resolves exact bend/SCH/trade headers; no fuzzy matches"],"previously_passing_results_affected":0,"policy_open":"Field-work +20% and material-specific surcharge reference were not evaluated in this base-rate audit. Three combinations with two explicit dashes have no calculation route; source note ④ material surcharge and note ⑤ separate costs remain open.","current_counts":counts,"full_rule_verification":False}
 RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(counts,ensure_ascii=False))
if __name__=="__main__":main()
