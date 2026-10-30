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
PATH=ROOT/'data/drafts/specs/기계설비/13-6-14.json';pkg=json.loads(PATH.read_text(encoding='utf-8'));spec=pkg['draft']
e874=[('기계기사','12.882'),('(해체)목공','4.706'),('플랜트기계설치공','4.706'),('특별인부','4.706'),('석공','3.294'),('특별인부','2.470'),('플랜트기계설치공','1.176'),('플랜트배관공','1.176'),('산소절단공','0.941'),('플랜트용접공','0.588'),('특별인부','4.706'),('특별인부','4.706'),('특수비계공','4.706'),('플랜트기계설치공','4.706'),('플랜트제관공','2.353'),('시공측량기사','9.412'),('시공측량조수','9.412'),('플랜트기계설치공','9.412'),('플랜트기계설치공','9.412'),('플랜트기계설치공','4.706'),('플랜트용접공','4.706'),('특별인부','14.118'),('시공측량기사','2.353')]
e875=[('시공측량조수','2.353'),('플랜트기계설치공','2.353'),('플랜트기계설치공','2.353'),('특별인부','2.353'),('특수비계공','0.624'),('플랜트기계설치공','1.412'),('산소절단공','0.948'),('특별인부','2.353'),('플랜트전공','3.529'),('특별인부','3.529')]
emat=[('산소 6,000ℓ입','0.5','병'),('아세틸렌 2,100ℓ입','0.05','병'),('용접봉 KSE 4301','7','kg')]
assert len(e874)==23 and len(e875)==10 and len(emat)==3
assert [len(t['values']) for t in spec['tables']]==[23,10,3]
for table,exp,start in zip(spec['tables'][:2],[e874,e875],[1,24]):
 assert [(k.split(' / ',1)[1],v['인/ton']) for k,v in table['values'].items()]==exp
 assert all(k.startswith(f'원문행 {i:02d} / ') for i,k in enumerate(table['values'],start))
assert [(name,spec['tables'][2]['values'][f'원문자재 {i:02d} / {name}']['수량'],unit)
 for i,(name,_,unit) in enumerate(emat,1)]==emat
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
p874,p875=pdf[873].get_text(),pdf[874].get_text()
assert '13-6-14 Tainter Gate Guide Metal 설치' in p874
assert all(x in p874 for x in ['12.882','3.294','2.470','0.941','0.588','9.412','14.118'])
assert all(x in p875 for x in ['2.353','0.624','1.412','0.948','3.529','0.5','0.05','7'])
r=per_unit(spec,{'quantity':'2'},labor_only=True);assert r['status']=='computed',r
lines=r['unit_lines'];labor=[x for x in lines if x['kind']=='labor'];materials=[x for x in lines if x['kind']=='material']
assert len(labor)==33 and len(materials)==3 and len(lines)==36
labor_sum=sum((Fraction(x['exact']) for x in labor),Fraction());assert labor_sum==sum((Fraction(v) for _,v in e874+e875),Fraction())
assert all(len(x.get('citations',[])) and x['citations'][0]['internal_id'] in ('p874-t1','p875-t0') for x in labor)
assert {x['name']:Fraction(x['exact']) for x in materials}=={n:Fraction(v) for n,v,_ in emat}
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
version=select_rate_version('2026-10-19');priced=price_unit(spec,lines,version,{'quantity':'2'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
 node=compute({'spec_id':spec['id'],'inputs':{'quantity':'2'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','numeric_source_cells':36,'labor_rows':33,'material_cells':3,
 'labor_rate_sum_per_ton':str(labor_sum),'source_pages_physical':[874,875],
 'process_cells':'merged source labels retained only as context; no inferred process subtotal',
 'gas_basis':'bottle units preserved; 35℃/150 atm condition not converted',
 'inspection_rate':'none applied; no installation inspection multiplier stated in these source pages',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/mechanical-13-6-14-tainter-gate-install-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(audit,ensure_ascii=False,indent=2))
