"""Promote mechanical 2-2-6 after source axes and material rows were verified."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ID="2026-정오표1차/기계설비/2-2-6/제연댐퍼설치"
INDEX=ROOT/"data/drafts/executable.json";AUDIT=ROOT/"evals/runtime_validation/per-unit-2-2-6-damper-labor-and-materials-2026-10-19.json";RECORD=ROOT/"evals/runtime_validation/executable-2-2-6-damper-labor-and-materials-promotion-2026-10-19.json"
def main():
 a=json.loads(AUDIT.read_text(encoding="utf-8"));assert a["status"]=="source_transposed_labor_and_material_rows_verified" and a["source"]["independent_source_cells_checked"]==14 and len(a["runtime"]["estimate_flows"])==2
 x=json.loads(INDEX.read_text(encoding="utf-8"));assert ID not in x["executable"];fs=[f for f in x["failed"] if f.get("id")==ID];assert len(fs)==1 and fs[0].get("stage")=="calculator_execution_or_rule_gate",fs
 prev=fs[0]["reason"];x["failed"]=[f for f in x["failed"] if f.get("id")!=ID];x["executable"]=sorted([*x["executable"],ID]);s=x["summary"];s["by_calc_type"]["per_unit"]["executable"]+=1;s["by_scope"]["기타"]["executable"]+=1;s["executable"]=len(x["executable"]);s["failed"]=len(x["failed"])
 reasons=[]
 for reason,count in s["failure_reasons_top10"]:
  if reason==prev:
   if count>1:reasons.append([reason,count-1])
  else:reasons.append([reason,count])
 s["failure_reasons_top10"]=reasons;INDEX.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 counts={"executable":len(x["executable"]),"failed":len(x["failed"]),"unsupported":s["skipped_without_compatible_calculator"],"excluded":s["excluded_from_execution"]}
 record={"id":ID,"previous_status":"failed","current_status":"executable","previous_failure_reason":prev,"verification":str(AUDIT.relative_to(ROOT)),"scope":"Printed p.663: four transposed labor cells and eight material quantity/unit/spec cells independently matched; both connection modes computed and estimate quantity prompts returned ㎡.","runtime_changes":[],"source_extraction_repair":"p719-t4's flattened merged material labels were restored into four exact source rows in chunks.all.jsonl and the spec.","previously_passing_results_affected":0,"policy_open":"The 2% light-equipment expense remains in cost_rules and is outside this per-unit labor/material output. Electrical conduit and wiring remain explicitly separate per source note ②.","current_counts":counts,"full_rule_verification":False}
 RECORD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(counts,ensure_ascii=False))
if __name__=="__main__":main()
