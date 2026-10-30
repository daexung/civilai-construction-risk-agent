import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=next(p for p in (root/'data/drafts/specs').rglob('*.json') if (lambda d:d.get('division')=='기계설비' and d.get('section_no')=='13-2-3')(json.loads(p.read_text(encoding='utf8'))['draft']))
d=json.loads(path.read_text(encoding='utf8'))['draft']
out={'id':d['id'],'inputs':[(x['name'],x.get('allowed_values'),x.get('unit')) for x in d['inputs']],'params':d['quantity_model']['params'],'tables':[{'id':t['id'],'rows':list(t['values'].items())[:2]} for t in d['tables']]}
(root/'evals/runtime_validation/13-2-3-axis-sample.txt').write_text(json.dumps(out,ensure_ascii=True,indent=2),encoding='utf8')
