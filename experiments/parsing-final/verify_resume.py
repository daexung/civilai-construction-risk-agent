"""Verify the resumed full output, preserving a concrete per-table decision ledger."""
import sys,json,collections,re,copy,tempfile,ast,unicodedata
from pathlib import Path
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));import run
import pymupdf,line_regrid as lr, reviewed_tables as rt,source_corrections as sc,diagram_tables as dt
sys.stdout.reconfigure(encoding='utf-8')
old=run.read(run.PREV/'store.json');new=run.read(W/'out'/'store.json')
manifest=run.read(W/'reviewed_tables.json');targets={e['table_id'] for e in manifest['tables']}
diagrams=run.read(W/'diagram_tables.json')['tables']
O={t['table_id']:t for t in old['tables']};N={t['table_id']:t for t in new['tables']}
records=[json.loads(x) for x in (W/'out'/'records.jsonl').read_text(encoding='utf-8').splitlines()]
oldrecords=[json.loads(x) for x in (run.PREV/'records.jsonl').read_text(encoding='utf-8').splitlines()]
links=run.read(W/'out'/'links.json')['record_links'];gen=run.read(W/'out'/'generation.json')
checks=[]
def check(name,ok,detail=None):checks.append({'name':name,'passed':bool(ok),'detail':detail})
def groups(rs):
    g=collections.defaultdict(list)
    for r in rs:
        if r.get('table_id'):g[r['table_id']].append({k:r.get(k) for k in ('text','section','page','kind','table_id','bbox','structure')})
    return g
og=groups(oldrecords);ng=groups(records)
check('전체 982쪽과 표 식별자 보존',new['pages']==list(range(1,983)) and set(O)==set(N) and len(N)==2328)
check('레코드 식별자 중복 없음',len({r['record_uid'] for r in records})==len(records))
check('레코드와 연결 정보 순서 일치',len(records)==len(links) and all(r['record_uid']==l['record_uid'] and i==l['record_idx'] for i,(r,l) in enumerate(zip(records,links))))
check('실제 실행 코드 버전 일치',gen['code_sha256']=={p.name:sc.digest(p) for p in (W/'pipeline').glob('*.py')})
for key,p in [('pdf_sha256',run.PDF),('raw_sha256',run.RAW),('corrections_sha256',run.CORRECTIONS),('completeness_sha256',W/'completeness.json'),('row_mappings_sha256',W/'row_mappings.json'),('reviewed_tables_sha256',W/'reviewed_tables.json'),('diagram_tables_sha256',W/'diagram_tables.json')]:
    check(key+' 일치',gen[key]==sc.digest(p))
for p in (W/'pipeline').glob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
check('전체 후보 코드 문법 확인',True)
oldheld={k for k,t in O.items() if t['flags']}
check('기존 보류 286개와 작업 대상 일치',targets==oldheld and len(targets)==286)
diff=[k for k in O if og[k]!=ng[k]]
outside=[k for k in diff if k not in targets]
check('대상 밖 표의 내용과 상태 동일',not outside,outside)
# 변경(본문 완전성): 하위 글 추가로 문서 순서 번호(order)만 밀린다. 순서 번호를 뺀 기존 항목은 그대로여야 하고,
# 새 주석은 하위 글 표시(nesting)가 있는 것만 허용한다. 기존 주석이 사라지거나 바뀌면 실패한다.
def no_order(xs):return [{k:v for k,v in x.items() if k!='order'} for x in xs]
check('기준·제목·논리 표·쪽 경계 보존(순서 번호 제외)',all(no_order(old[k])==no_order(new[k]) for k in ('basis','headings')) and all(old[k]==new[k] for k in ('logical_tables','boundaries','context_out')))
check('기존 주석 원문과 연결 보존(순서 번호 제외)',no_order(old['notes'])==no_order([n for n in new['notes'] if not n.get('nesting')]))
check('새 본문은 모두 하위 글 표시와 원시 위치를 가짐',all(n['nesting']['container_odl_ids'] and n['odl_id'] and n['bbox'] for n in new['notes'] if n.get('nesting')))
ledger=[]
for e in manifest['tables']:
    tid=e['table_id'];t=N[tid];expected=diagrams[tid]['after'] if tid in diagrams else e['expected_cells']
    coordinates=sorted([c['r0'],c['r1'],c['c0'],c['c1']] for c in t['cells'])
    check(tid+' 기대 칸 구조',coordinates==sorted(c[:4] for c in expected))
    check(tid+' 원문 보관과 대조 근거',t.get('source_review',{}).get('source_sha256')==e['expected_source_sha256'])
    check(tid+' 실제 레코드 전달',bool(ng[tid]))
    if e.get('graphic'):
        got={c['src']['odl_id']:c for c in t['cells'] if c.get('graphic_conditions')}
        check(tid+' 모든 값에 계단선 번호·출력·위치 연결',len(got)==len(e['graphic']['cells']) and all(got[x['odl_id']]['graphic_conditions']==x for x in e['graphic']['cells']))
        gl=[l for l in links if l.get('table_id')==tid or l.get('host_table_id')==tid]
        check(tid+' 내보낸 값의 계단선 연결',{x['odl_id'] for l in gl for x in l.get('graphic_conditions',[])}==set(got))
        check(tid+' 모든 행의 출력표 출처 연결',all(l.get('graphic_legend',{}).get('odl_id')==e['graphic']['legend_odl_id'] for l in gl))
    state='미해결' if t['flags'] else '교정 완료'
    ledger.append({'table_id':tid,'page':t['page'],'before_reasons':[f['code'] for f in O[tid]['flags']],
                   'status':state,'evidence':e['evidence'],'remaining':t['flags'],'before_records':len(og[tid]),'after_records':len(ng[tid])})
check('새로 보류가 생긴 대상 밖 표 없음',all(not t['flags'] for k,t in N.items() if k not in targets))
check('68쪽 각 위치와 값 대응',len(ng['full-p68-ocorrection:p68-t0'])==12 and any('냉온수배관 - 기계실' in r['text'] and '소 75' in r['text'] for r in ng['full-p68-ocorrection:p68-t0']) and any('냉온수배관 - 옥내일반' in r['text'] and '소 45' in r['text'] for r in ng['full-p68-ocorrection:p68-t0']))
check('823쪽 Steel plate 열 개 규격과 Channel 두 규격',sum('Steel plate' in r['text'] for r in ng['full-p823-o117292'])==10 and sum('Channel' in r['text'] for r in ng['full-p823-o117292'])==2)
check('555쪽 기존 13행 유지',len(ng['full-p555-o80398'])==13 and og['full-p555-o80398']==ng['full-p555-o80398'])
check('502쪽 분수식 전달 유지',all(og[k]==ng[k] for k in O if O[k]['page']==502))
check('기존 칸·행·누락 교정 자료 그대로',sc.digest(run.CORRECTIONS)==sc.digest(run.PREV/'corrections.json') and all(sc.digest(W/p)==sc.digest(run.PREV/p) for p in ('row_mappings.json','completeness.json')))
check('미확정 원문 수량 두 값 보존',len(N['full-p758-o107176']['flags'])==1 and any('0.215 0.415' in r['text'] and r['structure']['status']=='uncertain' for r in ng['full-p758-o107176']))
check('443쪽 괄호 그림 속도 세 값 전달',all(any(x in r['text'] for r in ng['full-p443-o59652']) for x in ('적재 : 5.5km/hr','공선(空船) : 9.3km/hr','독항시(獨航時) : 12.9km/hr')))
check('523쪽 촬영운항시간 구성 네 항목이 (촬영운항시간) 행에 전달',sum(('(촬영운항시간)' in r['text']) and any(x in r['text'] for x in ('계기비행시간','왕복운항시간','순촬영운항시간','예비운항시간')) for r in ng['full-p523-o75093'])==4)
allcells={c['cell_id'] for t in new['tables'] for c in t['cells']}
check('모든 레코드 칸 연결 대상 존재',all(set(l.get('cell_ids',[]))<=allcells for l in links))
newflag=[{'table_id':k,'page':t['page'],'flags':t['flags']} for k,t in N.items() if t['flags']]
run.write(W/'out'/'remaining_review.json',newflag)
run.write(W/'out'/'resolution_ledger.json',ledger)
run.write(W/'out'/'outside_changes.json',outside)
run.write(W/'out'/'summary.json',{'pages':982,'tables':2328,'records':len(records),'original_held':286,
 'corrected':sum(x['status']=='교정 완료' for x in ledger),'unresolved':len(newflag),'outside_changed':len(outside),
 'uncertain_records':sum(r.get('structure',{}).get('status')=='uncertain' for r in records)})

# Guard cases use the actual production apply path and fail before exporting anything.
with tempfile.TemporaryDirectory(dir=W/'out') as td:
    test=Path(td)/'bad.json'
    for label,mutate in [('문서 버전',lambda m:m.update(pdf_sha256='0'*64)),
                         ('엔진 버전',lambda m:m.update(engine_sha256='0'*64)),
                         ('교정 전 내용',lambda m:m['tables'][0].update(expected_source_sha256='0'*64)),
                         ('기대 구조',lambda m:m['tables'][0]['expected_cells'][0].__setitem__(4,'WRONG'))]:
        bad=copy.deepcopy(manifest);mutate(bad);run.write(test,bad)
        source={e['odl_id']:copy.deepcopy(e['source_node']) for e in bad['tables']}
        doc={'kids':list(source.values())}
        try:rt.apply(doc,test,run.RAW,run.PDF,run.CORRECTIONS,W/'completeness.json',W/'row_mappings.json');rejected=False
        except ValueError:rejected=True
        check(label+' 불일치 거부',rejected)
    bad=run.read(W/'diagram_tables.json');bad['tables']['full-p443-o59652']['cells'][1]['text']='적재 : 5.0km/hr';run.write(test,bad)
    d2={'kids':[copy.deepcopy(e['source_node']) for e in manifest['tables'] if e['table_id']=='full-p443-o59652']}
    try:dt.apply(d2,test,run.RAW,run.PDF,W/'reviewed_tables.json');rejected=False
    except ValueError:rejected=True
    check('그림 표 원문 글자 불일치 거부',rejected)
    bad=run.read(W/'diagram_tables.json');bad['reviewed_tables_sha256']='0'*64;run.write(test,bad)
    try:dt.apply({'kids':[]},test,run.RAW,run.PDF,W/'reviewed_tables.json');rejected=False
    except ValueError:rejected=True
    check('그림 표 앞 교정 자료 버전 불일치 거부',rejected)
run.write(W/'out'/'resume_checks.json',{'checks':checks,'passed':sum(c['passed'] for c in checks),'failed':sum(not c['passed'] for c in checks)})
print('SUMMARY',run.read(W/'out'/'summary.json'))
print('FAILED', [c for c in checks if not c['passed']])
sys.exit(1 if any(not c['passed'] for c in checks) else 0)
