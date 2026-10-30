"""Source and multi-activity audit for civil 4-3-2 track placement."""
from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/'data/drafts/specs/토목/4-3-2.json';PKG=json.loads(PATH.read_text(encoding='utf-8'));SPEC=PKG['draft']
page=fitz.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')[402];text=page.get_text()
assert all(token in text for token in ['4-3-2 궤광거치','250','16,000L','11.19㎾','시공량을 5%까지','보통인부 2인'])
expected={'도상정리 작업/특별인부':{'수량':'1'},'도상정리 작업/보통인부':{'수량':'9'},'도상정리 작업/살수차':{'규격':'16,000L','수량':'1'},'궤광조립대 설치/궤도공':{'수량':'7'},'궤광조립대 설치/보통인부':{'수량':'3'},'궤광높이기/궤도공':{'수량':'7'},'궤광높이기/보통인부':{'수량':'3'},'궤광높이기/측량중급기술자':{'수량':'1'},'궤광높이기/양로기':{'규격':'11.19kW','수량':'1'},'궤광정정 및 타설준비/궤도공':{'수량':'8'},'궤광정정 및 타설준비/보통인부':{'수량':'2'},'궤광정정 및 타설준비/측량중급기술자':{'수량':'1'},'궤광정정 및 타설준비/LVT 방진상자 추가 보통인부':{'수량':'2'},'시공량':{'시공량(m)':'250'},'비고':{'단선 감산률':'최대 5%'}}
assert SPEC['tables'][0]['values']==expected
assert sum(c.get('table_id')=='p403-t0' and c.get('value') not in ('최대 5%',None) for c in PKG['citations'])==14
routes=[]
for structure,helper_rate in [('직결식',17),('매립식(LVT)',19)]:
 for length in (250,500):
  inp={'quantity':str(length),'track_type':'복선','track_structure':structure};r=adjusted_daily_crew(SPEC,inp);assert r['status']=='computed',r
  days=Fraction(length,250)
  assert Fraction(r['daily_volume_m3'])==250 and Fraction(r['work_days'])==days
  expected_people={'특별인부':days,'보통인부':helper_rate*days,'궤도공':22*days,'측량중급기술자':2*days}
  assert {k:Fraction(v) for k,v in r['person_days'].items()}==expected_people,(inp,r)
  assert {k:Fraction(v) for k,v in r['equipment_days'].items()}=={'살수차 16,000L':days,'양로기 11.19kW':days}
  routes.append({'track_structure':structure,'quantity_m':length,'work_days':str(days),'person_days':{k:str(v) for k,v in expected_people.items()}})
for structure in ('매립식(LVT)','직결식'):
 r=adjusted_daily_crew(SPEC,{'quantity':'500','track_type':'단선','track_structure':structure});assert r['status']=='blocked',r
valid=validate_one(PATH,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert valid['ok'],valid
node_status='not_registered_in_active_execution_index'
if SPEC['id'] in load_specs():
 n=compute({'spec_id':SPEC['id'],'inputs':{'quantity':'500','track_type':'복선','track_structure':'매립식(LVT)'}});assert n['status']=='COMPUTED',n;node_status=n['status']
audit={'id':SPEC['id'],'status':'pass','source_numeric_table_cells_independently_checked':13,'source_note_numeric_value_checked':1,'render':'evals/runtime_validation/source-followup-physical-403.png','computed_routes':routes,'blocked_policy_routes':2,'verified_rules':['shared 250m/day basis for all four sequential operations','stage-specific labor and equipment counts preserved','survey operation cited twice exactly as original shows','LVT vibration-box installation adds two general laborers only during correction/precast-preparation stage','single-track up-to-5% reduction is blocked because source gives no point-selection policy','other machine costs and concrete placement are separately accounted'],'full_rule_verification':False,'validator_ok':valid['ok'],'calculation_node':node_status}
Path('evals/runtime_validation/civil-4-3-2-track-placement-source-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
