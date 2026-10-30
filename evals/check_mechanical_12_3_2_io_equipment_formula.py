from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/'data/drafts/specs/기계설비/12-3-2.json';pkg=json.loads(PATH.read_text(encoding='utf-8'));spec=pkg['draft']
expected={'설치':{'기사':Fraction('0.008'),'계장공':Fraction('0.042')},
          '점검·시험':{'기사':Fraction('0.046'),'계장공':Fraction('0.080')}}
assert {k:{t:Fraction(v) for t,v in cols.items()} for k,cols in spec['tables'][0]['values'].items()}==expected
assert spec['tables'][1]['values']=={'가산율':{'3개월':'20%','6개월':'40%'}}
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=pdf[777];compact=''.join(page.get_text().split())
assert '12-3-2' in page.get_text() and 'I/O Equipment' in page.get_text()
assert all(v in page.get_text() for v in ['0.008','0.042','0.046','0.080']) and '20%' in compact and '40%' in compact
cases=[]
for qty in ('1','100','1000'):
 for duration in ('지원 없음','3개월','6개월'):
  result=formula_quantity(spec,{'quantity':qty,'support_period':duration});assert result['status']=='computed',result
  got={x['name']:Fraction(x['exact']) for x in result['unit_lines']}
  expected_lines={f'{task} {trade}':rate*int(qty) for task,cols in expected.items() for trade,rate in cols.items()}
  if duration!='지원 없음':
   factor=Fraction(1,5) if duration=='3개월' else Fraction(2,5)
   expected_lines.update({f'운영관리지원 {duration} 점검·시험 {trade}':rate*int(qty)*factor
                          for trade,rate in expected['점검·시험'].items()})
  assert got==expected_lines,(qty,duration,got,expected_lines)
  for line in result['unit_lines']:
   assert len(line['citations'])==(2 if line['name'].startswith('운영관리지원') else 1)
  cases.append(f'{qty}/{duration}')
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
version=select_rate_version('2026-10-19');sample=formula_quantity(spec,{'quantity':'100','support_period':'3개월'})
priced=price_unit(spec,sample['unit_lines'],version,{'quantity':'100','support_period':'3개월'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
 node=compute({'spec_id':spec['id'],'inputs':{'quantity':'100','support_period':'3개월'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','base_labor_cells':4,'support_percentage_cells':2,
 'cases':len(cases),'quantity_period_cases':cases,'support_basis':'20%/40% applied separately to cited inspection/test rate for each profession',
 'separate_costs':'wiring, communications lines and DDC outer box remain excluded per source note',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/mechanical-12-3-2-io-equipment-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
