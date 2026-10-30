import json,sys
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.lookup import lookup
from backend.agent.tools.calc.adapters import lookup_adapter
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
IDENT='2026-정오표1차/공통/8-5-8/기타기계';SP=ROOT/'data/drafts/specs/공통/8-5-8.json';AP=ROOT/'evals/runtime_validation/common-8-5-8-equipment-price-lookup-audit-2026-10-20.json'
CONFIG={354:(1,'p355-t1',[('7101-','고성능착정기',1),('7103-','하수관천공기(수동식)',1),('7104-','상수도관천공기(수동식)',1),('7106-','골재살포기',1),('7110-','진공흡입준설차',2),('7120-','버킷식준설기',1),('7202-','자동세륜기(롤타입)',2),('7204-','물탱크(살수차)',5)]),355:(0,'p356-t0',[('7205-','이동식 임목파쇄기',3),('7206-','부착용 집게',3),('7210-','동력분무기',1),('7330-','라인마커',1),('7360-','차선제거기',2),('7430-','윈치(수동)',5),('7431-','윈치(자동)',4),('7505-','발전기',11),('7611-','용접기(교류)',4),('7612-','용접기(직류)',3),('7613-','용착기',2)]),356:(0,'p357-t0',[('7613-','용착기',4),('7614-','알곤용접기',1),('7620-','절단기',2),('7621-','프라즈마절단기',1),('7730-','건설용펌프(자흡식)',5),('7740-','수중모터펌프',3),('7750-','취부기',2),('7770-','실사출기',1),('7811-','엔진(가솔린)',6),('7812-','엔진(디젤)',11),('7830-','우레탄폼분사용기구',1),('7930-','모터',2)]),357:(0,'p358-t0',[('7930-','모터',12),('7935-','모터(쉴드TBM용)',1),('7950-','레일천공기',1),('7951-','파워렌치',1),('7952-','침목천공기',1),('7953-','타이템퍼',1),('7954-','양로기',1),('7991-','모르타르펌프',3),('7992-','모르타르믹서',1),('7993-','양수기',1),('7994-','PowerTrowel',1),('7995-','배관파이프',1)])}
def source_rows(pdf,i,table_idx):
 m=pdf[i].find_tables().tables[table_idx].extract()[1]
 return [x.strip() for x in m[1].splitlines()],[x.strip() for x in m[2].splitlines()]
def main():
 pdf=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');pkg=json.loads(SP.read_text(encoding='utf8'));s=pkg['draft'];tables={t['id']:t for t in s['tables']};records=s['inputs'][0]['source_record_map'];routes=0
 for pi,(table_idx,source_id,groups) in CONFIG.items():
  rawcodes,prices=source_rows(pdf,pi,table_idx);assert len(rawcodes)==len(prices)
  offset=0;prefix=None
  for gi,(group_prefix,name,count) in enumerate(groups):
   tid=f'other-machine-{pi+1}-{gi}';assert tables[tid]['source_table_id']==source_id;table=tables[tid]
   for code_raw,price in zip(rawcodes[offset:offset+count],prices[offset:offset+count]):
    if len(code_raw)==9 and code_raw[4]=='-':prefix=code_raw[:5];full=code_raw
    elif code_raw.startswith('-'):full=(prefix or group_prefix)+code_raw[1:]
    else:full=(prefix or group_prefix)+code_raw
    assert full.startswith(group_prefix),(full,group_prefix)
    assert code_raw in table['values'],(tid,code_raw)
    row=table['values'][code_raw];assert row=={'기종':name,'분류번호':code_raw,'가격(￦)':price},(full,row,name,price)
    assert records[full]=={'table_id':tid,'row':code_raw}
    result=lookup(s,{'machine_code':full});assert result['status']=='computed' and result['value']==row,(full,result)
    assert all(c.get('internal_id')==source_id for c in result['provenance']['citations'])
    routes+=1
   offset+=count
  assert offset==len(rawcodes),(pi,offset,len(rawcodes))
 assert routes==117 and routes==len(records)==len(s['inputs'][0]['allowed_values'])
 empty=lookup(s,{});assert empty['status']=='ask' and empty['missing']==['machine_code']
 sample=next(iter(records));adapted=lookup_adapter(s,{'machine_code':sample});assert adapted['status']=='computed' and adapted.get('reference_only') is True
 valid=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert valid['ok'],valid
 idxp=ROOT/'data/drafts/executable.json';idx=json.loads(idxp.read_text(encoding='utf8'))
 if IDENT not in idx['executable']:
  assert any(x['id']==IDENT for x in idx['skipped']);idx['skipped']=[x for x in idx['skipped'] if x['id']!=IDENT];idx['executable'].append(IDENT);idx['executable'].sort();idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 load_specs.cache_clear();active=compute({'spec_id':IDENT,'inputs':{'machine_code':sample}});assert active['status']=='COMPUTED' and active['result'].get('reference_only') is True,active
 audit={'id':IDENT,'status':'pass','physical_pages':[355,356,357,358],'printed_pages':[299,300,301,302],'machine_group_tables':len(tables),'source_rows':routes,'independently_compared_source_cells':routes*3,'exact_machine_code_routes':routes,'active_compute':'pass; lookup adapter preserves reference_only','citation_validation':'pass for each selected row','unit':'original price cell in won, source string unchanged','scope':'reference lookup only; no quantity multiplication or site applicability date assumed','visual_source_images':[f'evals/runtime_validation/source-8-5-8-p{x}.png' for x in [355,356,357,358]]}
 AP.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(audit,ensure_ascii=False))
if __name__=='__main__':main()
