"""괄호 그림 표 교정(diagram_tables.json). reviewed_tables 적용 뒤에 실행한다.

443·523쪽 표는 괄호 그림의 일부만 표로 잡혔고, 나머지 글은 'text block' 안에 있어 어느 출력에도 없었다.
그림 전체를 칸으로 다시 만든다. 칸마다 원문 영역(bbox)을 고정하고, 적용할 때 그 영역의 PDF 글자를 다시 읽어
고정한 글과 같아야 한다. 원문·원시 출력·앞 교정 자료 해시와 교정 전 칸 목록이 다르면 적용을 거부한다.
"""
import json
from pathlib import Path
import pymupdf
import line_regrid as lr
import source_corrections as sc


def apply(doc, manifest_path, raw_path, pdf_path, reviewed_path):
    m = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    for key, p in (('pdf_sha256', pdf_path), ('raw_sha256', raw_path), ('reviewed_tables_sha256', reviewed_path),
                   ('engine_sha256', Path(lr.__file__))):
        if sc.digest(p) != m[key]:
            raise ValueError(f'그림 표 교정 자료의 버전 불일치: {key}')
    audit = []
    with pymupdf.open(pdf_path) as pdf:
        for tid, d in m['tables'].items():
            nodes = [n for n in sc.walk(doc) if n.get('type') == 'table' and n.get('id') == d['odl_id']]
            if len(nodes) != 1:
                raise ValueError(f'그림 표 교정 대상 수 불일치: {tid}')
            node = nodes[0]
            if lr.summary(node) != d['before']:
                raise ValueError(f'그림 표 교정 전 칸 내용 불일치: {tid}')
            page = pdf[d['page'] - 1]
            H = page.rect.height
            rows = [{'id': f"{node['id']}:d{r}", 'cells': []} for r in range(d['n_rows'])]
            for i, c in enumerate(d['cells']):
                text = lr.text_of(lr.page_chars(page, c['bbox_pt']))
                if text != c['text']:
                    raise ValueError(f"그림 표 칸 원문 글자 불일치: {tid} {c['text']!r} != {text!r}")
                b = c['bbox_pt']
                nb = [b[0], H - b[3], b[2], H - b[1]]
                cid = f"{node['id']}:d{i}"
                rows[c['r0']]['cells'].append({
                    'id': cid, 'type': 'table cell', 'row number': c['r0'] + 1, 'column number': c['c0'] + 1,
                    'row span': c.get('rs', 1), 'column span': c.get('cs', 1), 'bounding box': nb,
                    'kids': [{'id': f'{cid}:text', 'type': 'paragraph', 'content': text,
                              'page number': d['page'], 'bounding box': nb}],
                    '_regrid': {'kind': 'diagram_cell', 'orig_id': node['id'], 'source_bbox_pt': b}})
            bs = [c['bbox_pt'] for c in d['cells']]
            x0, y0, x1, y1 = min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)
            review = dict(node.get('_reviewed') or {})
            review['diagram'] = {'reason': d['reason'], 'source_text_nodes': d['source_text_nodes']}
            original_rows = node.get('number of rows')
            node.update({'rows': rows, 'number of rows': d['n_rows'], 'number of columns': d['n_cols'],
                         'bounding box': [x0, H - y1, x1, H - y0], '_header_override': 0, '_reviewed': review,
                         '_regrid': {'config': {'diagram': True, 'header_rows': 0}, 'header_rows': 0,
                                     'orig_rows': original_rows}})
            if lr.summary(node) != d['after']:
                raise ValueError(f'그림 표 결과가 고정한 칸과 다름: {tid}')
            audit.append({'kind': 'diagram', 'table_id': tid, 'reason': d['reason'],
                          'cells': [c['text'] for c in d['cells']]})
    return doc, audit
