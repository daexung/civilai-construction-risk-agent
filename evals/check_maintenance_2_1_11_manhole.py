import json,sys
from pathlib import Path
from fractions import Fraction
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.price import price_unit,select_rate_version
from backend.agent.tools.source.citation import resolve_cites
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
IDENT='2026-정오표1차/유지관리/2-1-11/맨홀보수'
SP=ROOT/'data/drafts/specs/유지관리/2-1-11.json'; AP=ROOT/'evals/runtime_validation/maintenance-2-1-11-manhole-audit-2026-10-20.json'
CREW={'포장공':'2','특별인부':'3','보통인부':'3'}
EQUIP={'커터(콘크리트 및 아스팔트용)':'1','소형브레이커(전기식)':'2','모르타르믹서':'1','플레이트콤팩터':'1','트럭':'3'}
OUTPUT={'하수도 및 기타 맨홀':'6','상수도 맨홀':'4'}
SUR={'5이하':Fraction(0),'10이하':Fraction(1,20),'15이하':Fraction(1,10),'20이하':Fraction(3,20)}
def main():
 pkg=json.loads(SP.read_text(encoding='utf8'));s=pkg['draft']; tables={t['id']:t for t in s['tables']}
 assert tables['p936-t3']['values']['시공량(개소)']==OUTPUT
 for name,value in {**CREW,**EQUIP}.items():
  assert tables['p936-t3']['values'][name]=={typ:value for typ in OUTPUT},name
 assert tables['p936-t4']['values']['할증률(%)']=={'10이하':'5','15이하':'10','20이하':'15'}
 # The original p.880 image was visually compared: 5이하 is a dash, followed by 5/10/15%.
 chunks=load_chunks(ROOT/'data/processed/chunks.all.jsonl')
 assert '⑤ 내부미장을 할 경우 품을 별도 계상한다.' in chunks['p936-x17']['text']
 assert '⑦ 공구손료 및 경장비(공기압축기, 발전기 등)의 기계경비는 인력품의 4%로 계상한다.' in chunks['p936-x17']['text']
 cases=[]
 for typ,out in OUTPUT.items():
  for height,surcharge in SUR.items():
   quantity=Fraction(12);result=adjusted_daily_crew(s,{'manhole_type':typ,'quantity':str(quantity),'raise_height':height,'internal_plastering':False,'other_cutter':False},labor_only=True)
   assert result['status']=='computed',(typ,height,result)
   days=quantity/Fraction(out); labor_expected={name:days*Fraction(v)*(1+surcharge) for name,v in CREW.items()}
   equipment_expected={name:days*Fraction(v) for name,v in EQUIP.items()}
   assert Fraction(result['work_days'])==days
   assert {k:Fraction(v) for k,v in result['person_days'].items()}==labor_expected,(typ,height,result['person_days'],labor_expected)
   assert {k:Fraction(v) for k,v in result['equipment_days'].items()}==equipment_expected
   lines={x['name']:x for x in result['unit_lines']}
   for name in CREW:
    assert any(c.get('internal_id')=='p936-t3' and c.get('row')==name and c.get('column')==typ and c.get('value')==CREW[name] for c in lines[name]['citations']), (name, lines[name]['citations'])
    if surcharge:
     table_col=height
     assert any(c.get('internal_id')=='p936-t4' and c.get('row')=='할증률(%)' and c.get('column')==table_col and c.get('value')==str(int(surcharge*100)) for c in lines[name]['citations']), (name, lines[name]['citations'])
   for name in EQUIP:
    assert any(c.get('internal_id')=='p936-t3' and c.get('row')==name and c.get('column')==typ and str(c.get('value')).strip()==EQUIP[name] for c in lines[name]['citations']), (name, lines[name]['citations'])
   priced=price_unit(s,result['unit_lines'],select_rate_version('2026-10-01'),{'manhole_type':typ,'quantity':str(quantity),'raise_height':height,'internal_plastering':False,'other_cutter':False},'2026-10-01')
   assert priced['status'] in ('OK','PARTIAL'),priced
   for cost in priced.get('cost_lines',[]):
    if cost.get('amount_exact') is not None:
     assert Fraction(cost['amount_exact'])==Fraction(priced['labor_subtotal'])*Fraction(4,100)
   cases.append({'manhole_type':typ,'quantity':'12','raise_height':height,'days':str(days),'labor_person_days':{k:str(v) for k,v in labor_expected.items()},'equipment_days':{k:str(v) for k,v in equipment_expected.items()},'price_status':priced['status']})
 for field in ('internal_plastering','other_cutter'):
  inp={'manhole_type':'하수도 및 기타 맨홀','quantity':'1','raise_height':'5이하','internal_plastering':False,'other_cutter':False};inp[field]=True
  blocked=adjusted_daily_crew(s,inp,labor_only=True);assert blocked['status']=='blocked',(field,blocked)
 validation=validate_one(SP,ROOT/'data/drafts',chunks,file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 idxp=ROOT/'data/drafts/executable.json';idx=json.loads(idxp.read_text(encoding='utf8'));assert IDENT in idx['executable'] and all(x.get('id')!=IDENT for x in idx['skipped'])
 audit={'id':IDENT,'status':'pass','physical_pdf_page_index':936,'printed_page':880,'independently_compared_original_numeric_cells':21,'original_dash_cells':1,'route_count':len(cases),'blocked_source_conditions':2,'focused_validation':'pass','price_path':'offline; labor subtotal × source 4% cost line checked per route when prices available','source_axes':{'work_output':OUTPUT,'crew':CREW,'equipment':EQUIP,'surcharge_percent':{'5이하':'dash/0 additional','10이하':'5','15이하':'10','20이하':'15'}},'cases':cases}
 AP.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps({'audit':str(AP.relative_to(ROOT)),'routes':len(cases),'validation':'pass','saved_partition':idx['summary']},ensure_ascii=False))
if __name__=='__main__':main()
