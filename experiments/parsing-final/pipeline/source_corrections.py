"""Version-bound corrections applied to a copy of raw input, with original nodes retained.

The manifest contains reviewed regions and expected original text. It is not a
page-number rule in the parser. A different PDF or raw input is rejected.
"""
import copy
import re
import hashlib
import json
from pathlib import Path
import pymupdf
import odl_tables
import table_guard


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def walk(node):
    yield node
    for key in odl_tables.CHILD_KEYS:
        for child in node.get(key) or []:
            yield from walk(child)


def native(box, height):
    return [box[0], height-box[3], box[2], height-box[1]]


def cell_text_from_pdf(page, box):
    """Use glyph centres for column ownership and baseline for row ownership."""
    chars=[]
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for ch in span['chars']:
                    x0,y0,x1,y1=ch['bbox'];x=(x0+x1)/2;y=ch['origin'][1]
                    if box[0]<=x<=box[2] and box[1]<=y<=box[3]:
                        chars.append((y,x,ch['c']))
    lines=[]
    for c in sorted(chars):
        if lines and abs(c[0]-lines[-1][0][0])<1:
            lines[-1].append(c)
        else:
            lines.append([c])
    return '\n'.join(''.join(c[2] for c in sorted(line,key=lambda x:x[1])).strip() for line in lines).strip()


def recover_node(table, page, target):
    cm=table_guard.pymupdf_to_common(table,page.number+1)
    height=page.rect.height;tid='correction:'+target['old_table_id']
    rows=[{'id':f'{tid}:r{r}','cells':[]} for r in range(cm['n_rows'])]
    for i,c in enumerate(cm['cells']):
        box=native(c['bbox_pt'],height);cid=f'{tid}:c{i}'
        # A table.extract string and geometry are independently inspectable here.
        cell={'id':cid,'type':'table cell','row number':c['r0']+1,'column number':c['c0']+1,
              'row span':c['r1']-c['r0'],'column span':c['c1']-c['c0'],'bounding box':box,
              'kids':[{'id':f'{cid}:text','type':'paragraph','content':c['text'],
                       'page number':page.number+1,'bounding box':box}],
              '_source_kind':'pymupdf_correction'}
        rows[c['r0']]['cells'].append(cell)
    return {'id':tid,'type':'table','page number':page.number+1,
            'bounding box':native(cm['bbox_pt'],height),'number of rows':cm['n_rows'],
            'number of columns':cm['n_cols'],'rows':rows,'_source_kind':'pymupdf_correction',
            '_correction':{'kind':'missing_table','target':target['old_table_id'],
                           'bbox_pt':cm['bbox_pt'],'extractor':'PyMuPDF find_tables',
                           'reason':target['reason']}}


def apply(doc, raw_path, pdf_path, manifest_path, completeness=None):
    m=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if digest(pdf_path)!=m['pdf_sha256'] or digest(raw_path)!=m['raw_sha256']:
        raise ValueError('교정 문서 또는 원시 출력의 해시가 다릅니다.')
    nodes={n['id']:n for n in walk(doc) if 'id' in n};audit=[]
    with pymupdf.open(pdf_path) as pdf:
        for item in m['cells']:
            node=nodes[item['id']]
            if odl_tables.cell_text(node)!=item['expected_text']:
                raise ValueError(f"교정 전 칸 내용 불일치: {item['id']}")
            actual=cell_text_from_pdf(pdf[item['page']-1],item['bbox_pt'])
            if actual!=item['replacement']:
                raise ValueError(f"원문 글자 위치 대조 불일치: {item['id']}")
            original=copy.deepcopy(node)
            node['kids']=[{'id':f"correction:{item['id']}:text",'type':'paragraph',
                          'page number':item['page'],'content':actual,
                          'bounding box':node['bounding box']}]
            node['_correction']={'kind':'cell','original':original,'replacement':actual,
                                 'reason':'확인된 칸 경계 오류를 PDF 글자 중심 위치로 교정'}
            audit.append({'kind':'cell',**item})
        for item in m['formulas']:
            originals=[copy.deepcopy(nodes[i]) for i in item['ids']]
            if [n.get('content') for n in originals]!=item['expected_texts']:
                raise ValueError('수식 교정 전 내용 불일치')
            target=nodes[item['ids'][-1]]
            target['content']=item['replacement']
            target['bounding box']=native(item['bbox_pt'],pdf[item['page']-1].rect.height)
            target['_correction']={'kind':'formula','originals':originals,'replacement':item['replacement'],
                                   'bbox_pt':item['bbox_pt'],'reason':'원문 그림에서 확인한 분수식의 읽기용 표현'}
            skip=set(item['ids'][:-1]);doc['kids']=[n for n in doc['kids'] if n.get('id') not in skip]
            audit.append({'kind':'formula',**item})
        by_page={}
        for target in m['missing_tables']:by_page.setdefault(target['page'],[]).append(target)
        for p,targets in by_page.items():
            page=pdf[p-1];found=page.find_tables().tables
            replacements=[]
            for target in targets:
                a=pymupdf.Rect(target['bbox'])
                ranked=[]
                for t in found:
                    b=pymupdf.Rect(t.bbox);inter=(a&b).get_area();union=a.get_area()+b.get_area()-inter
                    ranked.append((inter/union if union else 0,t))
                score,table=max(ranked,key=lambda x:x[0],default=(0,None))
                if score<.8:
                    raise ValueError(f"누락 표 보충 영역 불일치: {target['old_table_id']} ({score})")
                fix=next((x for x in (completeness or {}).get('tables',[]) if x['target']==target['old_table_id']),None)
                if fix is None:
                    replacements.append(recover_node(table,page,target))
                    continue
                # 확인한 누락 칸: 원문 선·글자 위치로 정한 빠진 선분을 더해 같은 보충 경로로 다시 읽는다
                original=table_guard.pymupdf_to_common(table,p)
                added=page.find_tables(add_lines=[((s[0],s[1]),(s[2],s[3])) for s in fix['add_lines']]).tables
                fixed=max(added,key=lambda t:(a&pymupdf.Rect(t.bbox)).get_area()/(a|pymupdf.Rect(t.bbox)).get_area())
                cm=table_guard.pymupdf_to_common(fixed,p)
                got={'n_rows':cm['n_rows'],'n_cols':cm['n_cols'],'cells':[[c['r0'],c['r1'],c['c0'],c['c1'],c['text']] for c in cm['cells']]}
                if got!=fix['expected']:
                    raise ValueError(f"누락 보완 결과가 고정한 칸과 다름: {target['old_table_id']}")
                node=recover_node(fixed,page,target)
                node['_correction']['completeness']={'add_lines':fix['add_lines'],'line_basis':fix['line_basis'],
                    'original_cells':[[c['r0'],c['r1'],c['c0'],c['c1'],c['text']] for c in original['cells']],
                    'original_shape':[original['n_rows'],original['n_cols']],
                    'reason':'원문에 있으나 보충 표에 칸이 없거나 여러 칸이 합쳐진 내용. 원문 그림 대조로 확인'}
                replacements.append(node)
            old=[n for n in doc['kids'] if n.get('page number')==p];kept=[];removed=[]
            for n in old:
                b=n.get('bounding box');covered=False
                if b and n.get('type') not in {'table','heading'}:
                    rect=pymupdf.Rect(native(b,page.rect.height))
                    covered=any((rect&pymupdf.Rect(r['_correction']['bbox_pt'])).get_area()/max(rect.get_area(),1)>=.98
                                for r in replacements)
                (removed if covered else kept).append(n)
            # Existing node order is authoritative. Insert each recovered table
            # beside the first following source node, without reordering old nodes.
            for r in sorted(replacements,key=lambda n:-n['bounding box'][3]):
                pos=next((i for i,n in enumerate(kept) if n.get('bounding box')
                          and n['bounding box'][3]<=r['bounding box'][3]),len(kept))
                kept.insert(pos,r)
            indices=[i for i,n in enumerate(doc['kids']) if n.get('page number')==p]
            start=indices[0] if indices else next((i for i,n in enumerate(doc['kids']) if n.get('page number',0)>p),len(doc['kids']))
            doc['kids']=[n for n in doc['kids'] if n.get('page number')!=p]
            doc['kids'][start:start]=kept
            audit.append({'kind':'missing_tables','page':p,'tables':[r['_correction'] for r in replacements],
                          'removed_overlapping_nodes':removed})
    return doc,audit


def _lines(text):
    return [l for l in text.split('\n') if l.strip()]


def load_row_mappings(path, raw_path, pdf_path, corrections_path):
    """Reviewed row mappings, bound to the same PDF, raw output and cell corrections."""
    m=json.loads(Path(path).read_text(encoding='utf-8'))
    if (digest(pdf_path)!=m['pdf_sha256'] or digest(raw_path)!=m['raw_sha256']
            or digest(corrections_path)!=m['corrections_sha256']):
        raise ValueError('행 연결 교정 자료의 원문·원시 출력·교정 자료 해시가 다릅니다.')
    with pymupdf.open(pdf_path) as pdf:
        for t in m['tables']:
            for h in t['holds']:
                for r in h.get('regions',[]):
                    if cell_text_from_pdf(pdf[t['page']-1],r['bbox_pt'])!=r['pdf_text']:
                        raise ValueError(f"보류 근거 원문 영역 글자 불일치: {t['table_id']} {r['label']}")
    return {t['table_id']:t for t in m['tables']}


def confirm_rows(tb, entry):
    """Apply a reviewed mapping to one stored table. Any mismatch raises; nothing is applied silently.

    Confirmed rows keep every original line in the same cell (line range = whole cell). A cell spanning
    several rows stays one source cell that each row points to. Returns the extra hold flags.
    """
    cells={c['cell_id']:(i,c) for i,c in enumerate(tb['cells'])}
    for row in entry['rows']:
        g=row['grid_row']
        if g>=len(tb['row_map']) or g<tb['header_rows']:
            raise ValueError(f"행 연결 교정 대상 행 없음: {tb['table_id']} {g}")
        rm=tb['row_map'][g]
        if rm['odl_row']!=row['odl_row'] or rm['state']!='stacked_unsplit':
            raise ValueError(f"행 연결 교정 전 행 상태 불일치: {tb['table_id']} {g} {rm}")
        stacked=[c['cell_id'] for c in tb['cells'] if c['r0']==g and not c['has_nested_table'] and len(_lines(c['text_raw']))>=2]
        if stacked!=[x['cell_id'] for x in row['cells']]:
            raise ValueError(f"행 연결 교정 대상 칸 목록 불일치: {tb['table_id']} {g} {stacked}")
        for x in row['cells']:
            i,c=cells[x['cell_id']]
            if c['text_raw']!=x['expected_text'] or [c['r0'],c['r1']]!=x['rows']:
                raise ValueError(f"행 연결 교정 전 칸 내용 불일치: {x['cell_id']}")
            if (x['kind']=='여러 행에 공통으로 적용되는 칸')!=(c['r1']-c['r0']>1):
                raise ValueError(f"행 연결 판정과 원문 칸 병합 범위 불일치: {x['cell_id']}")
            lines=_lines(c['text_raw']);reading=x.get('reading')
            if reading is not None and re.sub(r'\s','',reading)!=re.sub(r'\s','',c['text_raw']):
                raise ValueError(f"읽기용 글이 원문 글자와 다름: {x['cell_id']}")
            c['row_mapping']={'kind':x['kind'],'rows':list(range(c['r0'],c['r1'])),'line_range':[0,len(lines)],
                              'lines':lines,'reading':reading or ' '.join(lines),'basis':row['basis'],
                              'source_image':entry['source_image']}
            if reading is not None:
                tb['common']['cells'][i]['text']=reading     # 레코드 읽기용. 원래 글(text_raw)은 그대로
        rm['state']='confirmed_single'
        rm['row_mapping']={'basis':row['basis'],'cell_ids':stacked,'source_image':entry['source_image']}
    flags=[]
    for h in entry['holds']:
        flags.append({'cell_id':(h.get('cell_ids') or [None])[0],'cell_ids':h.get('cell_ids',[]),'code':h['code'],
                      'severity':h['severity'],'detail':h['detail'],'regions':h.get('regions',[]),
                      'text':' / '.join(r['pdf_text'].replace('\n','·') for r in h.get('regions',[]))
                             or ' / '.join(cells[c][1]['text_raw'].replace('\n','·') for c in h.get('cell_ids',[]))})
    return flags


def fraction_reading(page, box):
    """Read a stacked fraction cell by geometry: each horizontal fraction bar has exactly one word
    above (numerator) and one below (denominator). Other words are operators between bars and the
    result line below. Returns (reading, evidence); raises if the layout is not exactly that."""
    rect=pymupdf.Rect(box)
    words=[w for w in page.get_text('words',clip=rect) if w[4].strip()]
    bars={}
    for d in page.get_drawings():
        for it in d['items']:
            if it[0]=='l' and abs(it[1].y-it[2].y)<0.2 and rect.contains(it[1]) and rect.contains(it[2]):
                bars[(round(min(it[1].x,it[2].x),1),round(it[1].y,1),round(max(it[1].x,it[2].x),1))]=1
    bars=sorted(bars)
    if not bars:raise ValueError('분수 막대가 없습니다.')
    used=set();parts=[];fracs=[]
    for x0,y,x1 in bars:
        above=[w for w in words if x0<=(w[0]+w[2])/2<=x1 and y-15<=w[3]<=y+0.5]
        below=[w for w in words if x0<=(w[0]+w[2])/2<=x1 and y-0.5<=w[1]<=y+15]
        if len(above)!=1 or len(below)!=1:raise ValueError(f'분수 막대 위·아래 글자가 하나씩이 아닙니다: {(x0,y,x1)}')
        used|={above[0],below[0]};fracs.append(f'{above[0][4]}/{below[0][4]}')
        parts+=[{'role':'numerator','text':above[0][4],'bbox':list(above[0][:4]),'bar':[x0,y,x1]},
                {'role':'denominator','text':below[0][4],'bbox':list(below[0][:4]),'bar':[x0,y,x1]}]
    ops=[];bottom=max(w[3] for w in used)
    for (a,b) in zip(bars,bars[1:]):
        op=[w for w in words if w not in used and a[2]<=(w[0]+w[2])/2<=b[0] and w[1]<bottom]
        if len(op)!=1:raise ValueError('분수 사이 연산 기호가 하나가 아닙니다.')
        used.add(op[0]);ops.append(op[0][4]);parts.append({'role':'operator','text':op[0][4],'bbox':list(op[0][:4])})
    rest=sorted((w for w in words if w not in used),key=lambda w:(w[1],w[0]))
    if any(w[1]<bottom for w in rest):raise ValueError('분수식 줄에 해석하지 못한 글자가 있습니다.')
    parts+=[{'role':'result','text':w[4],'bbox':list(w[:4])} for w in rest]
    reading=fracs[0]+''.join(f' {o} {f}' for o,f in zip(ops,fracs[1:]))+''.join(' '+w[4] for w in rest)
    return reading,{'bars':[list(b) for b in bars],'parts':parts}


def load_completeness(path, raw_path, pdf_path, corrections_path):
    """Recovered-table completeness corrections, bound to the same PDF, raw output and cell corrections.
    Fraction readings are rebuilt from the PDF and must match; their characters may differ from the
    original cell only by whitespace and one '/' per fraction bar."""
    m=json.loads(Path(path).read_text(encoding='utf-8'))
    if (digest(pdf_path)!=m['pdf_sha256'] or digest(raw_path)!=m['raw_sha256']
            or digest(corrections_path)!=m['corrections_sha256']):
        raise ValueError('누락 보완 교정 자료의 원문·원시 출력·교정 자료 해시가 다릅니다.')
    with pymupdf.open(pdf_path) as pdf:
        for f in m['fractions']:
            page=pdf[f['page']-1]
            reading,evidence=fraction_reading(page,f['bbox_pt'])
            if reading!=f['reading'] or evidence['bars']!=f['evidence']['bars']:
                raise ValueError(f"분수식 원문 위치 판독 불일치: {f['cell_id']}")
            plain=lambda s:sorted(re.sub(r'\s','',s))
            if plain(reading.replace('/',''))!=plain(f['expected_text']) or reading.count('/')!=len(evidence['bars']):
                raise ValueError(f"분수식 읽기용 글이 원래 글자와 다름: {f['cell_id']}")
    return m


def apply_completeness(tb, m):
    """Fraction readings and confirmed holds for one stored table. Cell text must match first."""
    cells={c['cell_id']:(i,c) for i,c in enumerate(tb['cells'])}
    for f in m['fractions']:
        if f['table_id']!=tb['table_id']:continue
        if f['cell_id'] not in cells or cells[f['cell_id']][1]['text_raw']!=f['expected_text']:
            raise ValueError(f"분수식 교정 전 칸 내용 불일치: {f['cell_id']}")
        i,c=cells[f['cell_id']]
        c['fraction_reading']={'reading':f['reading'],'evidence':f['evidence'],
                               'basis':'원문 분수 배치(막대 위 분자, 아래 분모)를 읽기 위한 표현. 원래 칸 글은 text_raw'}
        tb['common']['cells'][i]['text']=f['reading']
    return [{'cell_id':None,'cell_ids':[],'code':h['code'],'severity':h['severity'],'detail':h['detail'],'text':''}
            for h in m['holds'] if h['table_id']==tb['table_id']]
