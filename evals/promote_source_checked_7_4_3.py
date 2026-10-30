import json,hashlib
from collections import Counter
from pathlib import Path
ROOT=Path.cwd(); KEY='2026-정오표1차/토목/7-4-3/배송관진수'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
audit=json.loads((ROOT/'evals/runtime_validation/per-unit-7-4-3-exact-table-continuation-2026-10-19.json').read_text(encoding='utf8'))
assert audit['status']=='pass' and audit['independent_source_cells']==30 and audit['exact_runtime_scenarios']==60 and audit['format_citation_preflight']=='pass'
p=ROOT/'data/drafts/executable.json'; idx=json.loads(p.read_text(encoding='utf8'))
if KEY not in idx['executable']:
 r=next(x for x in idx['failed'] if x['id']==KEY); assert r['stage']=='calculator_execution_or_rule_gate',r
 idx['failed']=[x for x in idx['failed'] if x['id']!=KEY];idx['executable']=sorted([*idx['executable'],KEY]);idx['summary']['by_calc_type']['per_unit']['executable']+=1
idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(x) for x in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)];p.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
stages=dict(Counter(x['stage'] for x in idx['failed']));cur={'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution'],'failure_stages':stages}
cp_path=ROOT/'evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json';cp=json.loads(cp_path.read_text(encoding='utf8'));cp['previous_active_lists']=cp['current_active_lists'];cp['current_active_lists']=cur;cp.setdefault('source_checks',{})['토목/7-4-3']='Original PDF physical pp.450-451 (printed pp.394-395): all 30 labor/equipment cells across the p450-t2 base and p451-t0 continuation were independently compared. Exact diameter routing 200-610→p450-t2 and 630-860→p451-t0 was tested at 60 scenarios (15 diameters × 2 pipe types × quantities 1/2), yielding 120 exact rate citations. Format/citation preflight passed.'
if KEY not in cp.setdefault('promoted',[]):cp['promoted'].append(KEY)
cp.setdefault('validation',{})['civil_7_4_3_continuation']=audit
add=cp.setdefault('source_evidence_added_this_continuation',{'sections':0,'cells':0,'breakdown':{}}); b=add.setdefault('breakdown',{})
if '토목/7-4-3 exact continuation' not in b:add['sections']+=1;add['cells']+=30;b['토목/7-4-3 exact continuation']=30
cp['remaining_failures']={'calculator_or_rule_gate':stages.get('calculator_execution_or_rule_gate',0),'source_preflight':stages.get('source_preflight',0),'format_preflight':stages.get('format_or_input_preflight',0),'open_policy':cp['remaining_failures']['open_policy']}
specroot=ROOT/'data/drafts/specs';entries=[x.relative_to(specroot).as_posix().encode()+b'\0'+sha(x).encode() for x in sorted(specroot.rglob('*.json'))]
cp['hashes'].update({'spec_count':len(entries),'spec_manifest_sha256':hashlib.sha256(b'\n'.join(entries)).hexdigest(),'chunks_sha256':sha(ROOT/'data/processed/chunks.all.jsonl'),'executable_sha256':sha(p),'runtime_per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py'),'validator_sha256':sha(ROOT/'pipeline/validate_drafts.py')})
cp_path.write_text(json.dumps(cp,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
report={'promoted':KEY,'current_active_lists':cur,'audit':audit,'reused':'unaffected saved validations; no full inventory replay','rerun':'30 source cells, 60 exact calculation scenarios, 120 citations, format/citation preflight','hashes':cp['hashes'],'full_rule_verification':0}
(ROOT/'evals/runtime_validation/executable-7-4-3-continuation-promotion-2026-10-19.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'promoted':KEY,'current_active_lists':cur,'hashes':cp['hashes']},ensure_ascii=False,indent=2))
