from __future__ import annotations
import json,sys,re
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/'data/drafts/specs/기계설비/13-6-8.json';pkg=json.loads(PATH.read_text(encoding='utf-8'));spec=pkg['draft']
assert [len(t['values']) for t in spec['tables']]==[31,34,13,7]
pdf=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
regions=[(863,(117,651)),(864,(68,668)),(865,(68,335)),(865,(389,540))]
for table,(page_no,(y0,y1)) in zip(spec['tables'],regions):
 source=[]
 for word in pdf[page_no].get_text('words'):
  if y0<=word[1]<=y1 and word[0]>480 and re.search(r'\d',word[4]):
   m=re.search(r'\d+(?:\.\d+)?',word[4]);source.append(m.group(0))
 if table['id']=='p866-t1': expected=[v['수량'] for v in table['values'].values()]
 else: expected=[v['인/ton'] for v in table['values'].values()]
 assert source==expected,(table['id'],source,expected)
assert '13-6-8 Spiral Casing 설치' in pdf[863].get_text()
assert '7%' in ''.join(pdf[865].get_text().split())
r=per_unit(spec,{'quantity':'1'},labor_only=True);assert r['status']=='computed',r
lines=r['unit_lines'];labor=[x for x in lines if x['kind']=='labor' and x['name']!='검사'];materials=[x for x in lines if x['kind']=='material'];inspection=[x for x in lines if x['name']=='검사']
assert (len(labor),len(materials),len(inspection))==(78,7,1)
labor_total=sum((Fraction(x['exact']) for x in labor),Fraction())
assert Fraction(inspection[0]['exact'])==labor_total*Fraction(7,100)
assert all(x.get('citations') for x in labor+materials+inspection)
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
version=select_rate_version('2026-10-19');priced=price_unit(spec,lines,version,{'quantity':'1'},basis_date='2026-10-19')
node_status='not_registered_in_active_execution_index'
if spec['id'] in load_specs():
 node=compute({'spec_id':spec['id'],'inputs':{'quantity':'1'}});assert node['status']=='COMPUTED',node;node_status=node['status']
audit={'id':spec['id'],'status':'pass','numeric_source_cells':85,'labor_rows':78,'material_cells':7,
 'original_pdf_numeric_cells':{'p864-t0':31,'p865-t0':34,'p866-t0':13,'p866-t1':7},
 'labor_rate_sum_per_ton':str(labor_total),'inspection_rate':'7% of total labor, independently recomputed',
 'merged_process_cells':'not assigned to row subtotals; all row/trade/rate values use visual source review and source-order cell audit',
 'gas_bottle_basis':'35℃ / 150 atm note retained; no volume conversion',
 'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status,
 'local_wage_version':version['id'],'unpriced_local_catalog_items':[x.get('name') for x in priced.get('unpriced',[])]}
out=ROOT/'evals/runtime_validation/mechanical-13-6-8-spiral-casing-source-audit-2026-10-19.json'
out.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
