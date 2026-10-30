import json,sys,hashlib
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.lookup import lookup
from backend.agent.tools.calc.adapters import lookup_adapter
from backend.agent.tools.source.citation import resolve_cites
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
from backend.agent.nodes.compute import compute
IDENT='2026-정오표1차/공통/8-4-3/운반및하역기계'
SP=ROOT/'data/drafts/specs/공통/8-4-3.json';AP=ROOT/'evals/runtime_validation/common-8-4-3-machine-lookup-audit-2026-10-20.json'
CONFIG={333:[('2101-','크레인(무한궤도)',15),('2104-','크레인(타이어) 10–70ton',11)],334:[('2104-','크레인(타이어) 80–300ton',8),('2105-','트럭 탑재형 크레인',6),('2106-','고소작업차',3),('2107-','터널용 고소작업차',1),('2208-','타워크레인',5),('2330-','디젤기관차',2),('2402-','경운기',1),('2502-','지게차',5),('2602-','트랙터(타이어)',4),('2702-','트럭 트랙터 및 평판 트레일러',4)]}
def page_rows(pdf,index):
 raw=pdf[index].find_tables().tables[0].extract()[1]
 codes=[x.strip() for x in raw[0].splitlines()];specs=[x.strip() for x in raw[2].splitlines()];fuel=[x.strip() for x in raw[3].splitlines()];misc=[x.strip() for x in raw[4].splitlines()];labor=[x.strip() for x in raw[5].splitlines()]
 if index==333:
  joined=[];i=0
  while i<len(specs):
   if i+1<len(specs) and specs[i+1].startswith('('):joined.append((specs[i]+' '+specs[i+1]).strip());i+=2
   else:joined.append(specs[i]);i+=1
  specs=joined
 assert len(codes)==len(specs)==len(fuel)==len(misc)==len(labor)
 prefix='2104-' if index==334 else None;expanded=[]
 for code in codes:
  if len(code)==9 and code[4]=='-':prefix=code[:5];expanded.append(code)
  else: assert prefix;expanded.append(prefix+code)
 return list(zip(expanded,specs,fuel,misc,labor))
def main():
 pdf=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');source={i:page_rows(pdf,i) for i in CONFIG}
 pkg=json.loads(SP.read_text(encoding='utf8'));s=pkg['draft'];tables={t['id']:t for t in s['tables']};map_group=s['inputs'][0]['source_table_map'];groups_seen=[];routes=0;source_cells=0
 for index,groups in CONFIG.items():
  offset=0
  for grp_i,(prefix,machine,count) in enumerate(groups):
   tid=f'machine-{index+1}-{grp_i}';table=tables[tid];source_id=f'p{index+1}-t0';assert table['source_table_id']==source_id
   group=next(g for g,x in map_group.items() if x==tid);assert group==machine
   entries=source[index][offset:offset+count];assert len(entries)==len(table['values'])==count
   for code,rawspec,fuel,misc,labor in entries:
    source_name=machine.removesuffix(' 10–70ton').removesuffix(' 80–300ton')
    spec=rawspec;extra=''
    if index==333 and prefix=='2101-' and '(' in spec:spec,extra=spec.split(' ',1)
    row=table['values'][spec]
    assert row['분류번호']==code and row['기계명']==source_name and row['규격']==spec
    assert row['주연료 (ℓ/hr)']==fuel and row['잡재료 (주연료의%)']==misc and row['조종원 (인/일)']==labor,(code,row,(fuel,misc,labor))
    if extra:assert row['규격 부가표기']==extra and table['source_column_map']['규격 부가표기']=='규격'
    out=lookup(s,{'machine_group':group,'equipment_spec':spec});assert out['status']=='computed',(group,spec,out)
    assert out['value']==row
    assert all(c.get('internal_id')==source_id for c in out['provenance']['citations'])
    for line in out['unit_lines']:
     for cite in line['citations']:
      assert cite.get('internal_id')==source_id
      assert cite.get('row')==spec
    routes+=1;source_cells+=len(row)
   offset+=count
  assert offset==len(source[index])
 assert routes==65 and source_cells==65*6+10
 # A dependent choice asks only exact rows from the selected source table.
 ask=lookup(s,{});assert ask['status']=='ask' and ask['missing']==['machine_group']
 group=next(iter(map_group));ask=lookup(s,{'machine_group':group});assert ask['status']=='ask' and len(ask['questions'][0]['allowed_values'])==15
 adapter=lookup_adapter(s,{'machine_group':group,'equipment_spec':next(iter(tables[map_group[group]]['values']))});assert adapter['status']=='computed' and adapter.get('reference_only') is True
 valid=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert valid['ok'],valid
 # The index transition makes the source-only lookup available through the active compute node.
 idxp=ROOT/'data/drafts/executable.json';idx=json.loads(idxp.read_text(encoding='utf8'));assert IDENT in [x['id'] for x in idx['skipped']]
 idx['skipped']=[x for x in idx['skipped'] if x['id']!=IDENT];idx['executable'].append(IDENT);idx['executable']=sorted(set(idx['executable']));idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 from backend.agent.rules.specs import load_specs;load_specs.cache_clear()
 active=compute({'spec_id':IDENT,'inputs':{'machine_group':group,'equipment_spec':next(iter(tables[map_group[group]]['values']))}})
 assert active['status']=='COMPUTED' and active['result'].get('reference_only') is True,active
 audit={'id':IDENT,'status':'pass','physical_pages':[334,335],'printed_pages':[278,279],'groups':len(tables),'source_rows_independently_compared':routes,'source_cells_independently_compared':source_cells,'lookup_routes':routes,'dependent_choice':'exact table-specific specification options pass','active_compute':'lookup_adapter via compute node; reference_only preserved','draft_validation':'pass','page_images':['evals/runtime_validation/source-8-4-3-p334.png','evals/runtime_validation/source-8-4-3-p335.png'],'scope':'all 65 original equipment/specification rows; reports hourly fuel, source misc-material percentage and operator person/day as reference values; no work-hour total or cost inference'}
 AP.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(audit,ensure_ascii=False))
if __name__=='__main__':main()
