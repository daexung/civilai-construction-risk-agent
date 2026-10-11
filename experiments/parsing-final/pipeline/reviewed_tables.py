"""Version-bound source review; no unreviewed table is changed."""
import json, hashlib, copy, collections, re
from pathlib import Path
import pymupdf
import source_corrections as sc
import line_regrid as lr

def object_digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def graphic_node(node, graphic):
    """Split an already merged N column by reviewed physical row boundaries."""
    import odl_tables as ot
    new=copy.deepcopy(node)
    for row in new['rows']:
        for cell in list(row['cells']):
            if cell['column number']!=2 or cell.get('row span',1)<=1 or cell['row number']<=2:continue
            nr=[r for r in graphic['N_rows'] if cell['row number']-1<=r['row']<cell['row number']-1+cell['row span']]
            if collections.Counter(re.findall(r'\d+',ot.cell_text(cell)))!=collections.Counter(str(r['N']) for r in nr):
                raise ValueError('묶인 N값 칸과 원문 행별 N값이 다름')
            row['cells'].remove(cell)
            for r in nr:
                cid=f"{cell['id']}:N{r['row']}"
                c=copy.deepcopy(cell)
                c.update({'id':cid,'row number':r['row']+1,'row span':1,'bounding box':r['bbox_native'],
                    'kids':[{'id':cid+':text','type':'paragraph','content':str(r['N']), 'bounding box':r['bbox_native']}],
                    '_regrid':{'kind':'source_N_row','orig_id':cell['id']}})
                new['rows'][r['row']]['cells'].append(c)
    new['_graphic']=graphic
    return new

def apply(doc, manifest_path, raw_path, pdf_path, corrections_path, completeness_path, rowmap_path):
    m=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    for key,p in [('pdf_sha256',pdf_path),('raw_sha256',raw_path),('corrections_sha256',corrections_path),
                  ('completeness_sha256',completeness_path),('row_mappings_sha256',rowmap_path),
                  ('engine_sha256',Path(lr.__file__))]:
        if sc.digest(p)!=m[key]: raise ValueError(f'표 원문 대조 자료의 버전 불일치: {key}')
    audit=[]
    with pymupdf.open(pdf_path) as pdf:
        raster_checked=set()
        for entry in m['tables']:
            # A reviewed parent may contain a reviewed child, so locate in the current tree.
            matches=[n for n in sc.walk(doc) if n.get('type')=='table' and n.get('id')==entry['odl_id']]
            if len(matches)!=1: raise ValueError(f"표 원문 대조 대상 수 불일치: {entry['table_id']}")
            node=matches[0]
            if object_digest(node)!=entry['expected_source_sha256']:
                raise ValueError(f"표 교정 전 내용 불일치: {entry['table_id']}")
            if entry.get('graphic'):
                new=graphic_node(node,entry['graphic'])
                for p,expected in entry['graphic']['raster_sha256'].items():
                    if p in raster_checked:continue
                    pix=pdf[int(p)-1].get_pixmap(matrix=pymupdf.Matrix(4,4),colorspace=pymupdf.csGRAY)
                    if hashlib.sha256(pix.samples).hexdigest()!=expected:raise ValueError('계단선 원문 그림 불일치')
                    raster_checked.add(p)
            else:
                new=lr.regrid(node,pdf[entry['page']-1],entry['config'],entry['config']['header_rows'])
            if lr.summary(new)!=entry['expected_cells']:
                raise ValueError(f"표 원문 대조 기대 구조 불일치: {entry['table_id']}")
            new['_reviewed']={'evidence':entry['evidence'],'source_sha256':entry['expected_source_sha256'],
                              'hold':entry.get('hold'),'resolved_holds':entry.get('resolved_holds',[])}
            node.clear();node.update(new)
            audit.append({'table_id':entry['table_id'],'char_check':new.get('_regrid',{}).get('char_check'),
                          'evidence':entry['evidence'],'source_sha256':entry['expected_source_sha256']})
    return doc,audit
