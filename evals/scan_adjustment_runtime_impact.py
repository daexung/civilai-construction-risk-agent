import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.adjustments import _target,_norm,_percent_values
idx=json.loads((ROOT/'data/drafts/executable.json').read_text(encoding='utf-8'));active=set(idx['executable']);hits=[]
for p in (ROOT/'data/drafts/specs').rglob('*.json'):
 d=json.loads(p.read_text(encoding='utf-8'))['draft']
 if d['id'] not in active:continue
 for item in d.get('quantity_model',{}).get('params',{}).get('surcharges',[])+d.get('quantity_model',{}).get('params',{}).get('note_adjustments',[]):
  target=_target(item)
  if target is None or item.get('rate_table'):continue
  conditions={**{f['name']:f['allowed_values'][0] for f in d.get('inputs',[]) if f.get('type')=='enum'},**{k:v for k,v in (item.get('when') or {}).items() if not (isinstance(v,str) and re.match(r'\s*[<>!=]',v))}}
  for t in d.get('tables',[]):
   found=False
   for row,cols in t.get('values',{}).items():
    for col,raw in cols.items():
     if '%' in str(raw) and any(_norm(v)==_norm(col) or _norm(v)==_norm(row) for v in conditions.values()) and target in _percent_values(str(raw)):
      hits.append({'id':d['id'],'table':t['id'],'row':row,'column':col,'raw':raw});found=True;break
    if found:break
out={'scan_scope':'static scan over active executable specs for rate items matching textual percent cells that the adjustments runtime change can now resolve','active_executable_ids':len(active),'potential_cell_matches':len(hits),'unique_affected_ids':sorted({x['id'] for x in hits}),'cell_matches':hits,'focused_reruns':['2026-정오표1차/건축/11-1-1/콘크리트_모르타르면_바탕만들기: 28 combinations; eight optional yes/no adjustment branches; computed or blocked','2026-정오표1차/건축/9-1-4/표면마무리: four combinations; computed or blocked','2026-정오표1차/공통/2-8-11/안전난간대설치및해체: 12 combinations; computed'],'shared_tests':['check_adjustments.py 20/20','check_per_unit.py 44/44','check_cost_statement.py 8/8']}
(ROOT/'evals/runtime_validation/adjustment-runtime-impact-2026-10-19.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'active':len(active),'potential_cell_matches':len(hits),'unique_ids':len(out['unique_affected_ids']),'ids':[x.split('/')[-2] for x in out['unique_affected_ids']]},ensure_ascii=True))
