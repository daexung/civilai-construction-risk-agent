"""Independent source, task-rate, inspection and material audit for 13-6-11."""
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
PATH=ROOT/'data/drafts/specs/기계설비/13-6-11.json';PKG=json.loads(PATH.read_text(encoding='utf-8'));SPEC=PKG['draft']
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');a=pdf[869].get_text();b=pdf[870].get_text();compactb=''.join(b.split())
assert '13-6-11 Roller Gate Guide Metal 제작' in a and '13-6-12 Roller Gate Guide Metal 설치' in b and '인력품의7%' in compactb
assert all(v in b for v in ['2.3병','1.6병','1.9매','54.6㎏','0.018㎥','0.0018D/M','0.037개','0.14㎏','0.75ℓ','550㎾h','0.3개'])
assert [len(t['values']) for t in SPEC['tables']]==[18,8,11]
assert sum(c.get('table_id') in ('p870-t1','p871-t0') for c in PKG['citations'])==26
assert sum(c.get('table_id')=='p871-t1' for c in PKG['citations'])==11
r=per_unit(SPEC,{'quantity':'2'},labor_only=True);assert r['status']=='computed',r
lines=r['unit_lines'];labor=[x for x in lines if x['kind']=='labor' and x['name']!='검사'];materials=[x for x in lines if x['kind']=='material'];check=[x for x in lines if x['name']=='검사']
assert len(labor)==25 and len(materials)==11 and len(check)==1
source_total=sum((Fraction(x['exact']) for x in labor),Fraction(0));assert Fraction(check[0]['exact'])==source_total*Fraction(7,100)
assert all(x['citations'] and x['citations'][0]['internal_id'] in ('p870-t1','p871-t0') for x in labor)
assert all(x['citations'] and x['citations'][0]['internal_id']=='p871-t1' for x in materials)
expected={'산소 6,000ℓ입':Fraction('2.3'),'아세틸렌 2,100ℓ입':Fraction('1.6'),"함석 #32×3'×6'":Fraction('1.9'),'용접봉':Fraction('54.6'),'규사':Fraction('0.018'),'중유':Fraction('0.0018'),'노즐':Fraction('0.037'),'Zinc primer 15μ':Fraction('0.14'),'Tar Epoxy 125μ':Fraction('0.75'),'전기':Fraction('550'),'그라인더돌 12"ø':Fraction('0.3')}
assert {x['name']:Fraction(x['exact']) for x in materials}==expected
version=select_rate_version('2026-10-19');assert version
priced=price_unit(SPEC,lines,version,{'quantity':'2'},basis_date='2026-10-19')
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
node_status='not_registered_in_active_execution_index'
if SPEC['id'] in load_specs():
 node=compute({'spec_id':SPEC['id'],'inputs':{'quantity':'2'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':SPEC['id'],'status':'pass','independent_numeric_cells':37,'source_pages_physical':[870,871],'source_renders':['evals/runtime_validation/source-followup-physical-870.png','evals/runtime_validation/source-followup-physical-871.png'],'labor_task_cells':25,'material_cells':11,'inspection_rate':'7% of all 25 labor task rates','labor_rate_sum_per_ton':str(source_total),'inspection_rate_per_ton':str(Fraction(check[0]['exact'])),'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])],'oxygen_note':'35℃ / 150 atm bottle basis preserved; no gas volume conversion inferred','full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status}
Path('evals/runtime_validation/mechanical-13-6-11-roller-gate-fabrication-source-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
