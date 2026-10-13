"""최종 파싱 결과 -> 원문 노드·절 목록·참조 연결(PostgreSQL 적재용 행과 장부).

DB 없이 실행된다. 같은 입력과 코드면 같은 행·같은 식별자가 나온다. 입력 파일은 읽기만 한다.
"""
import bisect
import hashlib
import json
import re
from pathlib import Path

import corrections

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PF = ROOT / 'experiments/parsing-final'
INPUTS = {
    'records': PF / 'out/records.jsonl',
    'store': PF / 'out/store.json',
    'links': PF / 'out/links.json',
    'generation': PF / 'out/generation.json',
    'page_map': PF / 'page_map.json',
}
PDF = ROOT / 'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
EXPECTED = {'generation_id': 'complete-82c206c61e21', 'pages': 982, 'tables': 2328, 'records': 23481,
            'relations': 11823, 'references': 232}
CODE_FILES = [HERE / 'build_index.py', HERE / 'db.py', HERE / 'corrections.py', WORK / 'sql/20261011000100_rag_knowledge.sql',
              WORK / 'sql/20261011000200_rag_search_records.sql', WORK / 'corrections/shoulder_sections.json']
DOCUMENT_ID = 'pumsem-2026-errata1'
DIVISIONS = ('공통부문', '토목부문', '건축부문', '기계설비부문', '유지관리부문')
DIV_CODE = dict(zip(DIVISIONS, ('common', 'civil', 'arch', 'mech', 'maint')))

CHAPTER_RE = re.compile(r'^제\s*(\d{1,2})\s*장[_\s]*(\S.*)$')
GROUP_RE = re.compile(r'^(\d{1,2}-\d{1,2})(?![-\d])\s*(\S.*)$')
SECTION_RE = re.compile(r'^(\d{1,2}-\d{1,2}-\d{1,2})(?![-\d])\s*(\S.*)$')
LEADER_RE = re.compile(r'[·…]{3,}')
NUM_RE = re.compile(r'(?<![\d\-:])(\d{1,2}-\d{1,2}(?:-\d{1,2})?)(?![\d\-])')
SUBMARK_RE = re.compile(r'^\s*/?\s*(\d{1,2}\s*\.|[가-하]\s*\.|\(\d{1,2}\)|\[주\])')
LEVEL_RANK = {'chapter': 0, 'group': 1, 'section': 2}


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def norm(s):
    """비교용 정규화. 원문은 바꾸지 않는다."""
    return re.sub(r"[\s·･ㆍ.,/()\[\]‘’“”'\"~\-_]", '', s or '')


def read_inputs():
    files = {k: {'path': str(p.relative_to(ROOT)).replace('\\', '/'), 'bytes': p.stat().st_size, 'sha256': sha256(p)}
             for k, p in INPUTS.items()}
    files['pdf'] = {'path': str(PDF.relative_to(ROOT)).replace('\\', '/'), 'bytes': PDF.stat().st_size, 'sha256': sha256(PDF)}
    rd = lambda k: json.loads(INPUTS[k].read_text(encoding='utf-8'))
    data = {'store': rd('store'), 'links': rd('links'), 'generation': rd('generation'), 'page_map': rd('page_map'),
            'records': [json.loads(x) for x in INPUTS['records'].read_text(encoding='utf-8').splitlines()]}
    rels = data['links']['relations']
    counts = {'generation_id': data['generation']['id'], 'pages': len(data['generation']['pages']),
              'tables': len(data['store']['tables']), 'records': len(data['records']),
              'relations': len(rels), 'references': sum(r['type'] == 'reference' for r in rels),
              'record_links': len(data['links']['record_links']), 'headings': len(data['store']['headings']),
              'notes': len(data['store']['notes']), 'basis': len(data['store']['basis']),
              'skipped_text': len(data['store']['skipped_text']),
              'cells': sum(len(t['cells']) for t in data['store']['tables'])}
    mismatch = {k: (counts[k], v) for k, v in EXPECTED.items() if counts[k] != v}
    if data['generation']['pdf_sha256'] != files['pdf']['sha256']:
        mismatch['pdf_sha256'] = (files['pdf']['sha256'], data['generation']['pdf_sha256'])
    if mismatch:
        raise ValueError(f'입력이 기준과 다름: {mismatch}')
    code = {p.name: sha256(p) for p in CODE_FILES}
    rid_src = json.dumps({'inputs': {k: v['sha256'] for k, v in files.items()}, 'code': code}, sort_keys=True)
    manifest = {'files': files, 'counts': counts, 'expected': EXPECTED, 'code_sha256': code,
                'release_id': f"rk-{counts['generation_id']}-{hashlib.sha256(rid_src.encode()).hexdigest()[:12]}"}
    return data, manifest


# ---------------- 쪽 구역과 부문 ----------------
def page_regions(store, page_map):
    """부문 표지 쪽(‘2026’과 ‘X부문’ 제목이 함께 있는 쪽)으로 본문 부문 구간을 나눈다. 첫 표지 앞은 앞부분(목차)."""
    by_page = {}
    for h in store['headings']:
        by_page.setdefault(h['page'], []).append(h['text'].strip())
    for n in store['notes']:
        by_page.setdefault(n['page'], []).append(n['text'].strip())
    covers = {}
    for p, texts in by_page.items():
        divs = [t for t in texts if t in DIVISIONS]
        if divs and '2026' in texts:
            covers[p] = divs[0]
    first = min(covers)
    region, division, evidence = {}, {}, {}
    cur = None
    for p in range(1, len(page_map['pages']) + 1):
        if p in covers:
            cur = covers[p]
        region[p] = 'front' if p < first else 'cover' if p in covers else 'body'
        division[p] = cur if p >= first else None
        pm = page_map['pages'][str(p)]['division']
        evidence[p] = {'segment_division': division[p], 'page_map_division': pm,
                       'agree': None if pm is None or division[p] is None else pm == division[p]}
    # 앞부분 목차의 부문: 앞부분 안의 'X부문' 제목 쪽부터 다음 제목 쪽 전까지
    toc_div, cur = {}, None
    for p in range(1, first):
        hs = [t for t in by_page.get(p, []) if t in DIVISIONS]
        cur = hs[0] if hs else cur
        toc_div[p] = cur
    return region, division, toc_div, covers, evidence


# ---------------- 노드 ----------------
def build_nodes(store, region, division):
    nodes = []

    def add(node_id, kind, page, order, odl, bbox, text, parent, structure):
        nodes.append({'node_id': node_id, 'kind': kind, 'page': page, 'doc_order': order,
                      'odl_id': None if odl is None else str(odl), 'bbox': bbox, 'text': text, 'parent_node_id': parent,
                      'division': division.get(page), 'region': region.get(page, 'body'), 'structure': structure})

    drop = lambda d, ks: {k: v for k, v in d.items() if k not in ks}
    base = ('page', 'order', 'odl_id', 'bbox', 'text')
    for h in store['headings']:
        add(h['heading_id'], 'heading', h['page'], h['order'], h['odl_id'], h['bbox'], h['text'], None, drop(h, base))
    for n in store['notes']:
        add(n['note_id'], 'note', n['page'], n['order'], n['odl_id'], n['bbox'], n['text'], None, drop(n, base))
    for b in store['basis']:
        add(b['basis_id'], 'basis', b['page'], b['order'], b['odl_id'], b['bbox'], b['text'], None, drop(b, base))
    for t in store['tables']:
        parent = (t.get('nested_in') or {}).get('cell_id')
        add(t['table_id'], 'table', t['page'], t['order'], t['odl_id'], t['bbox_native'], None, parent,
            drop(t, ('cells', 'groups', 'page', 'order', 'odl_id')))
        for c in t['cells']:
            add(c['cell_id'], 'cell', t['page'], None, c['src']['odl_id'], c['src'].get('bbox'), c['text_raw'],
                t['table_id'], drop(c, ('text_raw',)))
        for gi, g in enumerate(t['groups']):
            add(f"{t['table_id']}:g{gi}", 'table_group', t['page'], None, None, None, None, t['table_id'], g)
    for s in store['skipped_text']:
        add(f"skip:{s['odl_id']}", 'skipped_text', s['page'], None, s['odl_id'], s['bbox'], s['text'], None, drop(s, base))
    ids = [n['node_id'] for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError('노드 식별자 중복')
    return nodes


# ---------------- 절 목록 ----------------
def parse_line(line, kind='note'):
    t = (line or '').strip()
    if not t or LEADER_RE.search(t):
        return None
    for level, rx in (('section', SECTION_RE), ('group', GROUP_RE), ('chapter', CHAPTER_RE)):
        m = rx.match(t)
        if m:
            rest = m.group(2)
            # 본문 글의 첫 줄은 짧은 제목만. ODL 제목 노드는 제목 뒤에 문장이 붙어도 받고 목차로 제목 길이를 정한다
            if kind != 'heading' and (re.search(r'다\.?\s*$', rest) or len(rest) > 80):
                return None
            return level, m.group(1), rest
    return None


def heading_lines(text, kind):
    """글 첫머리의 절 제목 줄들. 제목 아닌 줄이 나오면 멈춘다(문장 중간의 번호는 절로 보지 않는다).
    ODL 제목 하나에 두 제목이 붙은 경우('3-2 굴착 3-2-1 굴착(인력/토사)')는 같은 장 번호로 시작하는 곳에서 나눈다."""
    lines = (text or '').split('\n')
    if kind == 'heading' and len(lines) == 1:
        first = NUM_RE.match(lines[0].strip())
        if first:
            head = first.group(1).split('-')[0]
            lines = re.split(r'\s+(?=' + head + r'-\d{1,2}(?:-\d{1,2})?\s)', lines[0].strip())
    out = []
    for line in lines:
        parsed = parse_line(line, kind)
        if not parsed:
            break
        out.append((parsed, line.strip()))
    return out


TRAIL_RE = [re.compile(r"\s*\([^()]*\d{2}\s*년[^()]*\)\s*$"), re.compile(r"\s*\((?:단위\s*:)?[^()]*당\)\s*$")]


def align_prefix(raw, prefix_norm):
    """raw 글에서 정규화 글자 prefix_norm을 다 읽은 위치. 바로 뒤의 괄호·공백 같은 무시 글자도 함께 넘긴다."""
    i = c = 0
    while i < len(raw) and c < len(prefix_norm):
        c += bool(norm(raw[i]))
        i += 1
    while i < len(raw) and not norm(raw[i]) and raw[i] not in '/[(':
        i += 1
    return i


def clean_title(t):
    """끝에 붙은 개정 표기('05, '23년 보완)와 단위 기준(㎥당)을 뗀다. 원문 제목은 title_raw에 남는다."""
    prev = None
    while prev != t:
        prev = t
        for rx in TRAIL_RE:
            t = rx.sub('', t).strip()
    return t


def build_sections(store, region, division, page_map, toc_by_key, extra=None):
    """본문 구역의 번호 있는 제목 줄만 절로 둔다. 번호 없는 제목·품목 코드는 절로 만들지 않는다."""
    items = sorted([(h['order'], 'heading', h) for h in store['headings']]
                   + [(n['order'], 'note', n) for n in store['notes']]
                   + [(b['order'], 'basis', b) for b in store['basis']]
                   + [(t['order'], 'table', t) for t in store['tables']], key=lambda x: x[0])
    printed = {int(k): v['printed_page'] for k, v in page_map['pages'].items()}
    sections, by_key = [], {}
    stats = {'from_heading': 0, 'from_text_line': 0, 'split_merged_heading': 0, 'repeated': 0, 'title_trimmed_by_toc': 0}
    seg_end = {}
    for o, kind, x in items:
        if region[x['page']] == 'body':
            seg_end[division[x['page']]] = o + 1
    for o, kind, x in items:
        p = x['page']
        if region[p] != 'body' or kind not in ('heading', 'note') or x.get('nesting'):
            continue
        found = heading_lines(x['text'], kind)
        for k, ((level, number, title_raw), line) in enumerate(found):
            div = division[p]
            number_key = number if level != 'chapter' else f'ch{number}'
            key = (div, level, number_key)
            node_id = x['heading_id'] if kind == 'heading' else x['note_id']
            if key in by_key:
                sec = by_key[key]
                sec['evidence']['occurrences'].append({'node_id': node_id, 'page': p, 'line': line})
                sec['status'] = 'repeated_heading'
                stats['repeated'] += 1
                continue
            title = clean_title(title_raw)
            ev = {'source_kind': kind, 'line_index': k, 'printed_page': printed.get(p),
                  'page_map_division': page_map['pages'][str(p)]['division'], 'occurrences': []}
            toc = toc_by_key.get((div, number_key))
            if toc:
                ev['toc_title'] = toc['title']
                tt = norm(clean_title(toc['title']))
                if tt and norm(title).startswith(tt) and norm(title) != tt:
                    # 제목 줄에 본문이 붙은 경우: 목차 제목 길이까지만 제목으로 둔다(원문은 title_raw)
                    i = align_prefix(title, tt)
                    ev['title_before_toc_trim'] = title
                    title = title[:i].strip()
                    stats['title_trimmed_by_toc'] += 1
            status = ('body_heading' if kind == 'heading' and len(found) == 1 else
                      'body_heading_split' if kind == 'heading' else 'body_text_first_line')
            stats['from_heading' if kind == 'heading' else 'from_text_line'] += 1
            stats['split_merged_heading'] += int(kind == 'heading' and len(found) > 1)
            sec = {'section_id': f"{DOCUMENT_ID}:{DIV_CODE[div]}:{number_key}", 'document_id': DOCUMENT_ID,
                   'division': div, 'level': level, 'number': number_key, 'title': title,
                   'title_raw': line, 'heading_node_id': node_id, 'parent_section_id': None,
                   'start_order': o, 'end_order': None, 'first_page': p, 'last_page': p,
                   'status': status, 'evidence': ev}
            by_key[key] = sec
            sections.append(sec)
    # 원문 대조 교정으로 추가한 절. 기존 항목의 순서 번호는 바꾸지 않고, 첫 소속 항목의 순서에서 시작한다
    order_of = {x.get('heading_id') or x.get('note_id') or x.get('basis_id') or x.get('table_id'): o for o, _, x in items}
    for c in extra or []:
        key = (c['division'], c['level'], c['number'])
        if key in by_key:
            raise ValueError(f'교정할 절이 이미 있음: {key}')
        p = c['page']
        sec = {'section_id': f"{DOCUMENT_ID}:{DIV_CODE[c['division']]}:{c['number']}", 'document_id': DOCUMENT_ID,
               'division': c['division'], 'level': c['level'], 'number': c['number'], 'title': c['title'],
               'title_raw': c['title_raw'], 'heading_node_id': f"corr:{c['correction_id']}:heading", 'parent_section_id': None,
               'start_order': order_of[c['members'][0]], 'end_order': None, 'first_page': p, 'last_page': p,
               'status': 'pdf_correction',
               'evidence': {'source_kind': 'pdf_correction', 'correction_id': c['correction_id'], 'printed_page': printed.get(p),
                            'page_map_division': page_map['pages'][str(p)]['division'], 'occurrences': [],
                            'toc_title': (toc_by_key.get((c['division'], c['number'])) or {}).get('title'),
                            'pdf_heading': c['heading_pdf'], 'evidence': c['evidence']}}
        by_key[key] = sec
        sections.append(sec)
        stats['pdf_correction'] = stats.get('pdf_correction', 0) + 1
    sections.sort(key=lambda s: (s['start_order'], LEVEL_RANK[s['level']]))
    for s in sections:
        if s['level'] == 'section':
            g = by_key.get((s['division'], 'group', s['number'].rsplit('-', 1)[0]))
            c = by_key.get((s['division'], 'chapter', 'ch' + s['number'].split('-')[0]))
            s['parent_section_id'] = (g or c or {}).get('section_id')
        elif s['level'] == 'group':
            c = by_key.get((s['division'], 'chapter', 'ch' + s['number'].split('-')[0]))
            s['parent_section_id'] = (c or {}).get('section_id')
    order_page = sorted((o, x['page']) for o, _, x in items)
    opos = [o for o, _ in order_page]
    for i, s in enumerate(sections):
        rank = LEVEL_RANK[s['level']]
        nxt = next((t['start_order'] for t in sections[i + 1:]
                    if t['division'] == s['division'] and LEVEL_RANK[t['level']] <= rank
                    and t['start_order'] > s['start_order']), seg_end[s['division']])
        s['end_order'] = nxt
        j = bisect.bisect_left(opos, nxt) - 1
        s['last_page'] = max(s['first_page'], order_page[j][1])
    return sections, stats


def assign_sections(objs_with_order, sections):
    """문서 순서로 가장 안쪽 절을 찾는다(절 범위 [start, end))."""
    deepest = sorted(sections, key=lambda s: (s['start_order'], LEVEL_RANK[s['level']]))
    out = {}
    for oid, o, div in objs_with_order:
        best = None
        for s in deepest:
            if s['start_order'] > o:
                break
            if s['division'] == div and o < s['end_order'] and (best is None or LEVEL_RANK[s['level']] >= LEVEL_RANK[best['level']]):
                best = s
        out[oid] = best['section_id'] if best else None
    return out


# ---------------- 목차 ----------------
TOC_ENTRY_RE = re.compile(r'(제\s*\d{1,2}\s*장|\d{1,2}-\d{1,2}(?:-\d{1,2})?)\s*(\S.*?)\s*[·…]{3,}\s*(\d{1,4})')
TOC_CHAPTER_RE = re.compile(r'^(제\s*\d{1,2}\s*장)[_\s]*(\S.*?)\s+(\d{1,4})$', re.M)   # 목차의 장 줄은 점선이 없다


def parse_toc(store, region, toc_div):
    out = []
    srcs = [(h['heading_id'], h) for h in store['headings']] + [(n['note_id'], n) for n in store['notes']]
    for nid, x in srcs:
        if region[x['page']] != 'front':
            continue
        for k, m in enumerate(list(TOC_ENTRY_RE.finditer(x['text'])) or list(TOC_CHAPTER_RE.finditer(x['text']))):
            num = m.group(1)
            num = 'ch' + re.sub(r'\D', '', num) if num.startswith('제') else num
            out.append({'toc_id': f'{nid}#{k}', 'node_id': nid, 'division': toc_div.get(x['page']), 'number': num,
                        'title': m.group(2).strip(), 'printed_page': int(m.group(3)),
                        'matched_section_id': None, 'match_status': None})
    return out


def match_toc(toc, sections):
    by = {(s['division'], s['number']): s for s in sections}
    for t in toc:
        sec = by.get((t['division'], t['number']))
        t['matched_section_id'] = sec['section_id'] if sec else None
        t['match_status'] = ('no_body_section' if sec is None else
                             'matched' if norm(clean_title(t['title'])) == norm(sec['title']) else 'title_differs')
    return toc


# ---------------- 참조 연결 ----------------
MARKER_RE = re.compile(r'^\s*(?:\d{1,2}\s*\.|[가-하]\s*\.|\(\d{1,2}\)|[①-⑳㉮-㉳]|[-◦ㅇ○※])\s*')


def starts(text, want):
    """노드 글이 찾는 항목 글로 시작하는가. 항목 표지('2.', '가.')는 있어도 없어도 같게 본다."""
    t = norm(text)
    bare = norm(MARKER_RE.sub('', text or '', count=1))
    want_bare = norm(MARKER_RE.sub('', want, count=1)) or want
    # 참조가 항목 제목 끝에 한두 글자를 더 붙인 경우('… 다짐기준수립 품' ← 항목 '… 다짐기준수립')
    near = len(t) >= 6 and want.startswith(t) and len(want) - len(t) <= 2
    return t.startswith(want) or bare.startswith(want_bare) or near


class Resolver:
    def __init__(self, sections, nodes, node_section):
        self.sections = sections
        self.by_number = {}
        for s in sections:
            self.by_number.setdefault(s['number'], []).append(s)
        self.node_section = node_section
        self.text_nodes = sorted([n for n in nodes if n['kind'] in ('heading', 'note') and n['region'] == 'body'
                                  and n['doc_order'] is not None],
                                 key=lambda n: n['doc_order'])
        self.orders = [n['doc_order'] for n in self.text_nodes]
        self.sec_by_id = {s['section_id']: s for s in sections}

    def nodes_in(self, sec):
        i, j = bisect.bisect_left(self.orders, sec['start_order']), bisect.bisect_left(self.orders, sec['end_order'])
        return self.text_nodes[i:j]

    def find_subitem(self, sec, sub, exclude=None):
        """절 범위 안에서 하위 항목 글로 시작하는 제목·본문 노드. 마지막 구성요소로 찾고 첫 구성요소로 좁힌다."""
        parts = [p.strip() for p in re.split(r'\s*/\s*', sub.strip().lstrip('/')) if p.strip()]
        if not parts:
            return [], parts
        last = norm(parts[-1])
        if len(last) <= 2:               # '5.'처럼 표지만 있으면 글자로 찾지 않는다
            return [], parts
        cands = [n for n in self.nodes_in(sec) if n['node_id'] != exclude and starts(n['text'], last)]
        if len(cands) > 1 and len(parts) > 1:
            first = norm(parts[0])
            anchors = [n for n in self.nodes_in(sec) if starts(n['text'], first)]
            if anchors:
                cands = [n for n in cands if n['doc_order'] > anchors[0]['doc_order']]
        return cands, parts

    @staticmethod
    def split_title(tail, title):
        """참조 꼬리글이 절 제목으로 시작하면 (True, 남은 원문). 제목 없이 하위 항목이면 (None, 꼬리글)."""
        t = norm(title)
        tail = re.sub(r'^\s*의\s+', '', tail)        # '9-2-3의 2급 수준측량'
        if not tail.strip():
            return 'absent', ''
        if norm(tail).startswith(t) and t:
            return 'match', tail[align_prefix(tail, t):].strip()
        if SUBMARK_RE.match(tail):
            return 'subitem_only', tail.strip()
        if len(norm(tail)) >= 4 and t.startswith(norm(tail)):
            return 'prefix', ''                       # 절 제목의 앞부분만 적음('덕트제작' ← '덕트제작(Air, Gas)')
        return 'mismatch', tail.strip()

    def one(self, part, number, tail, source_div):
        level = 'section' if number.count('-') == 2 else 'group'
        all_c = [s for s in self.by_number.get(number, []) if s['level'] == level]
        scope = [s for s in all_c if s['division'] == part] if part else all_c
        rows, notes = [], []
        for s in scope:
            rel, rest = self.split_title(tail, s['title'])
            rows.append((s, rel, rest))
        good = [r for r in rows if r[1] in ('match', 'subitem_only')] or [r for r in rows if r[1] == 'absent']
        # 제목이 다른 번호의 절과 맞는지(번호 오기 가능성). 출발·대상 부문 안에서만 본다
        alt = []
        if tail.strip() and not good:
            for s in self.sections:
                if (s['level'] == level and s['division'] == (part or source_div) and s['number'] != number
                        and self.split_title(tail, s['title'])[0] == 'match'):
                    alt.append(s)
            prefix = [r for r in rows if r[1] == 'prefix']
            if prefix and not alt:
                good = prefix
                notes.append('참조 제목이 절 제목의 앞부분과 같음(나머지 생략)')
            elif prefix:
                rows = prefix
        if part and not scope:
            other = [s['section_id'] for s in all_c]
            return {'status': 'missing', 'reason': f'{part}에 본문 절 {number}이 없음', 'targets': [],
                    'candidates': [(s, '제목은 맞지만 번호가 다름') for s in alt],
                    'notes': ([f'다른 부문의 같은 번호(연결하지 않음): {other}'] if other else [])}
        if not good:
            cands = ([(s, '번호 일치, 제목 앞부분만 일치' if rel == 'prefix' else '번호 일치, 제목 불일치') for s, rel, _ in rows]
                     + [(s, '제목 일치, 번호 불일치') for s in alt])
            if not cands:
                return {'status': 'missing', 'reason': f'본문 절 {number}을 찾지 못함', 'targets': [], 'candidates': [], 'notes': []}
            return {'status': 'ambiguous', 'reason': '번호와 제목이 같은 본문 절을 가리키지 않음', 'targets': [],
                    'candidates': cands, 'notes': notes}
        if len(good) > 1:
            return {'status': 'ambiguous', 'reason': f'번호·제목이 맞는 본문 절이 {len(good)}개(부문 생략)', 'targets': [],
                    'candidates': [(s, '번호·제목 일치') for s, _, _ in good],
                    'notes': [f"출발 부문({source_div})과 같은 후보: {[s['section_id'] for s, _, _ in good if s['division'] == source_div]}"]}
        s, rel, rest = good[0]
        basis = ('부문 명시' if part else
                 f"부문 생략: 번호·제목이 맞는 본문 절이 하나뿐({'출발과 같은 부문' if s['division'] == source_div else '출발과 다른 부문'})")
        if rel == 'absent' and not part and len(all_c) > 1:
            return {'status': 'ambiguous', 'reason': '부문과 제목이 없고 같은 번호가 여러 부문에 있음', 'targets': [],
                    'candidates': [(c, '번호 일치') for c in all_c], 'notes': []}
        if rest:
            found, parts = self.find_subitem(s, rest)
            if len(found) == 1:
                return {'status': 'resolved', 'reason': f'{basis}; 절과 하위 항목을 원문 노드로 확인', 'targets': [(s, found[0]['node_id'])],
                        'candidates': [], 'notes': notes, 'subitem': rest}
            why = '하위 항목 노드를 찾지 못함' if not found else f'하위 항목 후보가 {len(found)}개'
            return {'status': 'partial', 'reason': f'{basis}; 절은 확인, {why}', 'targets': [(s, None)],
                    'candidates': [(s, f"하위 항목 후보 {n['node_id']}") for n in found[:5]], 'notes': notes, 'subitem': rest}
        how = {'match': '번호·제목 일치', 'prefix': '번호 일치, 제목은 절 제목의 앞부분', 'absent': '번호 일치(제목 없음)',
               'subitem_only': '번호 일치'}[rel]
        return {'status': 'resolved', 'reason': f"{basis}; {how}", 'targets': [(s, None)], 'candidates': [], 'notes': notes}

    def resolve(self, part, expression, source_node_id, source_div):
        if part and part.endswith('부분') and part[:-2] + '부문' in DIVISIONS:
            r = self.resolve(part[:-2] + '부문', expression, source_node_id, source_div)
            r['reason'] = f"원문 표기 '{part}'를 '{part[:-2]}부문'으로 읽음; " + r['reason']
            return r
        if part and part not in DIVISIONS:
            return {'status': 'external', 'reason': f'이 문서에 없는 부문 표기({part})', 'targets': [], 'candidates': [], 'parts': []}
        nums = list(NUM_RE.finditer(expression))
        if not nums:
            return self.title_only(expression, source_node_id, source_div)
        parts = []
        for i, m in enumerate(nums):
            end = nums[i + 1].start() if i + 1 < len(nums) else len(expression)
            tail = expression[m.end():end]
            sep = expression[end - 1] if i + 1 < len(nums) else ''
            tail = re.sub(r'(?:[\s,~/]|및|와|과|또는)+$', '', tail) if i + 1 < len(nums) else tail
            r = self.one(part, m.group(1), tail, source_div)
            r.update(number=m.group(1), tail=tail.strip(), joiner=('~' if '~' in expression[m.end():end] else sep))
            parts.append(r)
        out = {'parts': parts, 'targets': [t for p in parts for t in p['targets']],
               'candidates': [c for p in parts for c in p['candidates']]}
        sts = [p['status'] for p in parts]
        if len(parts) == 1:
            out.update(status=sts[0], reason=parts[0]['reason'])
        elif all(s == 'resolved' for s in sts):
            out.update(status='resolved', reason='여러 대상 모두 확인: ' + ' / '.join(p['reason'] for p in parts))
        elif any(s in ('resolved', 'partial') for s in sts):
            out.update(status='partial', reason='여러 대상 중 일부만 확인: ' + ' / '.join(f"{p['number']} {p['status']}" for p in parts))
        else:
            out.update(status='ambiguous' if 'ambiguous' in sts else 'missing', reason=' / '.join(p['reason'] for p in parts))
        # 범위(~): 두 끝이 같은 부문에서 확인되면 그 사이 절도 대상으로 둔다
        if (len(parts) == 2 and parts[0]['joiner'] == '~' and out['status'] == 'resolved'
                and parts[0]['targets'][0][0]['division'] == parts[1]['targets'][0][0]['division']):
            a, b = parts[0]['targets'][0][0], parts[1]['targets'][0][0]
            mids = [s for s in self.sections if s['division'] == a['division'] and s['level'] == 'section'
                    and a['start_order'] < s['start_order'] < b['start_order']]
            out['targets'] = [(a, None)] + [(s, None) for s in mids] + [(b, None)]
            out['reason'] += f'; 범위 표기(~): 두 끝 사이 절 {len(mids)}개 포함'
        return out

    def title_only(self, title, source_node_id, source_div):
        sec_id = self.node_section.get(source_node_id)
        sec = self.sec_by_id.get(sec_id)
        if sec is None:
            return {'status': 'missing', 'reason': '번호 없는 항목 제목이고 출발 문장의 절을 정하지 못함', 'targets': [], 'candidates': [], 'parts': []}
        found, _ = self.find_subitem(sec, title, exclude=source_node_id)
        if len(found) == 1:
            return {'status': 'resolved', 'reason': f"번호 없는 항목 제목: 출발 문장과 같은 절({sec['number']}) 안에 같은 글로 시작하는 항목이 하나뿐",
                    'targets': [(sec, found[0]['node_id'])], 'candidates': [], 'parts': [], 'subitem': title}
        if len(found) > 1:
            return {'status': 'ambiguous', 'reason': f'같은 절 안에 같은 항목 후보가 {len(found)}개', 'targets': [],
                    'candidates': [(sec, f"하위 항목 후보 {n['node_id']}") for n in found], 'parts': [], 'subitem': title}
        mk = re.match(r'^\s*(\d{1,2})\s*\.', title)
        same_no = [n for n in self.nodes_in(sec) if mk and n['kind'] == 'heading'
                   and re.match(r'^\s*' + mk.group(1) + r'\s*\.', n['text'])] if mk else []
        if same_no:
            return {'status': 'ambiguous', 'reason': f"출발 절({sec['number']}) 안에 같은 항목 번호 '{mk.group(1)}.'가 있으나 제목 글자가 다름(선택하지 않음)",
                    'targets': [], 'candidates': [(sec, f"같은 번호 항목 {n['node_id']}: {n['text'][:40]}") for n in same_no],
                    'parts': [], 'subitem': title}
        others = [s for s in self.sections if s['division'] == source_div and s['level'] == 'section'
                  and s['section_id'] != sec['section_id'] and self.find_subitem(s, title, exclude=source_node_id)[0]][:10]
        return {'status': 'ambiguous' if others else 'missing',
                'reason': ('출발 절 안에서 찾지 못함; 같은 부문 다른 절에 같은 항목이 있음(선택하지 않음)' if others
                           else '출발 절과 같은 부문에서 같은 항목을 찾지 못함'),
                'targets': [], 'candidates': [(s, '같은 부문 다른 절의 같은 항목') for s in others], 'parts': [], 'subitem': title}


def expression_of(target):
    num, title = target.get('number'), target.get('title') or ''
    title = title.replace('\n', ' ')
    return f"{num} {title}".strip() if num else title


SCAN_PATTERNS = [
    ('bracket_part', re.compile(r"\[(?P<part>[가-힣]{1,8}부[문분])\]\s*(?P<expr>\d{1,2}-\d{1,2}(?:-\d{1,2})?[^’'”\"\n]{0,60})")),
    ('quoted_number', re.compile(r"[‘'“\"]\s*(?P<expr>\d{1,2}-\d{1,2}(?:-\d{1,2})?\s*[^’'”\"\n]{1,60})[’'”\"]")),
    ('unquoted_number', re.compile(r"(?<![‘'“\"\d\-\]\s])\s(?P<expr>\d{1,2}-\d{1,2}-\d{1,2}\s+[가-힣A-Za-z][^‘’“”'\"\n.]{0,40}?)(?=(?:을|를|의|에)\s)")),
    ('other_part_word', re.compile(r'(?P<part>(?:전기|통신|소방|문화재|정보통신)\s*부문)(?P<expr>[^.\n]{0,40})')),
]


def build_edges(data, nodes, sections, node_section, region, division):
    node_by = {n['node_id']: n for n in nodes}
    R = Resolver(sections, nodes, node_section)
    edges, ledger = [], []

    def rows_for(r):
        tg = [{'role': 'target', 'section_id': s['section_id'], 'subitem_node_id': sub, 'reason': '확인한 대상'}
              for s, sub in r['targets']]
        cd = [{'role': 'candidate', 'section_id': s['section_id'], 'subitem_node_id': None, 'reason': why}
              for s, why in r['candidates']]
        seen, out = set(), []
        for x in tg + cd:
            k = (x['role'], x['section_id'], x['subitem_node_id'])
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out

    for rel in data['links']['relations']:
        if rel['type'] != 'reference':
            continue
        src = node_by[rel['from']]
        expr = expression_of(rel['target'])
        r = R.resolve(rel['target']['part'], expr, src['node_id'], src['division'])
        e = {'edge_id': rel['relation_id'], 'origin': 'existing_reference', 'relation_id': rel['relation_id'],
             'from_node_id': src['node_id'], 'expression': expr, 'sentence': rel['sentence'],
             'condition_text': rel['condition_text'], 'target_division': rel['target']['part'],
             'target_number': rel['target']['number'], 'target_subitem': r.get('subitem'),
             'target_status': r['status'], 'reason': r['reason'],
             'method': 'number_title_match' if rel['target']['number'] else 'same_section_title',
             'source_confirmed': rel['confirmed'], 'source_status': rel['status'],
             'evidence': {'source_page': src['page'], 'source_bbox': src['bbox'], 'source_division': src['division'],
                          'source_section_id': node_section.get(src['node_id']), 'cost_effect': rel.get('cost_effect'),
                          'raw_target': rel['target'], 'applicability': '질문별 판단(이 저장소에 저장하지 않음)',
                          'parts': [{k: p[k] for k in ('number', 'tail', 'status', 'reason')} for p in r.get('parts', [])],
                          'notes': [n for p in r.get('parts', []) for n in p.get('notes', [])] + r.get('notes', [])},
             'candidates': rows_for(r)}
        edges.append(e)
    # 기존 목록 밖 후보: 일반 패턴 점검(읽기 전용). 기존 참조가 있는 노드의 같은 번호는 제외
    covered = {}
    for e in edges:
        covered.setdefault(e['from_node_id'], set()).update(NUM_RE.findall(e['expression']) or [norm(e['expression'])])
    scan = []
    for n in nodes:
        if n['region'] != 'body' or n['kind'] not in ('note', 'basis', 'cell', 'heading') or not n['text']:
            continue
        for pname, rx in SCAN_PATTERNS:
            for m in rx.finditer(n['text']):
                expr = m.group('expr').strip()
                nums = NUM_RE.findall(expr)
                if pname != 'other_part_word' and nums and set(nums) <= covered.get(n['node_id'], set()):
                    continue
                if pname == 'quoted_number' and '[' in n['text'][max(0, m.start() - 12):m.start() + 2]:
                    continue        # 앞에 부문 괄호가 있으면 bracket_part가 잡는다
                part = m.groupdict().get('part')
                part = re.sub(r'\s+', '', part) if part else None
                if pname == 'other_part_word':
                    r = {'status': 'external', 'reason': f'이 문서에 없는 부문 언급({part})', 'targets': [], 'candidates': [], 'parts': []}
                else:
                    r = R.resolve(part, expr, n['node_id'], n['division'])
                key = (n['node_id'], m.start(), pname)
                scan.append({'edge_id': f"scan:{n['node_id']}@{m.start()}:{pname}", 'origin': 'scan_candidate',
                             'relation_id': None, 'from_node_id': n['node_id'], 'expression': m.group(0).strip(),
                             'sentence': n['text'], 'condition_text': None, 'target_division': part,
                             'target_number': nums[0] if nums else None, 'target_subitem': r.get('subitem'),
                             'target_status': r['status'], 'reason': r['reason'], 'method': f'scan:{pname}',
                             'source_confirmed': None, 'source_status': '새 후보(기존 파싱 관계 없음)',
                             'evidence': {'source_page': n['page'], 'source_kind': n['kind'], 'source_division': n['division'],
                                          'pattern': pname, 'span': [m.start(), m.end()]},
                             'candidates': rows_for(r)})
    return edges, scan


# ---------------- 관계 원본 ----------------
def build_relations(data, node_ids):
    out, stats = [], {}

    def norm_end(v):
        if v is None:
            return None, 'null'
        if v in node_ids:
            return v, 'node'
        if ':rows[' in v or ':rows' in v:
            return None, 'row_selector_raw'
        return None, 'title_string_raw'

    for r in data['links']['relations']:
        fn, fs = norm_end(r['from'])
        tn, ts = norm_end(r['to'])
        stats.setdefault(r['type'], {}).setdefault(f'{fs}->{ts}', 0)
        stats[r['type']][f'{fs}->{ts}'] += 1
        out.append({'relation_id': r['relation_id'], 'type': r['type'], 'from_raw': r['from'], 'to_raw': r['to'],
                    'from_node_id': fn, 'to_node_id': tn, 'from_norm': fs, 'to_norm': ts,
                    'confirmed': bool(r['confirmed']), 'status': r['status'], 'raw': r})
    return out, stats


def build():
    data, manifest = read_inputs()
    store = data['store']
    region, division, toc_div, covers, page_ev = page_regions(store, data['page_map'])
    nodes = build_nodes(store, region, division)
    node_ids = {n['node_id'] for n in nodes}
    toc = parse_toc(store, region, toc_div)
    toc_by_key = {}
    for t in toc:
        toc_by_key.setdefault((t['division'], t['number']), t)
    ordered = [(n['node_id'], n['doc_order'], n['division']) for n in nodes if n['doc_order'] is not None and n['region'] == 'body']
    # 원문 대조 교정: 교정 전 소속을 먼저 구해 교정 자료의 기대값과 맞춰 본 뒤 적용한다
    base_sections, _ = build_sections(store, region, division, data['page_map'], toc_by_key)
    before = assign_sections(ordered, base_sections)
    node_order = {nid: o for nid, o, _ in ordered}
    fixes = []
    for corr in corrections.load():
        corrections.check(corr, manifest, PDF, store, node_order, before, toc_by_key)
        fixes += corr['sections']
    sections, sec_stats = build_sections(store, region, division, data['page_map'], toc_by_key, extra=fixes)
    toc = match_toc(toc, sections)
    node_section = assign_sections(ordered, sections)
    sec_by_id = {s['section_id']: s for s in sections}
    for c in fixes:
        sid = f"{DOCUMENT_ID}:{DIV_CODE[c['division']]}:{c['number']}"
        for n in corrections.correction_nodes(c, store['page_height'][str(c['page'])], region[c['page']], division[c['page']]):
            nodes.append(n)
            node_section[n['node_id']] = sid
    node_ids = {n['node_id'] for n in nodes}
    records = []
    for rec, link in zip(data['records'], data['links']['record_links']):
        if rec['record_uid'] != link['record_uid']:
            raise ValueError('레코드와 연결 정보 순서 불일치')
        records.append({'record_uid': rec['record_uid'], 'record_idx': link['record_idx'], 'kind': rec['kind'],
                        'page': rec['page'], 'text': rec['text'], 'source_node_id': link['source_id'],
                        'section_id': node_section.get(link['source_id']), 'record': rec, 'link': link,
                        'cell_ids': list(dict.fromkeys(link.get('cell_ids') or []))})
    search = search_records(records, fixes, before, node_section, sec_by_id)
    # 원본 관계 중 교정 소속과 맞지 않는 것: 원본은 그대로 보존하고, 교정 자료에 근거와 함께 기록만 한다
    why = {'note_table_of': '원문상 이 표는 새 절의 본표다. 앞 절 표의 주석 표로 보지 않는다',
           'note_of_section': '원본 관계는 앞 절 제목을 가리킨다. 원문상 새 절 표 아래 [주]다',
           'note_of_unknown': '원본은 소속 미확정. 원문상 새 절 표 아래 [주] ①이다'}
    for c in fixes:
        m = set(c['members'])
        c['superseded_relations'] = [
            {'relation_id': r['relation_id'], 'type': r['type'], 'from': r['from'], 'to': r['to'], 'original_status': r['status'],
             'confirmed': r['confirmed'], 'note': why.get(r['type'], '교정 소속과 비교 필요')}
            for r in data['links']['relations'] if r['from'] in m or r['to'] in m]
    relations, rel_stats = build_relations(data, node_ids)
    edges, scan = build_edges(data, nodes, sections, node_section, region, division)
    doc = {'document_id': DOCUMENT_ID, 'title': '2026 건설공사 표준품셈(정오표 1차 반영)', 'year': 2026,
           'version_label': '원문_정오표1차_반영', 'pdf_path': manifest['files']['pdf']['path'],
           'pdf_sha256': manifest['files']['pdf']['sha256'], 'raw_sha256': data['generation']['raw_sha256'],
           'generation_id': data['generation']['id'], 'pages': manifest['counts']['pages']}
    return {'manifest': manifest, 'document': doc, 'nodes': nodes, 'sections': sections, 'section_stats': sec_stats,
            'toc': toc, 'records': records, 'relations': relations, 'relation_stats': rel_stats,
            'edges': edges, 'scan': scan, 'covers': covers, 'page_evidence': page_ev,
            'search_records': search, 'corrections': fixes, 'membership_before': before}


def search_records(records, fixes, before, node_section, sec_by_id):
    """다음 청킹이 읽을 검색 입력. 원본 레코드 글은 그대로 두고, 교정으로 소속이 바뀐 레코드만 글 앞의 절 제목을 바꾼다.
    교정으로 추가한 기준 줄((일당))은 원본 기준 레코드와 같은 모양으로 그 절의 첫 항목 앞에 넣는다."""
    member = {nid: c for c in fixes for nid in c['members']}
    first = {c['members'][0]: c for c in fixes}
    out, inserted = [], set()
    for r in records:
        nid = r['source_node_id']
        base = {'record_uid': r['record_uid'], 'record_idx': r['record_idx'], 'kind': r['kind'], 'page': r['page'],
                'source_node_id': nid, 'section_id': r['section_id'], 'origin': 'original', 'correction_id': None,
                'section_text': r['record']['section'], 'text': r['text']}
        if nid in first and nid not in inserted:
            c = first[nid]
            inserted.add(nid)
            out.append({**base, 'record_uid': None, 'record_idx': None, 'kind': 'text', 'origin': 'added_from_pdf',
                        'source_node_id': f"corr:{c['correction_id']}:basis", 'correction_id': c['correction_id'],
                        'section_id': node_section[f"corr:{c['correction_id']}:basis"], 'section_text': c['title_raw'],
                        'text': f"{c['title_raw']} | 설명 | {c['basis_pdf']['text']}"})
        if nid in member:
            c = member[nid]
            old = c['expected_previous_section_text']
            if r['record']['section'] != old or not r['text'].startswith(old + ' | '):
                raise ValueError(f'검색용 글의 기존 절 제목이 교정 자료와 다름: {r["record_uid"]}')
            if sec_by_id[node_section[nid]]['title_raw'] != c['title_raw']:
                raise ValueError(f'교정 소속 불일치: {nid}')
            base.update(origin='section_corrected', correction_id=c['correction_id'], section_text=c['title_raw'],
                        text=c['title_raw'] + r['text'][len(old):], previous_section_text=old,
                        previous_section_id=before.get(nid))
        out.append(base)
    for i, x in enumerate(out):
        x['search_idx'] = i
        x['search_uid'] = x['record_uid'] or f"{x['source_node_id']}#0"
    return out
