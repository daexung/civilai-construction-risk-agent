"""Offline scraper plus existing equipment dialogue estimate integration check."""
import json,os,sys
from collections import defaultdict
from fractions import Fraction as F
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.update(AGENT_MODE='tools',AGENT_LLM='off',AGENT_OFFLINE='1')
from openpyxl import load_workbook
from backend.agent.estimate import dialogue,tools
from backend.agent.rules.specs import load_specs
from backend.agent.tools.source import citation
from backend.api import dialogue_service,tables
SPECS=list(load_specs().values())
SCR=next(s for s in SPECS if s['section_no']=='8-2-6' and any(f['name']=='soil_condition' for f in s['inputs']))
DOZ=next(s for s in SPECS if s['section_no']=='8-2-1' and any(f['name']=='bulldozer_type' for f in s['inputs']))
LOADER=next(s for s in SPECS if s['section_no']=='8-2-5' and any(f['name']=='loader_type' for f in s['inputs']))
def hit(q):
 spec=SCR if SCR['title'] in q else DOZ if DOZ['title'] in q else LOADER
 return {'rank':1,'section_no':spec['section_no'],'division':spec['division'],'section':spec['section_no']+' '+spec['title'],'page':176,'table_id':None,'text':spec['title'],'chunk_id':'mock','ref':spec['id']}
def answer(q,spec_id,qty='100'):
 name=q['name'].split('::',1)[-1];spec=next(s for s in SPECS if s['id']==spec_id)
 if name=='quantity':return qty
 fixed={'push_dozer_used':False,'has_large_cobble':False,'is_trenching':False,'is_underwater':False,'is_residential_area':False}
 if name in fixed:return fixed[name]
 if name in ('L1','L2','L','fuel_price'):return {'L1':'120','L2':'180','L':'1.2','fuel_price':'1000'}[name]
 if name=='volume_basis':return '\uc790\uc5f0\uc0c1\ud0dc'
 field=next((f for f in spec['inputs'] if f['name']==name),None);choices=q.get('choices') or (field or {}).get('allowed_values')
 if isinstance(choices,list) and choices:return choices[0]
 return '10'
def drive(graph,tid,r,qty='100'):
 for _ in range(100):
  if not r['questions']:return r
  q=r['questions'][0];st=dialogue.load(graph,tid);iid=q['name'].split('::',1)[0];sid=st['session']['items'][iid]['selected_spec_id']
  r=dialogue_service.respond(graph,tid,{'answers':{q['name']:answer(q,sid,qty)},'refs':{q['name']:q['ref']}})
 raise AssertionError(('stuck',r['questions'][:1]))
def main():
 graph=dialogue.build_dialogue_graph();tid='scraper-mixed-e2e';msg=SCR['title']+' 100\u33a5 + '+DOZ['title']+' 100\u33a5 \ube44\uc6a9 \uacac\uc801'
 with patch.object(tools,'retrieve',side_effect=lambda s:{'hits':[hit(s['query'])],'search_info':{'method':'mock','api_calls':0,'warnings':[]}}),patch.object(citation,'_pages',return_value=defaultdict(lambda:{'printed_page':None,'division':None})):
  r=dialogue_service.respond(graph,tid,{'message':msg});include='\uacc4\uc0b0\uc5d0 \ud3ec\ud568'
  r=dialogue_service.respond(graph,tid,{'answers':{q['name']:include for q in r['questions']},'refs':{q['name']:q['ref'] for q in r['questions']}});r=drive(graph,tid,r)
  st=dialogue.load(graph,tid);assert st is not None, r;items=st['session']['items'];ids={it['selected_spec_id']:k for k,it in items.items()};sid=ids[SCR['id']];did=ids[DOZ['id']]
  assert items[sid]['status']=='PRICED' and items[sid]['priced_result']['status']=='OK',items[sid].get('priced_result')
  assert items[did]['status']=='PRICED' and items[did]['priced_result']['status']=='OK',items[did].get('priced_result')
  # Source: q=5.4*1.13, f=1/1.2, E=.85, cm=120/400+180/600+2.8=3.4.
  Q=60*F('5.4')*F('1.13')*F(1,F('1.2'))*F('.85')/F('3.4');lines=items[sid]['computed_result']['unit_lines']
  ref=next(F(x['exact']) for x in lines if x['kind']=='reference');hours=next(F(x['exact']) for x in lines if x['kind']=='equipment')
  assert ref==Q and hours==1/Q,(lines,Q)
  priced=items[sid]['priced_result'];assert int(priced['total'])==1014 and not priced['unpriced'],priced
  assert sorted(map(int,priced['unit_prices'].values()))==[239,311,464] and priced['reference_amounts']['total']=='101400'
  before=int(priced['total']);contract=st['session']['statement']['totals']['contract_amount'];sibling=json.dumps(items[did]['computed_result'],sort_keys=True)
  wb=load_workbook(BytesIO(tables.build_xlsx(dialogue_service.export_response(graph,tid))),data_only=True);row=next(x for x in wb['\ub0b4\uc5ed\uc11c'].iter_rows(values_only=True) if x[1]==sid);assert row[3]==100 and row[2]=='m3',row
  edit=SCR['title']+' 200\u33a5 \ubc14\uafd4';r=dialogue_service.respond(graph,tid,{'message':edit});r=drive(graph,tid,r,qty='200')
  st2=dialogue.load(graph,tid);its=st2['session']['items'];sc=its[sid];assert sc['conditions']['quantity']=='200',sc['conditions']
  ls=sc['computed_result']['unit_lines'];q2=next(F(x['exact']) for x in ls if x['kind']=='reference');h2=next(F(x['exact']) for x in ls if x['kind']=='equipment')
  assert q2==Q and h2==1/Q,(q2,h2,Q)
  assert int(sc['priced_result']['total'])==before and sc['priced_result']['unit_prices']==priced['unit_prices'] and sc['priced_result']['reference_amounts']['total']=='202800'
  assert json.dumps(its[did]['computed_result'],sort_keys=True)==sibling
  c2=st2['session']['statement']['totals']['contract_amount'];assert c2>contract,(contract,c2)
  wb2=load_workbook(BytesIO(tables.build_xlsx(dialogue_service.export_response(graph,tid))),data_only=True);row2=next(x for x in wb2['\ub0b4\uc5ed\uc11c'].iter_rows(values_only=True) if x[1]==sid);assert row2[3]==200 and row2[4]==row[4] and abs(row2[5]-2*row[5])<=2 and abs(row2[7]-2*row[7])<=2 and abs(row2[9]-2*row[9])<=2,(row,row2)
  assert dialogue_service.restore(graph,tid)['statement']['totals']['contract_amount']==c2
  print('PASS source formula/price, mixed scraper+bulldozer, stable per-unit prices, 100->200 Excel quantities/amounts, sibling and restore')
if __name__=='__main__':main()
