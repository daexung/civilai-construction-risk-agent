from pathlib import Path
import json,hashlib,sys
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import validate_one,chunks_by_id_from_list
spec_path=ROOT/'data/drafts/specs/기계설비/13-2-5.json'; spec=json.loads(spec_path.read_text(encoding='utf8')); draft=spec['draft']
cols=['0.75이하','1.00','1.25','1.50','1.75','2.00','2.25','2.50','2.75','3.00']
expected={
'p808-t2':{'3이하':['0.208','0.250',None,None,None,None,None,None,None,None],'4':['0.292','0.312','0.375','0.417',None,None,None,None,None,None],'5':[None,'0.396','0.437','0.500','0.521','0.583',None,None,None,None],'6':[None,'0.437','0.521','0.562','0.625','0.667','0.708',None,None,None],'8':[None,'0.625','0.708','0.771','0.771','0.917','0.937','1.000',None,None],'10':[None,None,'0.854','0.917','0.979','1.125','1.208','1.312','1.479','1.583'],'12':[None,None,None,'1.271','1.375','1.458','1.542','1.667','1.792','1.896'],'14':[None,None,None,'1.521','1.646','1.750','1.896','2.000','2.146','2.271']},
'p809-t0':{'16':[None,None,None,None,'1.958','2.083','2.187','2.417','2.562','2.708'],'18':[None,None,None,None,None,'2.562','2.708','2.854','3.083','3.292'],'20':[None,None,None,None,None,'2.917','3.146','3.312','3.542','3.792'],'22':[None,None,None,None,None,None,None,'3.583','3.833','4.125'],'24':[None,None,None,None,None,None,None,'3.875','4.125','4.417']}}
tables={t['id']:t for t in draft['tables']}; checked=0; blanks=0
for tid,rows in expected.items():
 for row,values in rows.items():
  actual=tables[tid]['values'].get(row,{})
  for col,value in zip(cols,values):
   if value is None:
    assert col not in actual,(tid,row,col,actual.get(col)); blanks+=1; continue
   assert actual.get(col)==value,(tid,row,col,actual.get(col),value)
   result=per_unit(draft,{'pipe_size':row,'thickness':col,'heating_method':'Electric Resistance Heating','quantity':'1'})
   assert result['status']=='computed',(tid,row,col,result)
   line=next(x for x in result['unit_lines'] if x['kind']=='labor' and x['name']=='플랜트용접공')
   assert Fraction(line['exact'])==Fraction(value),(tid,row,col,line,value)
   cite=line['citations'][0]
   assert (cite['internal_id'],cite['row'],cite['column'],cite['value'])==(tid,row,col,value)
   checked+=1
# every source-blank cross cell safely blocks; a representative for each table
for tid,row,col in [('p808-t2','3이하','1.25'),('p809-t0','16','1.50')]:
 result=per_unit(draft,{'pipe_size':row,'thickness':col,'heating_method':'Electric Resistance Heating','quantity':'1'})
 assert result['status']=='blocked',(tid,row,col,result)
# Active node uses the promoted spec and exact source path.
active=compute({'spec_id':draft['id'],'inputs':{'pipe_size':'24','thickness':'3.00','heating_method':'Electric Resistance Heating','quantity':'2'}})
assert active['status']=='COMPUTED',active
# source-declared Gas Heating policy remains blocked
result=per_unit(draft,{'pipe_size':'3이하','thickness':'0.75이하','heating_method':'Gas Heating','quantity':'1'})
assert result['status']=='blocked',result
chunks_path=ROOT/'data/processed/chunks.all.jsonl'; chunks=[json.loads(x) for x in chunks_path.read_text(encoding='utf8').splitlines() if x]
validation=validate_one(spec_path,ROOT/'data/drafts/specs',chunks_by_id_from_list(chunks),hashlib.sha256(chunks_path.read_bytes()).hexdigest())
assert validation['ok'],validation
record={'section':'13-2-5','result':'PASS','scope':{'source_numeric_cells':checked,'source_blank_intersections_preserved':blanks,'exact_cell_calculator_routes':checked,'blocked_blank_cases':2,'blocked_gas_heating_case':1,'active_compute_node':'passed','draft_validation':'passed'},'source_evidence':{'pdf':'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf','physical_pages':[808,809],'printed_pages':[752,753],'visually_inspected_renders':['evals/runtime_validation/followup-p808.png','evals/runtime_validation/followup-p809.png'],'comparison':'all 68 nonblank table values and row/column positions transcribed from original page images; all absent intersections preserved blank'},'validation':validation,'hashes':{'spec_sha256':hashlib.sha256(spec_path.read_bytes()).hexdigest(),'chunks_all_sha256':hashlib.sha256(chunks_path.read_bytes()).hexdigest()}}
out=ROOT/'evals/runtime_validation/mechanical-13-2-5-preheat-source-audit-2026-10-19.json';out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps(record,ensure_ascii=False,indent=2))
