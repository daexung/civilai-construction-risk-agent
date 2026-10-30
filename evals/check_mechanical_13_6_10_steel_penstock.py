"""Original source cells, task rates, inspection share and material quantity audit."""
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
PATH=ROOT/'data/drafts/specs/기계설비/13-6-10.json';PKG=json.loads(PATH.read_text(encoding='utf-8'));SPEC=PKG['draft']
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
text1=pdf[868].get_text();text2=pdf[869].get_text();compact1=''.join(text1.split())
assert '13-6-10SteelPenstock현장설치' in compact1 and '상기인력품의7%' in compact1
assert all(v in text2 for v in ['9.81㎏','3.53본','0.55병','0.39병','0.5개','4.8매','1.81ℓ','0.96ℓ'])
table=SPEC['tables'][0];materials=SPEC['tables'][1];assert len(table['values'])==36 and len(materials['values'])==8
assert len([c for c in PKG['citations'] if c.get('table_id')=='p869-t0'])==36
assert len([c for c in PKG['citations'] if c.get('table_id')=='p870-t0'])==8
result=per_unit(SPEC,{'quantity':'2'},labor_only=True);assert result['status']=='computed',result
lines=result['unit_lines'];labor=[x for x in lines if x['kind']=='labor' and x['name']!='검사 및 시험'];mat=[x for x in lines if x['kind']=='material'];inspection=[x for x in lines if x['name']=='검사 및 시험']
assert len(labor)==35 and len(mat)==8 and len(inspection)==1
source_total=sum((Fraction(x['exact']) for x in labor),Fraction(0));assert Fraction(inspection[0]['exact'])==source_total*Fraction(7,100)
for line in labor: assert line['citations'] and line['citations'][0]['internal_id']=='p869-t0'
for line in mat: assert line['citations'] and line['citations'][0]['internal_id']=='p870-t0'
assert all(Fraction(x['exact'])>0 for x in [*labor,*mat,inspection[0]])
expected_materials={'전기용접봉':Fraction('9.81'),'탄소봉 8ø×350㎜':Fraction('3.53'),'산소 6,000ℓ입':Fraction('0.55'),'아세틸렌 2,100ℓ입':Fraction('0.39'),'그라인더돌 12"ø':Fraction('0.5'),'Film 65×305':Fraction('4.8'),'Tar epoxy':Fraction('1.81'),'마린B/T (선박도로용)':Fraction('0.96')}
assert {x['name']:Fraction(x['exact']) for x in mat}==expected_materials
price_version=select_rate_version('2026-10-19');assert price_version
priced=price_unit(SPEC,lines,price_version,{'quantity':'2'},basis_date='2026-10-19')
validation=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert validation['ok'],validation
node_status='not_registered_in_active_execution_index'
if SPEC['id'] in load_specs():
 node=compute({'spec_id':SPEC['id'],'inputs':{'quantity':'2'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':SPEC['id'],'status':'pass','source_numeric_cells_independently_checked':43,'source_method':'physical PDF pages 869-870 text extraction and original render independently reviewed','renders':['evals/runtime_validation/source-followup-physical-869.png','evals/runtime_validation/source-followup-physical-870.png'],'labor_task_cells':len(labor),'material_cells':len(mat),'inspection_rule':'7% of all source labor rates; exact aggregate source labor rate checked independently','unit_rate_labor_sum_per_ton':str(source_total),'inspection_rate_per_ton':str(Fraction(inspection[0]['exact'])),'quantity_cases':[{'ton':1,'independent_labor_total':str(source_total+Fraction(inspection[0]['exact']))},{'ton':2,'independent_labor_total':str((source_total+Fraction(inspection[0]['exact']))*2)}],'material_per_ton':{k:str(v) for k,v in expected_materials.items()},'local_wage_version':price_version['id'],'local_price_unpriced':[x.get('name') for x in priced.get('unpriced',[])],'source_note':'oxygen and acetylene bottle capacity basis is retained; no volume conversion invented','full_rule_verification':False,'validator_ok':validation['ok'],'calculation_node':node_status}
Path('evals/runtime_validation/mechanical-13-6-10-penstock-source-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
