"""Promote civil 9-6-3 after source and condition-route verification."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ID="2026-정오표1차/토목/9-6-3/지적기준점현황조사"
INDEX=ROOT/"data/drafts/executable.json"
AUDIT=ROOT/"evals/runtime_validation/per-unit-9-6-3-exact-table-routes-2026-10-19.json"
RECORD=ROOT/"evals/runtime_validation/executable-9-6-3-exact-table-routes-promotion-2026-10-19.json"
def main():
 a=json.loads(AUDIT.read_text(encoding="utf-8"));assert a["status"]=="exact_condition_table_routes_and_tenth_basis_verified" and a["source"]["source_cells_checked"]==4 and len(a["runtime"]["condition_routes"])==4 and len(a["runtime"]["estimate_flows"])==4
 x=json.loads(INDEX.read_text(encoding="utf-8"));assert ID not in x["executable"];fs=[f for f in x["failed"] if f.get("id")==ID];assert len(fs)==1 and fs[0].get("stage")=="calculator_execution_or_rule_gate",fs
 prev=fs[0]["reason"];x["failed"]=[f for f in x["failed"] if f.get("id")!=ID];x["executable"]=sorted([*x["executable"],ID]);s=x["summary"];s["by_calc_type"]["per_unit"]["executable"]+=1;s["by_scope"]["기타"]["executable"]+=1;s["executable"]=len(x["executable"]);s["failed"]=len(x["failed"])
 reasons=[]
 for reason,count in s["failure_reasons_top10"]:
  if reason==prev:
   if count>1:reasons.append([reason,count-1])
  else:reasons.append([reason,count])
 s["failure_reasons_top10"]=reasons;INDEX.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 counts={"executable":len(x["executable"]),"failed":len(x["failed"]),"unsupported":s["skipped_without_compatible_calculator"],"excluded":s["excluded_from_execution"]}
 rec={"id":ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":prev,"verification":str(AUDIT.relative_to(ROOT)),"scope":"Printed p.524; four aggregate labor cells checked, exact condition-based table routing for triangular/traverse/auxiliary points, note ② tenth-basis and note ③ mountainous exception; four route calculations and live estimate flows passed.","runtime_changes":["opt-in exact table_selector.routes matches all declared conditions uniquely","quantity parser accepts exact source unit 点"],"previously_passing_results_affected":0,"policy_open":"Source note ④ ancillary traverse-point surveying and note ⑤ vessel rental remain separate costs; not inferred or included.","current_counts":counts,"full_rule_verification":False}
 RECORD.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(counts,ensure_ascii=False))
if __name__=="__main__":main()
