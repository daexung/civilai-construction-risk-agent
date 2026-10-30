from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit

def spec(sec): return json.loads((ROOT/f'data/drafts/specs/기계설비/{sec}.json').read_text(encoding='utf-8'))['draft']
def assert_lines(result, expected, label):
 assert result['status']=='computed',(label,result)
 actual={line['name']:Fraction(line['exact']) for line in result['unit_lines']}
 assert actual=={k:Fraction(v) for k,v in expected.items()},(label,actual,expected)
 assert all(line['citations'] and line['citations'][0]['internal_id'] for line in result['unit_lines']),label

checks=[]
# 11-1-3: source denominator is one pipe joint, including the separate consumables table.
s=spec('11-1-3'); labor_rates={'ø20':('0.061','0.017'),'25':('0.087','0.024'),'32':('0.109','0.030'),'40':('0.123','0.034'),'50':('0.168','0.046')}
for size,(pipe,helper) in labor_rates.items():
 r=per_unit(s,{'pipe_diameter':size,'quantity':'10'},labor_only=True)
 if size=='32':
  assert r['status']=='blocked' and 'p770-t2' in r.get('reason','') and r.get('citations'),r
  checks.append({'section':'11-1-3','case':'32 has labor cells but the separate p770-t2 exact material row is absent','status':'blocked with citation'})
  continue
 assert_lines(r,{'배관공(인)':pipe,'보통인부(인)':helper},f'11-1-3 labor/{size}/per 10 exact source joints')
 assert r['unit_basis']['per']=='1접합개소'
 checks.append({'section':'11-1-3','case':f'{size}, 10 접합개소','labor_lines':2,'status':'computed'})
# 12-2-4: five pipe rows are m-based; the valve row is explicitly each-based.
s=spec('12-2-4'); data={'1/2 B':('m','0.18','0.21'),'3/4B':('m','0.21','0.26'),'1B':('m','0.24','0.29'),'1 1/2B':('m','0.36','0.43'),'2B':('m','0.48','0.58'),'각종':('개','0.15','0.20')}
for row,(unit,screw,weld) in data.items():
 for connection,expected in [('Screw형',screw),('용접',weld)]:
  r=per_unit(s,{'item_spec':row,'connection_type':connection,'quantity':'1','is_no_fire_zone':False,'is_flange_high_pressure_special':False,'is_stainless':False,'is_loop_test':False,'is_process_pipe':False},labor_only=True)
  assert_lines(r,{'계장공':expected},f'12-2-4 {row}/{connection}')
  assert r['unit_basis']['per']==f'1{unit}'
  checks.append({'section':'12-2-4','case':f'{row}/{connection}/{unit}','labor_lines':1,'status':'computed'})
# 12-2-5: compare the full source row-unit/trade matrix transcribed from printed p.721.
s=spec('12-2-5')
rows={
'압축공기발생장치_5㎏/㎠이하':('조당',{'계장공':'1.40','보통인부':'0.40'}),
'압축공기발생장치_10㎏/㎠이하':('조당',{'계장공':'2.90','보통인부':'0.90'}),
'압축공기발생장치_30㎏/㎠이하':('조당',{'계장공':'8.50','보통인부':'2.50'}),
'주공기Tank_500ℓ 이하':('조당',{'계장공':'2.60','보통인부':'0.80'}),
'주공기Tank_700ℓ 이하':('조당',{'계장공':'3.0','보통인부':'1.5'}),
'주공기Tank_700ℓ 이상':('조당',{'계장공':'4.5','보통인부':'2.5'}),
'유니온엘보_20∼25㎜':('개당',{'계장공':'0.25','보통인부':'0.05'}),
'유압Cylinder_60K':('대',{'계장공':'0.7'}),'유압Cylinder_90K':('대',{'계장공':'0.8'}),'유압Cylinder_130K':('대',{'계장공':'1.0'}),
'OilPump_0.75㎾':('대',{'계장공':'1.5'}),'OilPump_1.50㎾':('대',{'계장공':'1.6'}),'OilPump_2.25㎾':('대',{'계장공':'1.7'}),'OilPump_3.00㎾':('대',{'계장공':'1.8'}),
'AirCylinder_100ø 이하':('대',{'계장공':'1.0'}),'AirCylinder_100ø 이상':('대',{'계장공':'1.2'}),
'AirCompressor_소형':('대',{'계장공':'1.5'}),'AirCompressor_대형':('대',{'계장공':'2.0'}),'제습기':('대',{'계장공':'1.5'}),
'공기압축기시험':('조당',{'계장공':'1.0','보통인부':'1.0'}),'조작함(설비물)_분전반, 계기, 스위치 기타':('조당',{'계장공':'2.0','보통인부':'1.0'})}
for row,(basis,expected) in rows.items():
 r=per_unit(s,{'item_spec':row,'quantity':'1','is_testing':False},labor_only=True)
 assert_lines(r,expected,f'12-2-5 {row}')
 assert r['unit_basis']['per']=='1'+basis.removesuffix('당')
 checks.append({'section':'12-2-5','case':row,'basis':basis,'labor_lines':len(expected),'status':'computed'})
# 8-3-1: the source unit column distinguishes cast-iron sections from weight tons.
s=spec('8-3-1')
boilers={
'주철제 보일러 | 1호(20∼60미만) 1,000Kcal/hr':('절','0.90','0.30'),
'주철제 보일러 | 2호(60∼135미만) 〃':('절','1.10','0.30'),
'주철제 보일러 | 3호(135∼230미만)〃':('절','1.10','0.30'),
'주철제 보일러 | 4호(230∼330미만)〃':('절','2.10','0.50'),
'주철제 보일러 | 5호(330∼640미만)〃':('절','3.0','0.70'),
'주철제 보일러 | 6호(640∼1,180미만) 〃':('절','4.5','0.70'),
'강판제보일러':('중량톤','1.2','0.8'),
'패키지형수관식보일러':('중량톤','6.0','2.0')}
for row,(unit,boiler,helper) in boilers.items():
 r=per_unit(s,{'boiler_type':row,'quantity':'2','is_industrial':False,'same_level':True,'truck_access':False},labor_only=True)
 assert_lines(r,{'보일러공':boiler,'특별인부':helper},f'8-3-1 {row}/{unit}')
 assert r['unit_basis']['per']=='1'+unit
 checks.append({'section':'8-3-1','case':row,'basis':unit,'labor_lines':2,'status':'computed'})
# 2-2-2: the printed source uses pieces for grilles/openings and ㎡ for hood area rates.
s=spec('2-2-2')
inlets=[('그릴(도어그릴)','규격 흡입구 | 규격 1m미만','개','0.525'),('그릴(도어그릴)','규격 장변길이 | 규격 1m이상','개','0.840'),('점검구','규격 300㎜×300㎜ 이하','개','0.355'),('후드','규격 일반 | 규격 투영면적 ㎡당','㎡','0.800'),('후드','규격 2중 | 규격 ″ ㎡당','㎡','0.960'),('후드','규격 그리스필터 | 규격 ″ ㎡당','㎡','0.860'),('후드','규격 2중 그리스필터 | 규격 ″ ㎡당','㎡','1.000')]
for item,specification,unit,rate in inlets:
 r=per_unit(s,{'item_type':item,'spec':specification,'quantity':'100'},labor_only=True)
 assert_lines(r,{'덕트공':rate},f'2-2-2 {item}/{specification}')
 assert r['unit_basis']['per']=='1'+unit
 checks.append({'section':'2-2-2','case':f'{item}/{specification}','basis':unit,'labor_lines':1,'status':'computed'})
# 8-5-1: the adjacent source note explicitly says the rates include one tank's installation.
s=spec('8-5-1')
tanks={'100':('0.75','0.90'),'200':('0.98','1.05'),'300':('1.13','1.28'),'400':('1.50','1.50'),'500':('1.50','1.50'),'750':('2.10','2.10'),'1,000':('2.63','2.63')}
for capacity,(pipe,helper) in tanks.items():
 r=per_unit(s,{'tank_capacity':capacity,'quantity':'2'},labor_only=True)
 assert_lines(r,{'배관공':pipe,'보통인부':helper},f'8-5-1 {capacity}ℓ tank')
 assert r['unit_basis']['per']=='1개'
 checks.append({'section':'8-5-1','case':f'{capacity}ℓ','basis':'개당','labor_lines':2,'status':'computed'})
# 12-3-1: process-specific source denominator, resources, and table-note percentages.
s=spec('12-3-1')
cases=[('설치','없음',{'기사':'61/1000','계장공':'29/1000'}),('통신상태점검','없음',{'계장공':'359/500'}),('점검･시험','없음',{'기사':'1/200','계장공':'19/1000'}),('점검･시험','3개월',{'기사':'23/4000','계장공':'437/20000'}),('점검･시험','6개월',{'기사':'13/2000','계장공':'247/10000'})]
for process,period,expected in cases:
 r=per_unit(s,{'process':process,'quantity':'1','has_service_module':False,'support_period':period},labor_only=True)
 assert_lines(r,expected,f'12-3-1 {process}/{period}')
 assert r['unit_basis']['per']==('1DDC' if process=='통신상태점검' else '1Point')
 checks.append({'section':'12-3-1','case':f'{process}/{period}','labor_lines':len(expected),'status':'computed'})

out={'root_cause':'mixed or omitted source denominators were parsed as one table-wide unit instead of exact task/process rows','sections':['11-1-3','12-2-4','12-2-5','12-3-1','8-3-1','2-2-2','8-5-1'],'focused_cases':len(checks),'computed_routes':sum(x['status']=='computed' for x in checks),'source_blocked_cases':sum(x['status'].startswith('blocked') for x in checks),'visual_source_cell_checks':{'12-2-4':12,'12-2-5':31,'12-3-1':7,'11-1-3':10,'8-3-1':16,'2-2-2':7,'8-5-1':14},'source_references':{'12-2-4':'printed p.720: table labels m-per and each-per explicitly','12-2-5':'printed p.721: exact unit column and resource cells','12-3-1':'printed pp.721-722: Point/DDC rows and support percentage table','11-1-3':'printed p.714: labor unit is per pipe joint; ø32 labor path remains blocked by missing separate material row','8-3-1':'printed p.696: unit column is 인/절 for six cast iron rows and 인/중량톤 for the two other rows','2-2-2':'printed p.662: three piece-rate cells, four ㎡ hood-rate cells; 14 absent item/spec pairs explicitly blocked','8-5-1':'printed p.699: adjacent note states the table rate includes per-tank installation'},'results':checks}
p=ROOT/'evals/runtime_validation/task-dependent-denominator-routes-2026-10-19.json'; p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))
