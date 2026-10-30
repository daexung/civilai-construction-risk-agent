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
PATH=ROOT/'data/drafts/specs/토목/9-18-6.json';pkg=json.loads(PATH.read_text(encoding='utf-8'));spec=pkg['draft']
component={'지적기사':[Fraction('0.001'),Fraction('0.001')],
           '지적산업기사':[Fraction('0.001'),Fraction('0.001'),Fraction('0.010'),Fraction('0.002')],
           '지적기능사':[Fraction('0.010')]}
expected={'지적기사':Fraction('0.002'),'지적산업기사':Fraction('0.014'),'지적기능사':Fraction('0.010')}
assert {k:sum(v,Fraction()) for k,v in component.items()}==expected
assert {k:Fraction(spec['tables'][0]['values'][f'합계 / {k}']['인원수']) for k in expected}==expected
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=pdf[621]
assert '9-18-6 연속지적도 품질개선(수치)' in page.get_text()
assert all(v in page.get_text() for v in ['0.001','0.002','0.010','0.014'])
assert '기계경비' in page.get_text() and '별도 계상' in page.get_text()
cases=[]
for q in ('1','25','1000'):
 r=per_unit(spec,{'quantity':q},labor_only=True);assert r['status']=='computed',r
 got={x['name']:Fraction(x['exact']) for x in r['unit_lines']}
 assert got==expected
 assert all(x.get('citations') for x in r['unit_lines']);cases.append(q)
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
version=select_rate_version('2026-10-19');result=per_unit(spec,{'quantity':'25'},labor_only=True)
priced=price_unit(spec,result['unit_lines'],version,{'quantity':'25'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
 node=compute({'spec_id':spec['id'],'inputs':{'quantity':'25'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','total_row_source_cells':3,
 'component_cells_checked':7,'component_sums_match_total':True,'cases':cases,
 'unit':'인/도곽','source_page_physical':622,'printed_page':566,
 'interior_parentheses':'preserved; source note defines parentheses as in-house; empty external subtotal not treated as a rate',
 'equipment_and_material_costs':'excluded from this labor total per source note; no invented estimate',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/civil-9-18-6-cadastral-map-quality-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
