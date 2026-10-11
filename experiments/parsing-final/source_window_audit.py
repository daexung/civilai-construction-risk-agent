"""Independent PDF-window character coverage for the reviewed source tables."""
import sys,collections,json,re,unicodedata
from pathlib import Path
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));import run
import pymupdf,line_regrid as lr,odl_tables as ot
sys.stdout.reconfigure(encoding='utf-8')
manifest=run.read(W/'reviewed_tables.json')
s=run.read(W/'out'/'store.json');tables={t['table_id']:t for t in s['tables']}
def normalized(s):return collections.Counter(re.sub(r'\s','',unicodedata.normalize('NFKC',s)))
results=[];numeric=[];page_glyphs={};numeric_checked=0
with pymupdf.open(run.PDF) as pdf:
    for e in manifest['tables']:
        tid=e['table_id'];page=pdf[e['page']-1];n=e['source_node'];H=page.rect.height
        b=n['bounding box'];box=[b[0],H-b[3],b[2],H-b[1]]
        if e['page'] not in page_glyphs:page_glyphs[e['page']]=lr.page_chars(page,list(page.rect))
        glyphs=page_glyphs[e['page']]
        inside=lambda rect:[ch for ch in glyphs if rect[0]<=ch[1]<=rect[2] and rect[1]<=ch[0]<=rect[3]]
        source=normalized(''.join(x[2] for x in inside(box)))
        # Nested table text is independently retained under its own table id.
        ids={tid}
        changed=True
        while changed:
            changed=False
            for t in s['tables']:
                if (t.get('nested_in') or {}).get('table_id') in ids and t['table_id'] not in ids:
                    ids.add(t['table_id']);changed=True
        stored=normalized(''.join(c['text_raw'] for k in ids for c in tables[k]['cells']))
        missing=source-stored
        before=normalized(ot.cell_text(n))
        preexisting=source-before
        results.append({'table_id':tid,'page':e['page'],'source_char_count':sum(source.values()),
                        'missing_characters':dict(missing),'source_vs_original_missing':dict(preexisting)})
        for c in tables[tid]['cells']:
            if c['r0']<tables[tid]['header_rows']:continue
            text=re.sub(r'\s','',c['text_raw'])
            if not text or not re.fullmatch(r'[\d,.+\-/%×~∼―–()①②③④⑤⑥⑦⑧⑨⑩]+',text):continue
            if not re.search(r'\d',text):continue
            numeric_checked+=1
            b=c['src']['bbox'];rect=[b[0],H-b[3],b[2],H-b[1]]
            actual=''.join(ch[2] for ch in inside(rect))
            diff=normalized(text)-normalized(actual)
            if diff:numeric.append({'table_id':tid,'cell_id':c['cell_id'],'text':c['text_raw'],'source':actual,'missing_from_pdf':dict(diff)})
run.write(W/'out'/'source_window_audit.json',results)
run.write(W/'out'/'numeric_position_audit.json',numeric)
findings=[r for r in results if r['missing_characters']]
print('Source windows',len(results),'with character differences',len(findings))
for r in findings:print(r)
print('Numeric cells checked',numeric_checked,'with source-position differences',len(numeric))
for r in numeric:print(r)
sys.exit(1 if findings or numeric else 0)
