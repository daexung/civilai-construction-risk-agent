from __future__ import annotations
import json
import sys
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
package=json.loads((ROOT/'data/drafts/specs/기계설비/13-1-1.json').read_text(encoding='utf-8'))
spec=package['draft']
source=json.loads((ROOT/'evals/runtime_validation/13-1-1-p779-reconstructed.json').read_text(encoding='utf-8'))
base={'pipe_type':'배관용 탄소강관 KSD3507','diameter':'6','location':'옥내배관','joint_type':'용접식','quantity':'2','material':'탄소강관','height':'0','is_machine_room':False,'is_underground':False,'pressure_under_5':False}
checks=[]
for diameter,row in source['rows'].items():
  for joint in ('용접식','나사식'):
    trades=['플랜트 용접공','플랜트 배관공','특별 인부'] if joint=='용접식' else ['플랜트 배관공']
    expected=[]
    for trade in trades:
      header=next((h for h in row if joint in h.replace(' ', '') and trade.replace(' ','') in h.replace(' ', '')),None)
      assert header is not None,(diameter,joint,trade)
      expected.append((trade,Fraction(row[header])))
    result=per_unit(spec,{**base,'diameter':diameter,'joint_type':joint},labor_only=True)
    assert result['status']=='computed',(diameter,joint,result)
    actual=[(line['name'],Fraction(line['exact'])) for line in result['unit_lines']]
    assert actual==expected,(diameter,joint,actual,expected)
    checks.append({'diameter':diameter,'joint_type':joint,'source_routes':len(expected),'quantity_ton':'2','labor_lines':len(actual),'status':result['status']})
# Independently checked endpoint values are read directly from the rendered original page audit.
for diameter,joint,expected in [('6','용접식',['92','46','46']),('300','용접식',['89/5','93/10','93/10']),('6','나사식',['92']),('300','나사식',['89/5'])]:
  got=per_unit(spec,{**base,'diameter':diameter,'joint_type':joint},labor_only=True)
  assert [x['exact'] for x in got['unit_lines']]==expected
out={'section':'13-1-1','source_physical_page':779,'printed_page':723,'independent_visual_cells':14,'reconstructed_rate_cells':140,'exact_routes_checked':len(checks),'labor_routes_checked':sum(x['source_routes'] for x in checks),'quantity_input_checked':'1 ton unit-rate basis','root_cause':'flat joint_type selector did not encode location + joint + trade multilevel column headers','open_routes':['outdoor piping','pressure piping','diameters above 300','material surcharges and notes','lower per-ton table semantics'],'results':checks}
path=ROOT/'evals/runtime_validation/13-1-1-exact-indoor-carbon-routes-2026-10-19.json'
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))
