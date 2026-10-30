import json
from pathlib import Path
p=Path('data/drafts/executable.json');idx=json.loads(p.read_text(encoding='utf-8'))
proof=json.loads(Path('evals/runtime_validation/targeted-execution-subset-2026-10-19.json').read_text(encoding='utf-8'))
ident='2026-정오표1차/기계설비/2-2-2/흡입구설치';ev=next(x for x in proof['results'] if x['id']==ident);assert ev['basic_executable'] and ev['samples_checked']==21,ev
failure=next(x for x in idx['failed'] if x['id']==ident)
idx['failed']=[x for x in idx['failed'] if x['id']!=ident];idx['executable']=sorted(set(idx['executable'])|{ident})
idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['by_calc_type']['per_unit']['executable']+=1;idx['summary']['by_scope']['기타']['executable']+=1
counts={}
for item in idx['failed']:
 r=item['reason'];key=r.split(':',1)[0] if r.startswith('기본 조합 ') else r;counts[key]=counts.get(key,0)+1
idx['summary']['failure_reasons_top10']=sorted(counts.items(),key=lambda x:(-x[1],x[0]))[:10]
p.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
out={'previous_counts':{'executable':817,'failed':69,'unsupported':170,'excluded':2},'current_counts':{'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},'promoted_id':ident,'previous_failure_reason':failure['reason'],'verification':ev}
Path('evals/runtime_validation/targeted-index-update-inlet-2026-10-19.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:out[k] for k in ('previous_counts','current_counts','promoted_id')},ensure_ascii=False))
