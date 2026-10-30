"""Verify flowmeter replacement rates and keep explicit protection dashes blocked."""
import hashlib,itertools,json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/유지관리/4-3-1.json';IMAGE=ROOT/'evals/runtime_validation/source-p981-flowmeter-replacement.png';AUDIT=ROOT/'evals/runtime_validation/maintenance-4-3-1-explicit-dash-scope-audit-2026-10-19.json'
RATES={'보호통':{'ø13~15':'6.0','ø20~32':'5.0','ø40~50':'4.0'},'유량계':{'ø13~15':'8.0','ø20~32':'7.0','ø40~50':'6.0','ø65~80':'2.0','ø100~150':'1.5','ø200~300':'1.0'}}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft']; table=spec['tables'][0]['values']; cells=[]; routes=[]
 for work,rates in RATES.items():
  for diameter,rate in rates.items():
   assert table[work][diameter]==rate;cells.append({'row':work,'column':diameter,'value':rate})
   result=adjusted_daily_crew(spec,{'work_type':work,'diameter':diameter,'quantity':'1','parallel_replacement':False})
   assert result['status']=='computed',(work,diameter,result)
   expected=1/Fraction(rate)
   actual={line['name']:Fraction(line['exact']) for line in result['unit_lines']}
   assert actual=={'배관공':expected,'보통인부':expected},(work,diameter,actual,expected)
   routes.append({'work_type':work,'diameter':diameter,'production_per_day':rate,'labor_days_each':str(expected)})
 for diameter in ('ø65~80','ø100~150','ø200~300'):
  assert table['보호통'][diameter]=='-'; cells.append({'row':'보호통','column':diameter,'value':'-','interpretation':'not converted to zero; blocked'})
  blocked=adjusted_daily_crew(spec,{'work_type':'보호통','diameter':diameter,'quantity':'1','parallel_replacement':False})
  assert blocked['status']=='blocked' and any(c.get('internal_id')=='p981-t0' for c in blocked.get('citations',[]))
 validation=validate_one(SPEC,DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS));assert validation['ok'],validation
 audit={'id':spec['id'],'status':'source_rates_verified_dash_semantics_preserved','source':{'physical_page':981,'printed_page':925,'image':'evals/runtime_validation/source-p981-flowmeter-replacement.png','image_sha256':sha(IMAGE),'visual_review':True,'cells':cells},'runtime':{'exact_numeric_routes':len(routes),'routes':routes,'explicit_dash_cases':3,'parallel_replacement':'still blocked; 30% work-rate reduction model remains separate and unresolved','validator':validation,'full_rule_verification':False},'spec_sha256':sha(SPEC),'runtime_sha256':sha(ROOT/'backend/agent/tools/calc/daily_crew.py')}
 AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'numeric_cells':len(routes),'dashes_blocked':3,'validator':validation['ok']}))
if __name__=='__main__':main()
