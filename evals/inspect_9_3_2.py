import json
from pathlib import Path
path=next(p for p in (Path(__file__).resolve().parents[1]/'data/drafts/specs').rglob('*.json')
          if (lambda d: d.get('division')=='기계설비' and d.get('section_no')=='9-3-2')
          (json.loads(p.read_text(encoding='utf8'))['draft']))
d=json.loads(path.read_text(encoding='utf8'))['draft']
out={'id':d['id'],'params':d['quantity_model']['params'],'tables':[{'id':t['id'],'rows':list(t['values'].items())[:2]} for t in d['tables']]}
(Path(__file__).resolve().parents[1]/'evals/runtime_validation/9-3-2-axis-sample.txt').write_text(json.dumps(out,ensure_ascii=True,indent=2),encoding='utf8')
