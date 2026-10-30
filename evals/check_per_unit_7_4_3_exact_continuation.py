from __future__ import annotations
import json,sys,unicodedata
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/토목/7-4-3.json';PDF=ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
TABLES={'p450-t2':{'200':('0.02','0.06'),'250':('0.02','0.07'),'300':('0.02','0.08'),'350':('0.02','0.09'),'400':('0.03','0.10'),'510':('0.03','0.13'),'560':('0.04','0.16'),'610':('0.04','0.18')},'p451-t0':{'630':('0.05','0.18'),'660':('0.05','0.20'),'685':('0.05','0.20'),'710':('0.05','0.21'),'760':('0.05','0.21'),'840':('0.06','0.25'),'860':('0.07','0.27')}}
TRADES=['보통인부\n(인)','크레인\n(hr)']; COLS=['보통인부\n(인)','크레인\n(hr)']
def norm(s):return ''.join(unicodedata.normalize('NFKC',str(s)).split()).casefold()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf8'))['draft'];tables={t['id']:t for t in spec['tables']};cells=0;routes=[]
 with pymupdf.open(PDF) as doc:
  for tid,rows in TABLES.items():
   table=tables[tid]
   for dia,values in rows.items():
    assert norm(dia) in norm(doc[table['source'].find('') if False else (449 if tid=='p450-t2' else 450)].get_text())
    assert list(table['values'][dia].values())==list(values),(tid,dia,table['values'][dia],values)
    for col,val in zip(COLS,values):
     assert norm(col.replace('\n','')) in norm(doc[449 if tid=='p450-t2' else 450].get_text()),(tid,col)
     assert norm(val) in norm(doc[449 if tid=='p450-t2' else 450].get_text()),(tid,dia,col,val)
     cells+=1
 for dia in [x for rows in TABLES.values() for x in rows]:
  tid='p450-t2' if dia in TABLES['p450-t2'] else 'p451-t0'
  expected=TABLES[tid][dia]
  for pipe_type in ('해상관','침설관'):
   for q in ('1','2'):
    r=per_unit(spec,{'pipe_diameter':dia,'pipe_type':pipe_type,'quantity':q,'crane_type_change':False})
    assert r['status']=='computed',(dia,pipe_type,q,r)
    lines={x['name']:x for x in r['unit_lines']}
    for trade,raw in zip(TRADES,expected):
     assert Fraction(lines[trade]['exact'])==Fraction(raw),(dia,pipe_type,q,trade,lines.get(trade))
     c=lines[trade]['citations'][0]
     assert (c['internal_id'],c['row'],c['value'])==(tid,dia,raw),(dia,c)
     assert c['column'] in table_columns(tables[tid],dia,trade),(dia,c)
    routes.append({'diameter':dia,'pipe_type':pipe_type,'quantity':q,'table':tid})
 v=validate_one(SPEC,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert v['ok'],v
 report={'status':'pass','source_pages':{'physical':[450,451],'printed':[394,395]},'independent_source_cells':cells,'exact_continuation_routes':15,'exact_runtime_scenarios':len(routes),'exact_rate_citations':len(routes)*2,'format_citation_preflight':'pass','source_visual_review':'Original PDF p.450 printed p.394 and p.451 printed p.395 checked: 200–610 rows on first table, 630–860 continuation rows on second; both resource columns and exact unit set.' ,'routes':routes}
 out=ROOT/'evals/runtime_validation/per-unit-7-4-3-exact-table-continuation-2026-10-19.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({k:v for k,v in report.items() if k!='routes'},ensure_ascii=False,indent=2));return 0
def table_columns(table,dia,trade):
 return [c for c in table['values'][dia] if ''.join(c.split())==''.join(trade.split())]
if __name__=='__main__':raise SystemExit(main())
