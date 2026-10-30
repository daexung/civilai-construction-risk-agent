from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/'data/drafts/specs/유지관리/3-2-12.json';pkg=json.loads(PATH.read_text(encoding='utf-8'));spec=pkg['draft']
expected={'내장재':{'석면해체공':Fraction('0.120'),'보통인부':Fraction('0.017')},
          '외장재':{'석면해체공':Fraction('0.045'),'보통인부':Fraction('0.011')},
          '뿜칠재':{'석면해체공':Fraction('0.5'),'보통인부':None}}
assert spec['tables'][0]['values']['석면해체공']=={'내장재':'0.120','외장재':'0.045','뿜칠재':'0.5'}
assert spec['tables'][0]['values']['보통인부']=={'내장재':'0.017','외장재':'0.011','뿜칠재':'-'}
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=pdf[972]
assert '3-2-12 석면건축자재 해체' in page.get_text() and '0.120' in page.get_text() and '0.045' in page.get_text() and '0.017' in page.get_text() and '0.011' in page.get_text()
assert '20%' in ''.join(page.get_text().split())
cases=0
for mat,rates in expected.items():
 for surface in ('철골면','콘크리트면'):
  for qty in ('1','10','100'):
   r=per_unit(spec,{'material_type':mat,'spray_surface':surface,'quantity':qty},labor_only=True);assert r['status']=='computed',r
   lines=r['unit_lines'];cases+=1
   if mat=='뿜칠재':
    factor=Fraction('1.2') if surface=='콘크리트면' else Fraction(1)
    assert len(lines)==1 and lines[0]['name']=='석면해체공'
    assert Fraction(lines[0]['exact'])==rates['석면해체공']*factor
   else:
    assert len(lines)==2
    assert {x['name']:Fraction(x['exact']) for x in lines}==rates
   assert all(x.get('citations') for x in lines)
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
version=select_rate_version('2026-10-19');sample=per_unit(spec,{'material_type':'뿜칠재','spray_surface':'콘크리트면','quantity':'10'},labor_only=True)
priced=price_unit(spec,sample['unit_lines'],version,{'material_type':'뿜칠재','spray_surface':'콘크리트면','quantity':'10'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
 node=compute({'spec_id':spec['id'],'inputs':{'material_type':'뿜칠재','spray_surface':'콘크리트면','quantity':'10'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','source_cells_checked':6,'source_table':'physical p973 / printed p917',
 'non_dash_cells':5,'dash_cells':1,'cases':cases,'concrete_spray_multiplier':'1.2, derived independently from stated 20% surcharge',
 'other_rules':'existing exclusion notes remain; no equipment/material cost invented',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/maintenance-3-2-12-asbestos-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
