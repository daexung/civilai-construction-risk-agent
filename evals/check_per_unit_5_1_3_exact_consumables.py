"""Check exact welding consumables per source ton; preserve upper-bound rules as partial."""
import hashlib,itertools,json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/토목/5-1-3.json';IMAGE=ROOT/'evals/runtime_validation/source-p414-material-rates.png';AUDIT=ROOT/'evals/runtime_validation/civil-5-1-3-exact-consumables-audit-2026-10-19.json'
RAW={'용접봉':'26','산소':'15.0','LPG가스':'10.0'};UNITS={'용접봉':'kg/ton','산소':'m³/ton','LPG가스':'kg/ton'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft']; table=next(t for t in spec['tables'] if t['id']=='p414-t1')['values'];cells=[]
 for name,value in RAW.items():assert table[name]['수량']==value;cells.append({'table':'p414-t1','row':name,'column':'수량','value':value})
 assert table['잡품·기타']['수량']=='1';cells.append({'table':'p414-t1','row':'잡품·기타','column':'수량','value':'1','disposition':'not priced: source caps cost at 5% of welding consumables; no rate selected'})
 routes=[]
 for weight,girder in itertools.product(('0.25','10'),('박스거더/플레이트거더','기타')):
  result=per_unit(spec,{'weight':weight,'girder_type':girder});assert result['status']=='computed',result
  actual={line['name']:Fraction(line['exact']) for line in result['unit_lines']}
  expected={'용접봉':Fraction(26),'산소':Fraction(15),'LPG가스':Fraction(10)}
  assert actual==expected,(weight,girder,actual,expected)
  assert all(line['unit']==UNITS[line['name']] and any(c.get('internal_id')=='p414-t1' for c in line['citations']) for line in result['unit_lines'])
  routes.append({'weight_ton':weight,'girder_type':girder,'per_ton_rates':{k:str(v) for k,v in actual.items()},'calculated_material_totals':{'welding_rod_kg':str(26*Fraction(weight)),'oxygen_m3':str(15*Fraction(weight)),'LPG_kg':str(10*Fraction(weight))},'status':'computed'})
 validator=validate_one(SPEC.resolve(),DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS));assert validator['ok'],validator
 audit={'id':spec['id'],'status':'exact_consumables_verified_with_partial_source_rules_preserved','source':{'physical_page':414,'printed_page':358,'image':'evals/runtime_validation/source-p414-material-rates.png','image_sha256':sha(IMAGE),'visual_review':True,'exact_cells':cells},'runtime':{'routes':routes,'exact_material_rates_per_ton':{'welding_rod':'26 kg','oxygen':'15 m³','LPG':'10 kg'},'partial_items':spec['not_calculated'],'price_validation':'material quantities verified offline; no external price service called; unit prices are outside this quantity check','validator':validator,'full_rule_verification':False},'spec_sha256':sha(SPEC),'per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py')}
 AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'source_cells':len(cells),'routes':len(routes),'partial_items':len(spec['not_calculated']),'validator':validator['ok']}))
if __name__=='__main__':main()
