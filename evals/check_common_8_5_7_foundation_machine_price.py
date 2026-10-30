import json,sys
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.lookup import lookup
from backend.agent.tools.calc.adapters import lookup_adapter
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
IDENT='2026-정오표1차/공통/8-5-7/기초공사용기계';SP=ROOT/'data/drafts/specs/공통/8-5-7.json';AP=ROOT/'evals/runtime_validation/common-8-5-7-foundation-machine-price-lookup-audit-2026-10-20.json'
CONFIG={352:(1,'p353-t1',[('6105-','그라우팅 믹서',2),('6202-','그라우팅 펌프',3),('6330-','디젤 파일 해머',4),('6408-','보링 기계',1)]),353:(0,'p354-t0',[('6408-','보링 기계',6),('6410-','오거',5),('6510-','오실레이터',5),('6515-','로테이터',1),('6516-','유압 파워 팩',4),('6517-','리버스 서큘레이션 드릴',5),('6518-','전회전식 천공기',5),('6530-','진동 파일 해머 (전동식)',6),('6532-','진동 파일 해머 (유압식)',1)]),354:(0,'p355-t0',[('6540-','워터 젯트',1),('6550-','유압식 압입 인발기',1),('6630-','유압 파일 해머',5),('6701-','PBD 천공기 (유압식)',2),('6801-','고압 분사 전용 장비',1),('6802-','파일 천공 전용 장비',6),('6803-','다짐 말뚝 전용 장비',2),('6901-','자동화 믹서 플랜트',1)])}
def get_source(pdf,i,t):
 z=pdf[i].find_tables().tables[t].extract()[1];return [a.strip() for a in z[1].splitlines()],[a.strip() for a in z[2].splitlines()]
def main():
 pdf=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');pkg=json.loads(SP.read_text(encoding='utf8'));s=pkg['draft'];tables={t['id']:t for t in s['tables']};rec=s['inputs'][0]['source_record_map'];n=0
 for pi,(ti,source_id,groups) in CONFIG.items():
  rawcodes,prices=get_source(pdf,pi,ti);assert len(rawcodes)==len(prices);pos=0;prefix=None
  for gi,(gp,name,count) in enumerate(groups):
   tid=f'foundation-machine-{pi+1}-{gi}';assert tables[tid]['source_table_id']==source_id
   for raw,price in zip(rawcodes[pos:pos+count],prices[pos:pos+count]):
    if len(raw)==9 and raw[4]=='-':prefix=raw[:5];full=raw
    elif raw.startswith('-'):full=(prefix or gp)+raw[1:]
    else:full=(prefix or gp)+raw
    assert full.startswith(gp),(full,gp)
    assert tables[tid]['values'][raw]=={'기종':name,'분류번호':raw,'가격(￦)':price}
    assert rec[full]=={'table_id':tid,'row':raw}
    result=lookup(s,{'machine_code':full});assert result['status']=='computed' and result['value']==tables[tid]['values'][raw]
    assert all(c.get('internal_id')==source_id for c in result['provenance']['citations'])
    n+=1
   pos+=count
  assert pos==len(rawcodes),(pi,pos,len(rawcodes))
 assert n==67==len(rec)
 adapted=lookup_adapter(s,{'machine_code':next(iter(rec))});assert adapted['status']=='computed' and adapted.get('reference_only')
 valid=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert valid['ok'],valid
 ip=ROOT/'data/drafts/executable.json';idx=json.loads(ip.read_text(encoding='utf8'))
 if IDENT not in idx['executable']:
  assert any(x['id']==IDENT for x in idx['skipped']);idx['skipped']=[x for x in idx['skipped'] if x['id']!=IDENT];idx['executable'].append(IDENT);idx['executable'].sort();ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 load_specs.cache_clear();active=compute({'spec_id':IDENT,'inputs':{'machine_code':next(iter(rec))}});assert active['status']=='COMPUTED' and active['result'].get('reference_only')
 audit={'id':IDENT,'status':'pass','physical_pages':[353,354,355],'printed_pages':[297,298,299],'machine_groups':len(tables),'source_rows':n,'independently_compared_source_cells':n*3,'exact_classification_code_routes':n,'active_compute':'pass; reference_only','draft_validation':'pass','page_images':[f'evals/runtime_validation/source-8-5-7-p{x}.png' for x in [353,354,355]],'scope':'original equipment price reference only; no site applicability or quantity multiplier assumed'}
 AP.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(audit,ensure_ascii=False))
if __name__=='__main__':main()
