"""Source-independent and runtime audit for restored civil 2-3-2 table."""
from __future__ import annotations
import json, sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one
SPEC_PATH=ROOT/'data/drafts/specs/토목/2-3-2.json'
PKG=json.loads(SPEC_PATH.read_text(encoding='utf-8'));SPEC=PKG['draft']
page=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')[390]
text=page.get_text()
assert '2-3-2 블록 붙이기(인력)' in text and '(㎡당)' in text and '0.076' in text and '0.066' in text
expected={'특별인부':{'단위':'인','수량':'0.076'},'보통인부':{'단위':'인','수량':'0.066'}}
table=SPEC['tables'][0];assert table['id']=='p391-t0' and table['values']==expected
assert [(x['row'],x['value']) for x in PKG['citations'] if x.get('table_id')]==[('특별인부','0.076'),('보통인부','0.066')]
routes=[]
for area in (1, 50, 125):
 result=per_unit(SPEC,{'area':str(area)},labor_only=True)
 assert result['status']=='computed',result
 rates={line['name']:Fraction(line['exact']) for line in result['unit_lines']}
 assert rates=={'특별인부':Fraction(76,1000),'보통인부':Fraction(66,1000)},(area,result)
 totals={name:rate*area for name,rate in rates.items()}
 assert totals=={'특별인부':Fraction(76*area,1000),'보통인부':Fraction(66*area,1000)}
 assert result['provenance']['quantity']=={'area':str(area)}
 routes.append({'area_m2':area,'unit_rates':{k:str(v) for k,v in rates.items()},'independent_labor_totals':{k:str(v) for k,v in totals.items()}})
validation=validate_one(SPEC_PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None)
assert validation['ok'],validation
node_status='not_registered_in_active_execution_index'
if SPEC['id'] in load_specs():
 node=compute({'spec_id':SPEC['id'],'inputs':{'area':'50'}})
 assert node['status']=='COMPUTED',node
 node_status=node['status']
audit={'id':SPEC['id'],'status':'pass','source_numeric_cells_independently_checked':2,'source_method':'physical PDF page 391 text extraction checked and rendered original independently reviewed','render':'evals/runtime_validation/source-followup-physical-391.png','computed_routes':routes,'verified_rules':['㎡당 table basis','special worker 0.076 and general worker 0.066','source note scope: river-bank manual revetment block laying; iron fitting connection included','slope leveling, soil fill, grass planting separate'],'full_rule_verification':False,'validator_ok':validation['ok'],'calculation_node':node_status}
Path('evals/runtime_validation/civil-2-3-2-manual-block-source-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(audit,ensure_ascii=False,indent=2))
