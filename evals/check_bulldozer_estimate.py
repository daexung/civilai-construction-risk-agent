"""8-2-1 bulldozer: source-based Q/time/price and shared equipment route smoke."""
from __future__ import annotations
import json, os, sys
from fractions import Fraction as F
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); os.environ['AGENT_OFFLINE']='1'
from backend.agent.rules.specs import load_specs
from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.tools.calc.price import price_unit, select_rate_version
spec=next(s for k,s in load_specs().items() if '/공통/8-2-1/불도저_' in k)
inputs={'bulldozer_type':'무한궤도','bulldozer_capacity':'7','transport_distance':'10','soil_type':'모래, 사질토','soil_state':'자연상태','site_condition':'양호','is_grading':False,'is_trenching':False,'work_type':'굴착/굴착운반/발근/석재류집적','volume_basis':'자연상태','L':'1.25','quantity':'100','fuel_price':'1500'}
result=formula_quantity(spec,inputs)
assert result['status']=='computed',result
qbase=F('1.1'); e=F(1); E=F('.8'); cm=F(10,43)+F(10,53)+F(1,4)
q=60*qbase*(F(1)/F('1.25'))*E/cm
lines={x['name']:x for x in result['unit_lines']}
assert F(lines['시간당 작업량 Q']['exact'])==q,(lines,q)
assert F(lines['불도저']['exact'])==1/q,(lines,q)
assert lines['불도저']['citations'] and lines['시간당 작업량 Q']['citations']
missing_l=formula_quantity(spec,{k:v for k,v in inputs.items() if k!='L'})
assert missing_l['status']=='ask' and 'L' in missing_l['missing'],missing_l
loose_inputs=inputs | {'volume_basis':'흐트러진 상태'}
loose_inputs.pop('L')
loose=formula_quantity(spec,loose_inputs)
assert loose['status']=='computed',loose
q_loose=60*F('1.1')*E/(F(10,43)+F(10,53)+F(1,4))
loose_lines={x['name']:x for x in loose['unit_lines']}
assert F(loose_lines['시간당 작업량 Q']['exact'])==q_loose and F(loose_lines['불도저']['exact'])==1/q_loose
assert lines['불도저']['unit']=='hr/㎥'
priced=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01')
assert priced['status']=='OK',priced.get('unpriced')
components={x['name']:x for x in priced['equipment_lines']}
assert {k:components[k]['machine_code'] for k in ('불도저 기계손료','불도저 운전원','불도저 연료·잡재료비')}=={k:'0101-0007' for k in ('불도저 기계손료','불도저 운전원','불도저 연료·잡재료비')}
assert all(components[k]['amount'] is not None for k in components)
assert priced['total'] is not None
assert int(priced['reference_amounts']['total']) == int(priced['total']) * 100
inputs200=inputs | {'quantity':'200'}
priced200=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs200,'2026-10-01')
assert int(priced200['reference_amounts']['total']) == int(priced['reference_amounts']['total']) * 2
assert priced200['unit_prices']==priced['unit_prices']
print(f"PASS 8-2-1 source expectation Q={q}, hours per ㎥={1/q}; 3 equipment costs priced, total={priced['total']}")
