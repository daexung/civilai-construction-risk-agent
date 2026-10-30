"""Check general equipment-installation rates and separate source adjustments."""
import hashlib,json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/기계설비/13-11-1.json'; IMAGE=ROOT/'evals/runtime_validation/source-p906-general-equipment-install.png'; AUDIT=ROOT/'evals/runtime_validation/per-unit-13-11-1-source-adjustments-audit-2026-10-19.json'
BASE={'기계산업기사':Fraction('0.50'),'기계설비공':Fraction('7.24'),'비계공':Fraction('2.86'),'용접공':Fraction('0.95'),'특별인부':Fraction('3.90')}
WEIGHT={'0.5ton 미만':Fraction(20),'0.5ton~1ton 미만':Fraction(10),'1ton~5ton 미만':Fraction(0),'5ton 이상':Fraction(-15)}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft']; src=spec['tables'][0]['values']; cells=[]
 raw_values={'기계산업기사':'0.50','기계설비공':'7.24','비계공':'2.86','용접공':'0.95','특별인부':'3.90'}
 for trade,value in BASE.items(): assert src[trade]['수량']==raw_values[trade];cells.append({'row':trade,'column':'수량','value':raw_values[trade]})
 assert src['검사및교정']['수량']=='기술관리를 제외한 본 품의 10%'; cells.append({'row':'검사및교정','column':'수량','value':src['검사및교정']['수량']})
 citation={'internal_id':'p906-t0'}; routes=[]
 for weight,percent in WEIGHT.items():
  r=per_unit(spec,{'quantity':'1','weight_category':weight,'partial_assembly':False}); assert r['status']=='computed',(weight,r)
  lines={x['name']:Fraction(x['exact']) for x in r['unit_lines']}; expected={k:(v if k=='기계산업기사' else v*(1+percent/100)) for k,v in BASE.items()}; expected['검사 및 교정']=sum(v for k,v in BASE.items() if k!='기계산업기사')/10
  assert lines==expected,(weight,lines,expected)
  assert any(c.get('internal_id')=='p906-t0' for x in r['unit_lines'] for c in x['citations'])
  routes.append({'weight':weight,'partial_assembly':False,'status':r['status'],'lines':{k:str(v) for k,v in lines.items()}})
 r=per_unit(spec,{'quantity':'1','weight_category':'1ton~5ton 미만','partial_assembly':True}); assert r['status']=='computed',r
 lines={x['name']:Fraction(x['exact']) for x in r['unit_lines']}; assert lines['기계산업기사']==BASE['기계산업기사'] and lines['기계설비공']==BASE['기계설비공']*Fraction(3,2)
 routes.append({'weight':'1ton~5ton 미만','partial_assembly':True,'status':r['status']})
 overlap=per_unit(spec,{'quantity':'1','weight_category':'0.5ton 미만','partial_assembly':True}); assert overlap['status']=='blocked',overlap
 validation=validate_one(SPEC,DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS));assert validation['ok'],validation
 audit={'id':spec['id'],'status':'independent_source_cells_and_nonoverlap_rules_verified','source':{'physical_page':906,'printed_page':850,'image':'evals/runtime_validation/source-p906-general-equipment-install.png','image_sha256':sha(IMAGE),'visual_review':True,'cells':cells,'nonzero_adjustments':'partial assembly +50%; weight <0.5t +20%, 0.5–1t +10%, 1–5t 0%, ≥5t −15%; inspection/correction 10% excluding technical management'},'runtime':{'standalone_weight_routes':routes[:4],'partial_assembly_route':routes[4],'overlap':'blocked because source does not specify additive or multiplicative order','inspection_formula':'sum of four non-management source trades × 10% = 1.495 per ton','validator':validation,'full_rule_verification':False},'spec_sha256':sha(SPEC),'per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py')}
 AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'routes':len(routes),'overlap':overlap['status'],'validator':validation['ok']}))
if __name__=='__main__':main()
