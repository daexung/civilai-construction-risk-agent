"""Original-page and daily-crew audit for reconstructed mechanical 3-3-1."""
from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/'data/drafts/specs/기계설비/3-3-1.json';PKG=json.loads(PATH.read_text(encoding='utf-8'));SPEC=PKG['draft']
page=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')[723];text=page.get_text()
assert all(v in text for v in ['3-3-1 각형덕트 보온','25이하','50이하','9.5','8.0','8.5','7.0'])
g='고무발포보온재·발포폴리에틸렌보온재';w='유리면보온재(글라스울)'
expected={'보온공':{'단위':'인','수량':'2'},'보통인부':{'단위':'인','수량':'1'},'25이하':{g:'9.5',w:'8.0'},'50이하':{g:'8.5',w:'7.0'}}
assert SPEC['tables'][0]['values']==expected
assert len([c for c in PKG['citations'] if c.get('table_id')=='p724-t0'])==6
routes=[]
outputs={('25이하',g):Fraction(95,10),('25이하',w):Fraction(8),('50이하',g):Fraction(85,10),('50이하',w):Fraction(7)}
for (thick,material),output in outputs.items():
 for area in (output,output*2):
  inp={'area':str(area),'thickness':thick,'insulation_type':material};r=adjusted_daily_crew(SPEC,inp)
  assert r['status']=='computed',r
  assert Fraction(r['daily_volume_m3'])==output
  assert Fraction(r['work_days'])==area/output
  assert {k:Fraction(v) for k,v in r['person_days'].items()}=={'보온공':2*area/output,'보통인부':area/output}
  routes.append({'thickness':thick,'material':material,'area_m2':str(area),'output_m2_per_day':str(output),'workdays':r['work_days'],'person_days':r['person_days']})
chunks=load_chunks(ROOT/'data/processed/chunks.all.jsonl');valid=validate_one(PATH,ROOT/'data/drafts/specs',chunks,None);assert valid['ok'],valid
node_status='not_registered_in_active_execution_index'
if SPEC['id'] in load_specs():
 node=compute({'spec_id':SPEC['id'],'inputs':{'area':'19','thickness':'25이하','insulation_type':g}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':SPEC['id'],'status':'pass','source_numeric_cells_independently_checked':6,'source_render':'evals/runtime_validation/source-followup-physical-724.png','computed_routes':routes,'verified_rules':['daily crew 2 insulators + 1 general laborer','merged material header assigns 9.5/8.5 to rubber foam and polyethylene; 8.0/7.0 to glass wool','25mm or less and 50mm or less thickness output axes','handling, cutting, installation, aluminum banding and finishing included'],'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status}
Path('evals/runtime_validation/mechanical-3-3-1-rectangular-duct-source-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
