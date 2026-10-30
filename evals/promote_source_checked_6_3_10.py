from __future__ import annotations
import hashlib,json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
KEY='2026-정오표1차/공통/6-3-10/신축이음설치'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 audit_path=ROOT/'evals/runtime_validation/per-unit-6-3-10-source-routes-2026-10-19.json'; audit=json.loads(audit_path.read_text(encoding='utf8'))
 assert audit['status']=='pass' and audit['independent_source_cells']==6 and audit['exact_work_type_table_routes']==3 and audit['exact_runtime_cell_citations']==6 and audit['format_citation_preflight']=='pass'
 idx_path=ROOT/'data/drafts/executable.json'; idx=json.loads(idx_path.read_text(encoding='utf8'))
 if KEY not in idx['executable']:
  failed=next(row for row in idx['failed'] if row['id']==KEY)
  assert failed['stage']=='calculator_execution_or_rule_gate'
  idx['failed']=[row for row in idx['failed'] if row['id']!=KEY]
  idx['executable']=sorted([*idx['executable'],KEY])
  idx['summary']['by_calc_type']['per_unit']['executable']+=1
 idx['summary']['executable']=len(idx['executable']); idx['summary']['failed']=len(idx['failed'])
 idx['summary']['failure_reasons_top10']=[list(pair) for pair in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)]
 idx_path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 stages=dict(Counter(x['stage'] for x in idx['failed']))
 current={'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution'],'failure_stages':stages}
 cp_path=ROOT/'evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json'; cp=json.loads(cp_path.read_text(encoding='utf8'))
 cp['previous_active_lists']=cp.get('current_active_lists',{}); cp['current_active_lists']=current
 cp.setdefault('promoted',[])
 if KEY not in cp['promoted']:cp['promoted'].append(KEY)
 cp.setdefault('validation',{})['common_6_3_10']=audit
 cp['validation']['runtime_change_impact']=("Added opt-in quantity_unit_by_table for exact per-table denominators where the work type implies the quantity unit. A full spec scan found the new key only in 공통/6-3-10. Its three source-table routes and all six rate citations were checked, with inputs quantity=2; `check_per_unit.py` passed 44/44. `price_unit` confirmed the 1% tool fee is emitted only for sealing. Prior promoted specs were not rerun because they do not use this new declaration.")
 cp['validation']['per_unit_runtime_impact_rechecked']=sorted(set(cp['validation'].get('per_unit_runtime_impact_rechecked',[])+['공통/6-3-10']))
 old=cp.get('source_evidence_added_this_continuation',{'sections':0,'cells':0,'breakdown':{}}); breakdown=old.setdefault('breakdown',{})
 if '공통/6-3-10 expansion joint' not in breakdown: old['sections']+=1;old['cells']+=6;breakdown['공통/6-3-10 expansion joint']=6
 cp['source_evidence_added_this_continuation']=old
 cp['remaining_failures']={'calculator_or_rule_gate':stages.get('calculator_execution_or_rule_gate',0),'source_preflight':stages.get('source_preflight',0),'format_preflight':stages.get('format_or_input_preflight',0),'open_policy':cp['remaining_failures']['open_policy']}
 base=ROOT/'data/drafts/specs'; entries=[p.relative_to(base).as_posix().encode()+b'\0'+sha(p).encode() for p in sorted(base.rglob('*.json'))]
 cp['hashes'].update({'spec_count':len(entries),'spec_manifest_sha256':hashlib.sha256(b'\n'.join(entries)).hexdigest(),'chunks_sha256':sha(ROOT/'data/processed/chunks.all.jsonl'),'executable_sha256':sha(idx_path),'runtime_per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py'),'validator_sha256':sha(ROOT/'pipeline/validate_drafts.py')})
 cp_path.write_text(json.dumps(cp,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 report={'promoted':KEY,'current_active_lists':current,'audit':str(audit_path.relative_to(ROOT)),'runtime_impact_scan':['공통/6-3-10'],'reused':'unaffected saved validations','rerun':'source audit 6 cells, 3 route/calculation cases, 3 price paths, focused per_unit suite 44/44','full_replay':False,'full_rule_verification':0,'hashes':cp['hashes']}
 out=ROOT/'evals/runtime_validation/executable-6-3-10-source-routes-promotion-2026-10-19.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
