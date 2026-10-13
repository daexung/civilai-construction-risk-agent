"""원문 대조 교정 자료를 검색 입력에 적용한다. 파싱 원본 파일은 바꾸지 않는다.

교정 자료(corrections/*.json)는 PDF 해시, 입력 해시, 원문 위치, 대상 원문 식별자, 기존 소속을 고정한다.
적용할 때 PDF 영역의 글자를 다시 읽고, 대상이 기존 소속과 순서에 그대로 있는지 확인한다. 하나라도 다르면 거부한다.
새 제목·기준 노드는 원문 대조로 추가한 항목이며 ODL 항목 번호를 갖지 않는다(odl_id 없음, 'corr:' 식별자).
"""
import json
import re
from pathlib import Path

import pymupdf

CORRECTION_FILES = [Path(__file__).resolve().parents[1] / 'corrections/shoulder_sections.json']


class CorrectionRejected(ValueError):
    pass


def load(paths=None):
    return [json.loads(Path(p).read_text(encoding='utf-8')) for p in (paths or CORRECTION_FILES)]


def pdf_text(page, bbox_pt):
    r = pymupdf.Rect(bbox_pt) + (-1, -1, 1, 1)
    return re.sub(r'\s+', ' ', page.get_text('text', clip=r)).strip()


def check(corr, manifest, pdf_path, store, node_order, node_section_before, toc):
    """적용 전 확인. 문제 목록이 비어 있지 않으면 거부한다."""
    bad = []
    files = manifest['files']
    if corr['pdf_sha256'] != files['pdf']['sha256']:
        bad.append('PDF 해시 불일치')
    for k, v in corr['inputs_sha256'].items():
        if files[k]['sha256'] != v:
            bad.append(f'입력 해시 불일치: {k}')
    texts_by_page = {}
    for x in store['headings'] + store['notes'] + store['basis']:
        texts_by_page.setdefault(x['page'], []).append(x['text'])
    with pymupdf.open(pdf_path) as pdf:
        for s in corr['sections']:
            cid, page = s['correction_id'], pdf[s['page'] - 1]
            for key in ('heading_pdf', 'basis_pdf'):
                got = pdf_text(page, s[key]['bbox_pt'])
                if got != s[key]['text']:
                    bad.append(f"{cid}: PDF {key} 글자 불일치 {got!r} != {s[key]['text']!r}")
            if any(s['title_raw'] in t for t in texts_by_page.get(s['page'], [])):
                bad.append(f'{cid}: 원시 출력에 이미 같은 제목 노드가 있음(교정 대상 아님)')
            first, nxt = s['members'][0], s['next_heading_node_id']
            if first not in node_order or nxt not in node_order:
                bad.append(f'{cid}: 대상 또는 다음 제목 노드 없음')
                continue
            between = sorted((o, nid) for nid, o in node_order.items() if node_order[first] <= o < node_order[nxt])
            if [nid for _, nid in between] != s['members']:
                bad.append(f'{cid}: 다음 제목 전 노드가 교정 자료와 다름 {[nid for _, nid in between]}')
            for nid in s['members']:
                prev = node_section_before.get(nid)
                if prev is None or not prev.endswith(':' + s['expected_previous_section']):
                    bad.append(f'{cid}: {nid}의 기존 소속이 {prev}(기대 {s["expected_previous_section"]})')
            t = toc.get((s['division'], s['number']))
            if not t or t['title'] != s['title'] or t['printed_page'] != s['printed_page']:
                bad.append(f'{cid}: 목차 항목과 다름 {t}')
    if bad:
        raise CorrectionRejected('; '.join(bad))


def correction_nodes(s, page_height, region, division):
    def native(b):
        return [b[0], round(page_height - b[3], 2), b[2], round(page_height - b[1], 2)]

    base = {'page': s['page'], 'doc_order': None, 'odl_id': None, 'parent_node_id': None,
            'division': division, 'region': region}
    meta = {'origin': 'pdf_correction', 'correction_id': s['correction_id'], 'insert_before': s['members'][0],
            'evidence': s['evidence'], 'bbox_origin': '왼쪽 아래(PDF 점, 다른 노드와 같음)'}
    return [dict(base, node_id=f"corr:{s['correction_id']}:heading", kind='heading', text=s['title_raw'],
                 bbox=native(s['heading_pdf']['bbox_pt']), structure=dict(meta, role='section_heading')),
            dict(base, node_id=f"corr:{s['correction_id']}:basis", kind='basis', text=s['basis_pdf']['text'],
                 bbox=native(s['basis_pdf']['bbox_pt']), structure=dict(meta, role='basis'))]
