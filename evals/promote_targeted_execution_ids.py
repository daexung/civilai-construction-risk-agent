import json
from pathlib import Path
p=Path('data/drafts/executable.json'); idx=json.loads(p.read_text(encoding='utf-8'))
evidence=json.loads(Path('evals/runtime_validation/targeted-execution-subset-2026-10-19.json').read_text(encoding='utf-8'))
promote=[x['id'] for x in evidence['results'] if x['basic_executable'] and x['id'].split('/')[-2] in {'11-1-3','12-2-4','12-2-5','12-3-1','13-1-1'}]
assert len(promote)==5, promote
failed={x['id']:x for x in idx['failed']}
assert all(i in failed for i in promote)
old=idx['summary']['failure_reasons_top10']
idx['executable']=sorted(set(idx['executable'])|set(promote))
idx['failed']=[x for x in idx['failed'] if x['id'] not in set(promote)]
idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed'])
idx['summary']['by_calc_type']['per_unit']['executable']+=len(promote)
idx['summary']['by_scope']['기타']['executable']+=len(promote)
counts={}
for item in idx['failed']:
 reason=item['reason']
 if reason.startswith('기본 조합 '): key=reason.split(':',1)[0]
 else:key=reason
 counts[key]=counts.get(key,0)+1
idx['summary']['failure_reasons_top10']=sorted(counts.items(),key=lambda x:(-x[1],x[0]))[:10]
p.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
result={'promoted_ids':promote,'previous_counts':{'executable':811,'failed':75,'unsupported':170,'excluded':2},'current_counts':{'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},'failure_reason_top10_before':old,'failure_reason_top10_after':idx['summary']['failure_reasons_top10']}
Path('evals/runtime_validation/targeted-index-update-2026-10-19.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
