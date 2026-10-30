import json,sys,itertools
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.adjustments import adjustment_questions
from evals.check_draft_executability import _values
TARGETS={
'2026-정오표1차/기계설비/13-1-1/플랜트배관설치','2026-정오표1차/기계설비/11-1-3/나사식접합및배관','2026-정오표1차/기계설비/12-2-4/Control_Air_배관','2026-정오표1차/기계설비/12-2-5/압축공기발생장치및공기관배관','2026-정오표1차/기계설비/12-3-1/중앙처리장치설치',
'2026-정오표1차/기계설비/8-3-1/보일러설치','2026-정오표1차/기계설비/2-2-2/흡입구설치','2026-정오표1차/기계설비/8-5-1/오일서비스탱크설치',
'2026-정오표1차/건축/11-1-1/콘크리트_모르타르면_바탕만들기','2026-정오표1차/건축/9-1-4/표면마무리','2026-정오표1차/공통/2-8-11/안전난간대설치및해체'}
results=[]
for sp in (ROOT/'data/drafts/specs').rglob('*.json'):
 s=json.loads(sp.read_text(encoding='utf-8'))['draft']
 if s['id'] not in TARGETS:continue
 fields=s['inputs'];p=s['quantity_model']['params'];b=defaultdict(list)
 for x in s.get('blocked',[]):
  c=x.get('blocked_if')
  if c:b[c['input']].append(c)
 choices=[_values(f,b[f['name']],p.get('surcharges',[])+p.get('note_adjustments',[])) for f in fields]
 seen={};failure=None
 for ix,v in enumerate(itertools.islice(itertools.product(*choices),64)):
  i=dict(zip((f['name'] for f in fields),v));r=per_unit(s,i);st=r.get('status');seen[st]=seen.get(st,0)+1
  if st=='ask':
   qs=r.get('questions',[])
   if not qs or any(q.get('default') is not None for q in qs):failure={'index':ix,'status':st,'reason':'invalid adjustment question/default'};break
   for answer in ('예','아니오'):
    rr=per_unit(s,{**i,**{q['name']:answer for q in qs}})
    if rr.get('status') not in ('computed','blocked'):
     failure={'index':ix,'status':'answered_'+rr.get('status'),'reason':rr.get('reason')};break
   if failure:break
   st='computed'
  if ix==0 and st!='computed':failure={'index':ix,'status':st,'reason':r.get('reason')};break
  if st not in ('computed','blocked'):
   failure={'index':ix,'status':st,'reason':r.get('reason')};break
 results.append({'id':s['id'],'samples_checked':sum(seen.values()),'first_status':next(iter(seen),'none'),'status_counts':seen,'failure':failure,'basic_executable':failure is None})
out={'scope':'five repaired failures and three existing executable IDs in the runtime impact scan','results':results}
(ROOT/'evals/runtime_validation/targeted-execution-subset-2026-10-19.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps([{'id':x['id'].split('/')[-2]+'/'+x['id'].split('/')[-1],'checked':x['samples_checked'],'status':x['status_counts'],'ok':x['basic_executable']} for x in results],ensure_ascii=True))
