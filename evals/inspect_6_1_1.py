import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.agent.tools.calc.per_unit import per_unit
p=next(p for p in Path('data/drafts/specs').rglob('*.json') if json.loads(p.read_text(encoding='utf8'))['draft'].get('section_no')=='6-1-1' and json.loads(p.read_text(encoding='utf8'))['draft'].get('division')=='기계설비')
d=json.loads(p.read_text(encoding='utf8'))['draft']
for row in d['tables'][0]['values']:
 r=per_unit(d,{'meter_size':row,'install_item':'보호통','quantity':'1','is_irregular_condition':False,'is_parallel_install':False})
 print(json.dumps({'row':row,'status':r.get('status'),'reason':r.get('reason'),'lines':r.get('unit_lines')},ensure_ascii=True))
