import json,sys,itertools
from collections import defaultdict
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from evals.check_draft_executability import _values
s=json.loads((ROOT/'data/drafts/specs/건축/11-1-1.json').read_text(encoding='utf-8'))['draft'];p=s['quantity_model']['params'];b=defaultdict(list)
for x in s.get('blocked',[]):
 c=x.get('blocked_if')
 if c:b[c['input']].append(c)
choices=[_values(f,b[f['name']],p.get('surcharges',[])+p.get('note_adjustments',[])) for f in s['inputs']]; seen={};failure=None
for ix,v in enumerate(itertools.islice(itertools.product(*choices),64)):
 i=dict(zip((f['name'] for f in s['inputs']),v));r=per_unit(s,i);st=r.get('status');seen[st]=seen.get(st,0)+1
 if st=='ask':
  qs=r.get('questions',[])
  if not qs or any(q.get('default') is not None for q in qs):failure={'index':ix,'status':st,'reason':'invalid question/default'};break
  for answer in ('예','아니오'):
   rr=per_unit(s,{**i,**{q['name']:answer for q in qs}})
   if rr.get('status') not in ('computed','blocked'):failure={'index':ix,'status':'answered_'+rr.get('status'),'reason':rr.get('reason')};break
  if failure:break
  st='computed'
 if ix==0 and st!='computed':failure={'index':ix,'status':st,'reason':r.get('reason')};break
 if st not in ('computed','blocked'):failure={'index':ix,'status':st,'reason':r.get('reason')};break
out={'id':s['id'],'samples_checked':sum(seen.values()),'status_counts':seen,'failure':failure,'basic_executable':failure is None,'interpretation':'existing executable path retained only after both explicit optional-adjustment answers were exercised'}
(ROOT/'evals/runtime_validation/adjustment-impact-11-1-1-audit-2026-10-19.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in out.items() if k!='id'},ensure_ascii=False))
