"""Regenerate the final parsing snapshot from the preserved local ODL input."""
import argparse
import collections
import hashlib
import json
import sys
import time
from pathlib import Path
sys.dont_write_bytecode=True
WORK=Path(__file__).resolve().parent;ROOT=WORK.parents[1]
OUT=WORK/'out'
PREV=WORK/'local/baseline/table-review';ROWMAP=WORK/'row_mappings.json';COMPLETE=WORK/'completeness.json'
CORRECTIONS=WORK/'corrections.json';PAGE_MAP=WORK/'page_map.json'
sys.path.insert(0,str(WORK/'pipeline'))
import source_corrections as sc
sys.stdout.reconfigure(encoding='utf-8')
PDF=ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
RAW=WORK/'local/raw.json'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):
    p.parent.mkdir(exist_ok=True,parents=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=1),encoding='utf-8')
def log(stage,**x):
    obj={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'stage':stage,**x}
    with (OUT/'progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')
    print(json.dumps(obj,ensure_ascii=False),flush=True)
def generate():
    import structure_store as ss
    import structure_rules as sr
    import structure_export as se
    import chunk
    required=[PDF,RAW,PAGE_MAP,CORRECTIONS,ROWMAP,COMPLETE,WORK/'reviewed_tables.json',WORK/'diagram_tables.json']
    missing=[str(p) for p in required if not p.is_file()]
    if missing:raise FileNotFoundError('필수 입력 파일이 없습니다: '+', '.join(missing))
    OUT.mkdir(parents=True,exist_ok=True)
    t=time.perf_counter();m=read(CORRECTIONS)
    gen={'id':'corrected-'+hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()[:12],
         'code_sha256':{p.name:sc.digest(p) for p in (WORK/'pipeline').glob('*.py')},
         'raw_sha256':sc.digest(RAW),'pdf_sha256':sc.digest(PDF),'corrections_sha256':sc.digest(CORRECTIONS),'row_mappings_sha256':sc.digest(ROWMAP),'completeness_sha256':sc.digest(COMPLETE),
         'reviewed_tables_sha256':sc.digest(WORK/'reviewed_tables.json'),'diagram_tables_sha256':sc.digest(WORK/'diagram_tables.json'),
         'pages':list(range(1,983))}
    gen['id']='complete-'+hashlib.sha256(json.dumps(gen,sort_keys=True).encode()).hexdigest()[:12]
    log('전체 교정 적용과 재생성 시작')
    probe=sr.PdfProbe(PDF)
    try:
        store=ss.load_store(RAW,gen['pages'],run='full',probe=probe,
                            divisions=chunk.page_divisions(PAGE_MAP),corrections=CORRECTIONS,row_mappings=ROWMAP,completeness=COMPLETE,
                            reviewed_tables=WORK/'reviewed_tables.json',diagram_tables=WORK/'diagram_tables.json')
        exported=se.export(store,gen)
        saved={k:getattr(store,k) for k in ['pages','page_height','page_height_source','printed_page','part_marks','headings','basis','notes','logical_tables','boundaries','context_out','skipped_text']}
        saved['tables']=[{k:v for k,v in tb.items() if k not in {'common','cover','_numeric','shades'}} for tb in store.tables]
        saved['generation']=gen
        write(OUT/'store.json',saved);write(OUT/'correction_audit.json',store.correction_audit)
        write(OUT/'review_audit.json',store.review_audit)
        records=exported.pop('records')
        (OUT/'records.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records)+'\n',encoding='utf-8')
        write(OUT/'links.json',{'generation':gen,**exported});write(OUT/'generation.json',gen)
        log('전체 교정 결과 생성 완료',tables=len(store.tables),records=len(records),elapsed_sec=round(time.perf_counter()-t,2))
    finally:probe.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['generate']);globals()[p.parse_args().stage]()
