import os, sys
from pathlib import Path
from collections import defaultdict
from unittest.mock import patch
from io import BytesIO
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); os.environ.update(AGENT_MODE='tools',AGENT_LLM='off',AGENT_OFFLINE='1')
from backend.agent.estimate import dialogue,tools
from backend.agent.rules.specs import load_specs
from backend.agent.tools.source import citation
from backend.api import dialogue_service,tables
SPECS=list(load_specs().values())
NEW=next(s for s in SPECS if s['section_no']=='5-1-8')
OLD=next(s for s in SPECS if s['section_no']=='6-1-1' and s['division']=='공통')
def hit(query):
 s=NEW if '복공판' in query else OLD
 return {'rank':1,'section_no':s['section_no'],'division':s['division'],'section':s['section_no']+' '+s['title'],'page':160,'text':s['title'],'chunk_id':'mock','ref':s['id']}
def answer(q):
 name=q['name'].split('::')[-1]
 if name=='operation': return '설치'
 if name=='quantity': return '500' if q['name'].startswith('i0_') else '20'
 if name in ('is_roof_slab','crane_used','lifting_equipment_used','scattered_small_volume'): return False
 return q['choices'][0] if q.get('choices') else '100'
def finish(g,tid,r,n=35):
 for _ in range(n):
  if not r['questions']: return r
  q=r['questions'][0]
  r=dialogue_service.respond(g,tid,{'answers':{q['name']:answer(q)},'refs':{q['name']:q['ref']}})
 return r
g=dialogue.build_dialogue_graph(); tid='parallel-5-1-8'
with patch.object(tools,'retrieve',side_effect=lambda s:{'hits':[hit(s['query'])],'search_info':{'method':'mock','api_calls':0,'warnings':[]}}), patch.object(citation,'_pages',return_value=defaultdict(lambda:{'printed_page':None,'division':None})):
 r=dialogue_service.respond(g,tid,{'message':'복공판 설치 500㎡ + 일반시공 20㎡ 견적'})
 r=dialogue_service.respond(g,tid,{'answers':{q['name']:'계산에 포함' for q in r['questions']},'refs':{q['name']:q['ref'] for q in r['questions']}})
 r=finish(g,tid,r)
 s=dialogue.load(g,tid)['session']; ids=s['item_order']; new_id=next(i for i in ids if s['items'][i]['selected_spec_id']==NEW['id']); old_id=next(i for i in ids if i!=new_id)
 assert s['items'][new_id]['status']=='PRICED',s['items'][new_id]
 assert s['items'][new_id]['priced_result']['status']=='PARTIAL'
 assert any(x['name']=='크레인' for x in s['items'][new_id]['priced_result']['unpriced'])
 assert any(x['name'].startswith('하부구조') for x in s['items'][new_id]['priced_result']['unpriced'])
 assert s['items'][new_id]['computed_result']['equipment_days']['크레인']=='25/6'
 crane_line=next(x for x in s['items'][new_id]['computed_result']['unit_lines'] if x['name']=='크레인')
 assert crane_line['unit']=='hr/㎡' and crane_line['exact']=='1/15'
 assert s['items'][new_id]['priced_result']['reference_amounts']['total']=='5395000'
 old_before=s['items'][old_id]['computed_result']; old_rev=s['items'][old_id]['input_revision']; old_statement=s['statement']['totals']['contract_amount']
 new_price=s['items'][new_id]['priced_result']['reference_amounts']['total']
 book=load_workbook(BytesIO(tables.build_xlsx(dialogue_service.export_response(g,tid))),data_only=True)
 assert any(row[1]==new_id for row in book['내역서'].iter_rows(values_only=True))
 r=dialogue_service.respond(g,tid,{'message':'복공판 설치 600㎡로 바꿔'})
 r=finish(g,tid,r); s2=dialogue.load(g,tid)['session']
 assert s2['items'][new_id]['input_revision']>s['items'][new_id]['input_revision']
 assert s2['items'][old_id]['input_revision']==old_rev and s2['items'][old_id]['computed_result']==old_before
 assert s2['items'][new_id]['priced_result']['reference_amounts']['total']!=new_price
 assert s2['aggregate_result']['status']=='PARTIAL',s2['aggregate_result']
 dialogue_service.restore(g,tid)
 restored=dialogue.load(g,tid)['session']
 assert restored['items'][old_id]['computed_result']==old_before
 assert restored['items'][new_id]['priced_result']==s2['items'][new_id]['priced_result']
 after_book=load_workbook(BytesIO(tables.build_xlsx(dialogue_service.export_response(g,tid))),data_only=True)
 after_row=next(row for row in after_book['내역서'].iter_rows(values_only=True) if row[1]==new_id)
 new_total_after=s2['items'][new_id]['priced_result']['reference_amounts']['total']
 assert after_row[3]==600 and after_row[11]==int(new_total_after)
 print('PASS',{'new_status':s2['items'][new_id]['status'],'priced_status':s2['items'][new_id]['priced_result']['status'],'aggregate':s2['aggregate_result']['status'],'new_total_before':new_price,'new_total_after':new_total_after,'edited_excel_row':after_row,'old_revision_preserved':old_rev,'contract_before':old_statement,'export_sheet_rows':book['내역서'].max_row,'crane_unit':crane_line['unit'],'crane_applied':crane_line['exact'],'restored':restored['items'][new_id]['priced_result']['status']})
