from __future__ import annotations
import hashlib,json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];KEY='2026-정오표1차/토목/4-5-3/장대레일설정'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 audit=json.loads((ROOT/'evals/runtime_validation/per-unit-4-5-3-explicit-dash-2026-10-19.json').read_text(encoding='utf8'))
 assert audit['status']=='pass' and audit['independent_source_cells']==6 and audit['exact_method_routes']==4 and audit['format_citation_preflight']=='pass'
 path=ROOT/'data/drafts/executable.json';idx=json.loads(path.read_text(encoding='utf8'))
 if KEY not in idx['executable']:
  row=next(x for x in idx['failed'] if x['id']==KEY);assert row['stage']=='calculator_execution_or_rule_gate'
  idx['failed']=[x for x in idx['failed'] if x['id']!=KEY];idx['executable']=sorted([*idx['executable'],KEY]);idx['summary']['by_calc_type']['per_unit']['executable']+=1
 idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(p) for p in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)];path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 stages=dict(Counter(x['stage'] for x in idx['failed']));current={'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution'],'failure_stages':stages}
 cp_path=ROOT/'evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json';cp=json.loads(cp_path.read_text(encoding='utf8'));cp['previous_active_lists']=cp['current_active_lists'];cp['current_active_lists']=current
 if KEY not in cp.setdefault('promoted',[]):cp['promoted'].append(KEY)
 cp.setdefault('validation',{})['civil_4_5_3_explicit_dash']=audit
 add=cp.setdefault('source_evidence_added_this_continuation',{'sections':0,'cells':0,'breakdown':{}});b=add.setdefault('breakdown',{})
 if '토목/4-5-3 dash cell' not in b:add['sections']+=1;add['cells']+=6;b['토목/4-5-3 dash cell']=6
 cp['remaining_failures']={'calculator_or_rule_gate':stages.get('calculator_execution_or_rule_gate',0),'source_preflight':stages.get('source_preflight',0),'format_preflight':stages.get('format_or_input_preflight',0),'open_policy':cp['remaining_failures']['open_policy']}
 base=ROOT/'data/drafts/specs';entries=[p.relative_to(base).as_posix().encode()+b'\0'+sha(p).encode() for p in sorted(base.rglob('*.json'))]
 cp['hashes'].update({'spec_count':len(entries),'spec_manifest_sha256':hashlib.sha256(b'\n'.join(entries)).hexdigest(),'chunks_sha256':sha(ROOT/'data/processed/chunks.all.jsonl'),'executable_sha256':sha(path),'runtime_per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py'),'validator_sha256':sha(ROOT/'pipeline/validate_drafts.py')});cp_path.write_text(json.dumps(cp,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 rep={'promoted':KEY,'current_active_lists':current,'source_audit':audit,'source_cell_change':'Restored explicit dash in p406-t2 extraction/spec and cited exclusion for natural-ambient special labor.','full_replay':False,'full_rule_verification':0,'hashes':cp['hashes']};(ROOT/'evals/runtime_validation/executable-4-5-3-dash-promotion-2026-10-19.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(rep,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
