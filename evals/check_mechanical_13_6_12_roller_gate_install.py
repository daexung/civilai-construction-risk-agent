"""Independent source-cell and calculator audit for the 13-6-12 repair."""
from __future__ import annotations
import json, sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one

PATH=ROOT/'data/drafts/specs/기계설비/13-6-12.json'
pkg=json.loads(PATH.read_text(encoding='utf-8')); spec=pkg['draft']
expected_p871=[('기계기사','5.33'),('목공','0.34'),('특별인부','0.34'),
 ('플랜트기계설치공','0.17'),('특별인부','0.17'),('플랜트기계설치공','0.34'),('특별인부','0.17')]
expected_p872=[('석공','1.15'),('특별인부','0.86'),('플랜트기계설치공','0.19'),('플랜트배관공','0.19'),
 ('산소절단공','0.12'),('플랜트용접공','0.12'),('특별인부','0.51'),('산소절단공','0.56'),
 ('플랜트기계설치공','0.56'),('특별인부','1.12'),('특수비계공','0.79'),('플랜트기계설치공','0.59'),
 ('산소절단공','0.29'),('플랜트기계설치공','0.29'),('플랜트용접공','1.6'),('특별인부','2.77'),
 ('특수비계공','0.79'),('플랜트용접공','4.9'),('측량사','0.59'),('측량조수','0.59'),
 ('산소절단공','0.59'),('플랜트기계설치공','1.48'),('특별인부','7.76'),('산소절단공','0.21'),
 ('플랜트용접공','1.6'),('특별인부','1.81'),('측량사','0.29'),('측량조수','0.29'),
 ('플랜트기계설치공','0.73'),('특별인부','2.29'),('도장공','0.067'),('특별인부','0.033'),
 ('특수비계공','0.22'),('플랜트기계설치공','0.34'),('산소절단공','0.22'),('특별인부','0.56'),
 ('플랜트전공','4.25'),('특별인부','4.25')]
expected_materials=[('산소 6,000ℓ입','0.69','병'),('아세틸렌 2,100ℓ입','0.2','병'),
 ('용접봉','31.05','kg'),('Tar Epoxy 2회','0.536','ℓ')]
assert len(expected_p871)==7 and len(expected_p872)==38 and len(expected_materials)==4
assert [len(t['values']) for t in spec['tables']]==[7,38,4]
for table, expected, start in zip(spec['tables'][:2],[expected_p871,expected_p872],[1,8]):
    actual=[(row.split(' / ',1)[1],cells['인/ton']) for row,cells in table['values'].items()]
    assert actual==expected,(table['id'],actual)
    assert all(row.startswith(f'원문행 {i:02d} / ') for i,row in enumerate(table['values'],start))
actual_materials=[]
for i,(name,value,unit) in enumerate(expected_materials,1):
    row=f'원문자재 {i:02d} / {name}'
    actual_materials.append((name,spec['tables'][2]['values'][row]['수량'],unit))
assert actual_materials==expected_materials
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
p871,p872,p873=(pdf[i].get_text() for i in (870,871,872))
assert '13-6-12 Roller Gate Guide Metal 설치' in p871
assert all(v in p872 for v in ['1.15','0.86','0.19','0.12','0.51','0.56','1.12','0.79','0.59','0.29','1.6','2.77','4.9','1.48','7.76','0.21','1.81','0.73','2.29','0.067','0.033','0.22','0.34','4.25'])
assert all(v in p873 for v in ['0.69','0.2','31.05','0.536'])
result=per_unit(spec,{'quantity':'2'},labor_only=True);assert result['status']=='computed',result
lines=result['unit_lines'];labor=[x for x in lines if x['kind']=='labor']
material=[x for x in lines if x['kind']=='material']
assert len(labor)==45 and len(material)==4 and len(lines)==49
labor_sum=sum((Fraction(x['exact']) for x in labor),Fraction())
assert labor_sum==Fraction('52.43')
assert len({(x['citations'][0]['internal_id'],x['citations'][0]['row']) for x in labor})==45
assert all(x['citations'] and x['citations'][0]['internal_id']=='p873-t0' for x in material)
expected_qty={name:Fraction(value) for name,value,_ in expected_materials}
assert {x['name']:Fraction(x['exact']) for x in material}==expected_qty
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None)
assert valid['ok'],valid
version=select_rate_version('2026-10-19'); priced=price_unit(spec,lines,version,{'quantity':'2'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
    node=compute({'spec_id':spec['id'],'inputs':{'quantity':'2'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','original_numeric_rate_cells':49,'labor_rows':45,
 'material_cells':4,'labor_rate_sum_per_ton':str(labor_sum),
 'source_pages_physical':[871,872,873],'merged_process_labels':'retained as row-order source evidence; no inferred row assignment or process subtotals',
 'inspection_rate':'none applied; adjacent 13-6-11 source rule is not presumed for 13-6-12',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/mechanical-13-6-12-roller-gate-install-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(audit,ensure_ascii=False,indent=2))
