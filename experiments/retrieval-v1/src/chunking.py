"""구조를 보존하는 청킹(2단계). 입력은 로컬 DB의 원문 릴리스(search_records와 원문 구조·관계).

  python -B experiments/retrieval-v1/src/chunking.py migrate
  python -B experiments/retrieval-v1/src/chunking.py load [--release <id>] [--fail-after <table>]

조각 종류
  work   본문 절(공종) 하나. 절 경로·제목, 원문 소제목, 원문 적용 범위 문장(scope_quote)
  rule   설명. 같은 절·같은 소제목·같은 소속(같은 표의 주석 / 절 전체 / 소속 미확정)의 이어지는 글. 길면 레코드 경계로 나눔
  table  표 하나(작은 표 전체). 크면 원문 행 묶음(table_group) 경계로 나누고 제목·소제목·기준·머리글을 반복
규칙
  - 글을 자르지 않는다. 한 행 묶음·한 레코드가 상한을 넘으면 그대로 두고 oversize로 표시한다.
  - 원문 글(body_text)과 검색용 문맥(context_text)을 나눠 저장한다.
  - 길어깨 교정의 superseded_relations는 어떤 소속·부모·주석 연결에도 쓰지 않는다.
  - 위치 근거 관계는 confirmed=false 그대로 연결만 한다. 확정 적용으로 바꾸지 않는다.
"""
import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db  # noqa: E402

WORK = HERE.parent
MIGRATION = WORK / 'sql/20261012000100_rag_chunks.sql'
CODE_FILES = [HERE / 'chunking.py', MIGRATION]
DEFAULT_RELEASE = 'rk-complete-82c206c61e21-37f81b5cfb1b'
CONFIG = {'rule_version': 'chunk-v1', 'rule_target_est_tokens': 800, 'table_target_est_tokens': 1600,
          'safety_cap_est_tokens': 6000, 'overlap': 0,
          'token_method': 'estimate: ceil(글자 수 / 1.5). 외부 API 없음. 실제 모델 토큰 수 아님',
          'cap_note': '6,000은 추정 토큰 기준의 안전 상한(실제 모델 한도 확인은 임베딩 단계)'}
PUA = re.compile('[-]')
SCOPE_RE = re.compile(r'본\s*품은')


def est(text):
    return math.ceil(len(text) / 1.5)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def label(sec):
    """절 표시: 번호 + 정리한 제목(개정 표기·붙은 본문 제외). 장은 원문 제목 줄."""
    return sec['title_raw'] if sec['level'] == 'chapter' else f"{sec['number']} {sec['title']}"


def body_of(x):
    """검색 입력 글에서 앞의 절 제목을 뗀 원문 부분. 설명 레코드는 '설명 | '도 뗀다."""
    t = x['text']
    pre = x['section_text'] + ' | '
    t = t[len(pre):] if t.startswith(pre) else t
    return t[len('설명 | '):] if x['kind'] == 'text' and t.startswith('설명 | ') else t


# ---------------- 입력 ----------------
def read_input(c, rid):
    q = lambda sql, *a: c.execute(sql, a).fetchall()
    st = q('select status from rag_knowledge.releases where release_id=%s', rid)
    if not st or st[0][0] != 'complete':
        raise SystemExit(f'원문 릴리스가 complete가 아님: {rid} {st}')
    cols = ['search_uid', 'search_idx', 'origin', 'record_uid', 'correction_id', 'kind', 'page', 'source_node_id',
            'section_id', 'section_text', 'text']
    search = [dict(zip(cols, r)) for r in q(f"select {','.join(cols)} from rag_knowledge.search_records where release_id=%s order by search_idx", rid)]
    recs = {r[0]: {'record': r[1], 'link': r[2]} for r in q('select record_uid, record, link from rag_knowledge.source_records where release_id=%s', rid)}
    ncols = ['node_id', 'kind', 'page', 'doc_order', 'region', 'division', 'text', 'parent_node_id', 'structure']
    nodes = {r[0]: dict(zip(ncols, r)) for r in q(f"select {','.join(ncols)} from rag_knowledge.nodes where release_id=%s and kind<>'cell'", rid)}
    cell_parent = dict(q("select node_id, parent_node_id from rag_knowledge.nodes where release_id=%s and kind='cell'", rid))
    rec_cells = defaultdict(list)
    for u, cell in q('select record_uid, cell_node_id from rag_knowledge.record_cells where release_id=%s order by 1, 2', rid):
        rec_cells[u].append(cell)
    scols = ['section_id', 'division', 'level', 'number', 'title', 'title_raw', 'heading_node_id', 'parent_section_id',
             'start_order', 'first_page', 'status']
    sections = {r[0]: dict(zip(scols, r)) for r in q(f"select {','.join(scols)} from rag_knowledge.sections where release_id=%s", rid)}
    rels = [dict(zip(['relation_id', 'type', 'from_raw', 'to_raw', 'confirmed', 'status'], r)) for r in
            q('select relation_id, type, from_raw, to_raw, confirmed, status from rag_knowledge.source_relations where release_id=%s', rid)]
    edges = [dict(zip(['edge_id', 'origin', 'from_node_id', 'target_status'], r)) for r in
             q('select edge_id, origin, from_node_id, target_status from rag_knowledge.edges where release_id=%s', rid)]
    corrections = [r[0] for r in q('select data from rag_knowledge.corrections where release_id=%s order by correction_id', rid)]
    # 입력 해시: DB 검색 입력 전체(순서 포함)
    h = hashlib.sha256()
    for x in search:
        h.update(json.dumps([x[k] for k in cols], ensure_ascii=False).encode())
    return {'release_id': rid, 'search': search, 'recs': recs, 'nodes': nodes, 'cell_parent': cell_parent,
            'rec_cells': rec_cells, 'sections': sections, 'rels': rels, 'edges': edges, 'corrections': corrections,
            'input_sha256': h.hexdigest(), 'search_cols': cols}


# ---------------- 청킹 ----------------
class Builder:
    def __init__(self, d):
        self.d = d
        self.chunks, self.sources, self.cells, self.links, self.excl = [], [], [], [], []
        self.usage = defaultdict(list)
        n = d['nodes']
        self.superseded = {r['relation_id'] for c in d['corrections'] for r in c.get('superseded_relations', [])}
        rels = [r for r in d['rels'] if r['relation_id'] not in self.superseded]
        self.used_relations = len(rels)
        self.basis_of = defaultdict(list)      # 표 -> [(기준 노드, 관계)]
        self.note_owner, self.note_table_of, self.nested, self.continues, self.child = {}, {}, {}, defaultdict(list), {}
        for r in rels:
            t, f, to = r['type'], r['from_raw'], r['to_raw']
            if t == 'basis_of' and to:
                self.basis_of[to].append((f, r))
            elif t == 'note_of_table':
                self.note_owner[f] = (to, r)
            elif t == 'note_table_of' and to:
                self.note_table_of[f] = (to, r)
            elif t == 'nested_table_in_cell':
                self.nested[f] = (to, r)
            elif t == 'table_continues':
                self.continues[f].append((to, r))
            elif t == 'child_of_item':
                self.child[f] = to
        # 원문 대조 교정: 교정 절의 표 아래 [주]는 그 표의 설명(위치 근거), 보완한 (일당)은 그 표의 기준
        self.corr_note = {}
        for c in d['corrections']:
            table = next(m for m in c['members'] if n[m]['kind'] == 'table')
            for m in c['members']:
                if m != table:
                    self.corr_note[m] = (table, c['correction_id'])
            self.basis_of[table].append((f"corr:{c['correction_id']}:basis", None))
        self.attached_basis = {b for v in self.basis_of.values() for b, _ in v}
        self.search_by_node = defaultdict(list)
        for x in d['search']:
            self.search_by_node[x['source_node_id']].append(x)
        # 절 제목 노드에 제목 뒤 원문이 붙은 경우('7-4-7 매립설계수량 매립 설계수량에는 …'). 레코드가 없으므로 따로 전달한다
        self.heading_extra = {}
        for sid, s in d['sections'].items():
            h = n.get(s['heading_node_id'])
            if not h or h['kind'] != 'heading' or not h['text']:
                continue
            i = h['text'].find(s['title'])
            rest = h['text'][i + len(s['title']):].strip() if i >= 0 else ''
            core = re.sub(r"\([^()]*\d{2}\s*년[^()]*\)|\((?:단위\s*:)?[^()]*당\)", '', rest).strip()
            if core and not re.match(r'^\d{1,2}-\d{1,2}', core):   # 붙은 다음 절 제목은 그 절이 따로 있다
                self.heading_extra[sid] = rest
        self.groups = defaultdict(list)       # 표 -> [(행 집합, 묶음 노드)]
        for nid, x in n.items():
            if x['kind'] == 'table_group':
                self.groups[x['parent_node_id']].append((set(x['structure'].get('rows') or []), nid))

    # --- 공통 ---
    def add_chunk(self, cid, kind, sec_id, context, body, parts, srcs, status, issues, title, pages, extra_links=()):
        text = context + '\n' + body if body else context
        e = est(text)
        if e > CONFIG['safety_cap_est_tokens']:
            status, issues = 'oversize', issues + [f'oversize: 추정 {e}토큰이 안전 상한을 넘음(자르지 않고 보존)']
        sec = self.d['sections'].get(sec_id)
        self.chunks.append({'chunk_id': cid, 'kind': kind, 'section_id': sec_id, 'division': sec['division'] if sec else None,
                            'title': title, 'page_first': min(pages) if pages else None, 'page_last': max(pages) if pages else None,
                            'part_index': parts[0], 'part_count': parts[1], 'context_text': context, 'body_text': body,
                            'text': text, 'est_tokens': e, 'token_method': CONFIG['token_method'], 'status': status,
                            'issues': issues, '_first_idx': min((s['search_idx'] for s, _ in srcs), default=None)})
        for k, (x, role) in enumerate(srcs):
            self.sources.append({'chunk_id': cid, 'ord': k, 'search_uid': x['search_uid'], 'role': role})
            self.usage[x['search_uid']].append({'chunk_id': cid, 'role': role})
        if sec_id:
            self.link(cid, 'in_section', section=sec_id, confirmed=True,
                      status='원문 대조 교정 절' if sec and sec['status'] == 'pdf_correction' else '본문 순서상 절 범위')
        for l in extra_links:
            self.link(cid, **l)

    def link(self, cid, link_type, chunk=None, node=None, section=None, edge=None, confirmed=False, status='', relation=None):
        self.links.append({'chunk_id': cid, 'link_type': link_type, 'target_chunk_id': chunk, 'target_node_id': node,
                           'target_section_id': section, 'target_edge_id': edge, 'confirmed': confirmed, 'status': status,
                           'relation_id': relation})

    def head(self, tag, sec_id):
        sec = self.d['sections'].get(sec_id)
        return f"[{tag}] {sec['division']} {label(sec)}" if sec else f'[{tag}]'

    # --- 표 ---
    def table_chunk(self, tid, xs, sub):
        n = self.d['nodes']
        t = n[tid]
        st = t['structure']
        sec_id = xs[0]['section_id']
        nested = tid in self.nested
        note_tbl = st.get('role') == 'note_table' and tid in self.note_table_of
        ctx = [self.head('주석 표' if note_tbl else '칸 안 표' if nested else '표', sec_id)]
        srcs_ctx, links = [], [{'link_type': 'table_node', 'node': tid, 'confirmed': True, 'status': '원문 표'}]
        if sub is not None:
            ctx.append('소제목: ' + body_of(sub['x']))
            srcs_ctx.append((sub['x'], 'context_subheading'))
            sub['ctx'] = True
        for b, r in self.basis_of.get(tid, []):
            bxs = self.search_by_node.get(b, [])
            for bx in bxs:
                ctx.append('기준: ' + body_of(bx))
                srcs_ctx.append((bx, 'context_basis'))
            if not bxs:
                # 번호 제목 끝에서 떼어 낸 기준('3. 일일시공량 (일당)')은 레코드가 없다. 기준 노드 원문을 그대로 쓴다
                ctx.append('기준: ' + n[b]['text'])
            links.append({'link_type': 'basis', 'node': b, 'confirmed': False,
                          'status': (r['status'] if r else '원문 대조 교정으로 보완한 기준(같은 절 표 바로 위)')
                          + ('' if bxs else '; 기준 노드 원문(레코드 없음)'),
                          'relation': r['relation_id'] if r else None})
        extra = self.heading_extra.get(sec_id)
        if extra:
            ctx.append('절 제목 줄의 나머지 원문: ' + extra)
        heads = [' '.join(p) for p in (st.get('col_path') or []) if p]
        if heads:
            ctx.append('머리글: ' + ' | '.join(heads))
        if nested:
            cell, r = self.nested[tid]
            links += [{'link_type': 'parent_cell', 'node': cell, 'confirmed': True, 'status': r['status'], 'relation': r['relation_id']},
                      {'link_type': 'parent_table', 'node': self.d['cell_parent'][cell], 'confirmed': True, 'status': '칸 안의 작은 표(구조)'}]
        if note_tbl:
            owner, r = self.note_table_of[tid]
            links.append({'link_type': 'note_table_of', 'node': owner, 'confirmed': False, 'status': r['status'], 'relation': r['relation_id']})
        for nxt, r in self.continues.get(tid, []):
            links.append({'link_type': 'continues_candidate', 'node': nxt, 'confirmed': False, 'status': r['status'], 'relation': r['relation_id']})
        issues, uncertain = [], 0
        for x in xs:
            s = self.d['recs'][x['record_uid']]['record'].get('structure') or {}
            if s.get('status') not in (None, 'ok'):
                uncertain += 1
                issues += [i for i in s.get('issues', []) if i not in issues]
        status = 'held' if st.get('flags') else 'uncertain' if uncertain else 'ok'
        if any(PUA.search(x['text']) for x in xs):
            issues.append('formula_unresolved: 수식 전용 글꼴 부호가 있음')
        # 행 묶음 경계로 나누기
        context = '\n'.join(ctx)
        row_group = {}
        for k, (rows, gid) in enumerate(self.groups.get(tid, [])):
            for r in rows:
                row_group[r] = k
        units, cur = [], None
        for x in xs:
            gr = (self.d['recs'][x['record_uid']]['link'].get('grid_rows') or [None])[0]
            g = row_group.get(gr, cur)
            if units and g == cur:
                units[-1].append(x)
            else:
                units.append([x])
                cur = g
        parts, acc = [], []
        for u in units:
            if acc and est(context + '\n' + '\n'.join(body_of(y) for y in acc + u)) > CONFIG['table_target_est_tokens']:
                parts.append(acc)
                acc = []
            acc = acc + u
        parts.append(acc)
        title = label(self.d['sections'][sec_id]) + ' 표'
        for k, part in enumerate(parts, 1):
            cid = f't:{tid}' + (f'#p{k}' if len(parts) > 1 else '')
            pctx = context + (f'\n(표 일부 {k}/{len(parts)}: 원문 행 묶음 경계로 나눔)' if len(parts) > 1 else '')
            body = '\n'.join(body_of(x) for x in part)
            self.add_chunk(cid, 'table', sec_id, pctx, body, (k, len(parts)), srcs_ctx + [(x, 'body') for x in part],
                           status, list(issues), title, [x['page'] for x in part], links)
            for x in part:
                lk = self.d['recs'][x['record_uid']]['link']
                for cell in self.d['rec_cells'].get(x['record_uid'], []):
                    self.cells.append({'chunk_id': cid, 'cell_node_id': cell, 'role': 'cell'})
                for cell in lk.get('shared_cell_ids') or []:
                    self.cells.append({'chunk_id': cid, 'cell_node_id': cell, 'role': 'shared_value'})

    # --- 설명 ---
    def owner_key(self, x, keys):
        nid = x['source_node_id']
        node = self.d['nodes'][nid]
        if nid in self.corr_note:
            return ('table', self.corr_note[nid][0])
        if nid in self.note_owner:
            return ('table', self.note_owner[nid][0])
        if nid in self.child and self.child[nid] in keys:
            return keys[self.child[nid]]
        scope = (node['structure'] or {}).get('scope') or {}
        if scope.get('kind') in ('orphan_tail', 'unassigned_body') or (node['kind'] == 'note' and not scope):
            return ('unknown',)
        return ('section',)

    def rule_chunks(self, group, key, sub):
        if not group:
            return
        sec_id = group[0]['section_id']
        ctx = [self.head('설명', sec_id)]
        srcs_ctx = []
        if sub is not None:
            if group[0] is sub['x']:
                sub['body'] = True             # 소제목이 이 설명의 첫 줄(원문 인용)
            else:
                ctx.append('소제목: ' + body_of(sub['x']))
                srcs_ctx.append((sub['x'], 'context_subheading'))
                sub['ctx'] = True
        context = '\n'.join(ctx)
        parts, acc = [], []
        for x in group:
            if acc and est(context + '\n' + '\n'.join(body_of(y) for y in acc + [x])) > CONFIG['rule_target_est_tokens']:
                parts.append(acc)
                acc = []
            acc.append(x)
        parts.append(acc)
        issues = []
        status = 'ok'
        if key[0] == 'unknown':
            status, issues = 'membership_unconfirmed', ['membership_unconfirmed: 소속 미확정 설명(가까운 표에 붙이지 않음)']
        if any(PUA.search(x['text']) for x in group):
            issues.append('formula_unresolved: 수식 전용 글꼴 부호가 있음')
        links = []
        if key[0] == 'table':
            tbls = {}
            for x in group:
                nid = x['source_node_id']
                if nid in self.corr_note:
                    tbls[self.corr_note[nid][0]] = ('원문 대조 교정 절의 표 아래 [주](위치 근거)', None)
                elif nid in self.note_owner:
                    r = self.note_owner[nid][1]
                    tbls.setdefault(self.note_owner[nid][0], (r['status'], r['relation_id']))
            links = [{'link_type': 'related_table', 'node': t, 'confirmed': False, 'status': s, 'relation': rid}
                     for t, (s, rid) in tbls.items()]
        first = group[0]['search_uid']
        title = label(self.d['sections'][sec_id]) + ' 설명'
        for k, part in enumerate(parts, 1):
            cid = f'r:{first}' + (f'#p{k}' if len(parts) > 1 else '')
            pctx = context + (f'\n(설명 일부 {k}/{len(parts)}: 레코드 경계로 나눔)' if len(parts) > 1 else '')
            plinks = list(links)
            if len(parts) > 1 and k > 1:
                plinks.append({'link_type': 'continues_part_of', 'chunk': f'r:{first}#p1', 'confirmed': True,
                               'status': '같은 설명 묶음을 길이 때문에 나눔'})
            self.add_chunk(cid, 'rule', sec_id, pctx, '\n'.join(body_of(x) for x in part), (k, len(parts)),
                           srcs_ctx + [(x, 'body') for x in part], status, list(issues), title, [x['page'] for x in part], plinks)

    # --- 전체 ---
    def run(self):
        d, n = self.d, self.d['nodes']
        group, gkey, keys = [], None, {}
        table, txs = None, []
        sub, cur_sec = None, None

        def flush_rule():
            nonlocal group, gkey
            self.rule_chunks(group, gkey, sub)
            group, gkey = [], None

        def flush_table():
            nonlocal table, txs
            if table:
                self.table_chunk(table, txs, sub)
            table, txs = None, []

        def close_sub():
            if sub is not None and not sub['body'] and not sub['ctx']:
                sub['body'] = True
                self.rule_chunks([sub['x']], ('section',), None)

        for x in d['search']:
            node = n[x['source_node_id']]
            if node['region'] != 'body':
                self.excl.append({'search_uid': x['search_uid'],
                                  'reason': '목차·앞부분(첫 부문 표지 앞)' if node['region'] == 'front' else '부문 표지 쪽(장 목록)'})
                continue
            if x['section_id'] != cur_sec:
                flush_table()
                flush_rule()
                close_sub()
                sub, cur_sec = None, x['section_id']
            if x['kind'] == 'table':
                tid = d['recs'][x['record_uid']]['record']['table_id']
                if tid != table:
                    flush_table()
                    flush_rule()
                    table = tid
                txs.append(x)
                continue
            flush_table()
            role = (d['recs'].get(x['record_uid']) or {}).get('link', {}).get('role') if x['record_uid'] else 'basis'
            if node['kind'] == 'basis' and x['source_node_id'] in self.attached_basis:
                continue                       # 해당 표 조각의 기준 문맥으로 쓴다
            if role == 'subheading':
                flush_rule()
                close_sub()
                sub = {'x': x, 'body': False, 'ctx': False}
                continue
            key = self.owner_key(x, keys)
            keys[x['source_node_id']] = key
            if group and key != gkey:
                flush_rule()
            if not group and sub is not None and not sub['body'] and not sub['ctx']:
                group.append(sub['x'])
            group.append(x)
            gkey = key
        flush_table()
        flush_rule()
        close_sub()
        self.work_chunks()
        self.reference_links()
        # 사용처 없는 본문 입력이 있으면 실패(설명 없는 누락 금지)
        excl = {e['search_uid'] for e in self.excl}
        missing = [x['search_uid'] for x in d['search'] if x['search_uid'] not in excl and not any(
            u['role'] in ('body', 'context_basis', 'context_subheading') for u in self.usage[x['search_uid']])]
        if missing:
            raise RuntimeError(f'사용처 없는 검색 입력 {len(missing)}개: {missing[:5]}')
        # 순서 번호: 첫 입력 순서, 공종 조각은 그 절의 첫 조각 바로 앞
        self.chunks.sort(key=lambda ch: (ch['_first_idx'] if ch['_first_idx'] is not None else 10 ** 9, ch['kind'] != 'work'))
        for i, ch in enumerate(self.chunks):
            ch['ordinal'] = i
            ch.pop('_first_idx')
        per = defaultdict(int)
        for l in self.links:
            l['link_ord'] = per[l['chunk_id']]
            per[l['chunk_id']] += 1

    def work_chunks(self):
        d = self.d
        by_sec = defaultdict(list)
        for ch in self.chunks:
            by_sec[ch['section_id']].append(ch)
        srcs_by_chunk = defaultdict(list)
        sx = {x['search_uid']: x for x in d['search']}
        for s in self.sources:
            srcs_by_chunk[s['chunk_id']].append(s)
        for sec_id, sec in sorted(d['sections'].items(), key=lambda kv: (kv[1]['start_order'], kv[1]['level'])):
            own = by_sec.get(sec_id, [])
            if sec['level'] != 'section' and not own:
                continue                      # 장·상위 묶음은 sections 표로 부모 조회만
            path, p = [], sec
            while p:
                path.insert(0, label(p))
                p = d['sections'].get(p['parent_section_id']) if p['parent_section_id'] else None
            subs, scope = [], []
            for ch in own:
                for s in srcs_by_chunk[ch['chunk_id']]:
                    x = sx[s['search_uid']]
                    lk = (d['recs'].get(x['record_uid']) or {}).get('link', {})
                    if lk.get('role') == 'subheading' and body_of(x) not in subs:
                        subs.append(body_of(x))
                    if ch['kind'] == 'rule' and s['role'] == 'body' and SCOPE_RE.search(body_of(x)) and x not in scope:
                        scope.append(x)
            n_t = sum(ch['kind'] == 'table' for ch in own)
            n_r = sum(ch['kind'] == 'rule' for ch in own)
            ctx = [f"[공종] {sec['division']} " + ' > '.join(path)]
            if subs:
                ctx.append('원문 소제목: ' + ' / '.join(subs))
            ctx.append(f'이 절의 조각: 표 {n_t}, 설명 {n_r}')
            body, used = [], []
            if sec_id in self.heading_extra:
                body.append('절 제목 줄의 나머지 원문: ' + self.heading_extra[sec_id])
            for x in scope:
                line = body_of(x)
                if body and est('\n'.join(ctx + body + [line])) > CONFIG['rule_target_est_tokens']:
                    break
                body.append(line)
                used.append(x)
            issues = []
            if len(used) < len(scope):
                issues.append(f'scope_quotes_limited: 적용 범위 문장 {len(scope)}개 중 {len(used)}개만 인용(나머지는 해당 설명 조각에 있음)')
            if not own:
                issues.append('no_content: 이 절에 본문 조각이 없음' +
                              ('(내용은 절 제목 줄에 붙은 원문뿐)' if sec_id in self.heading_extra else '(제목만 있음)'))
            cid = f"w:{sec_id.split(':', 1)[1]}"
            links = [{'link_type': 'heading_node', 'node': sec['heading_node_id'], 'confirmed': True, 'status': '절 제목 노드'}]
            if sec['parent_section_id']:
                links.append({'link_type': 'parent_section', 'section': sec['parent_section_id'], 'confirmed': True, 'status': '절 계층'})
            first = min((ch['_first_idx'] for ch in own if ch['_first_idx'] is not None), default=None)
            self.add_chunk(cid, 'work', sec_id, '\n'.join(ctx), '\n'.join(body), (1, 1), [(x, 'scope_quote') for x in used],
                           'ok', issues, label(sec), [sec['first_page']], links)
            self.chunks[-1]['_first_idx'] = first if first is not None else 10 ** 8
            for ch in own:
                self.link(ch['chunk_id'], 'work_chunk', chunk=cid, confirmed=True, status='같은 절의 공종 조각')

    def reference_links(self):
        by_node = defaultdict(set)
        for s in self.sources:
            if s['role'] == 'body':
                by_node[self.d_src_node[s['search_uid']]].add(s['chunk_id'])
        for c in self.cells:
            by_node[c['cell_node_id']].add(c['chunk_id'])
        self.unlinked_edges = []
        for e in self.d['edges']:
            cs = sorted(by_node.get(e['from_node_id'], []))
            if not cs:
                self.unlinked_edges.append(e['edge_id'])
            for cid in cs:
                # confirmed=True는 '출발 문장이 이 조각에 있음'이다. 대상 확인 상태는 edges.target_status에 그대로 있다
                self.link(cid, 'reference', edge=e['edge_id'], confirmed=True,
                          status=f"출발 문장 포함; 대상 {e['target_status']}({'기존 참조' if e['origin'] == 'existing_reference' else '새 후보'}); 적용 여부는 질문별 판단")

    @property
    def d_src_node(self):
        if not hasattr(self, '_srcnode'):
            self._srcnode = {x['search_uid']: x['source_node_id'] for x in self.d['search']}
        return self._srcnode


def build(c, rid):
    t0 = time.perf_counter()
    d = read_input(c, rid)
    b = Builder(d)
    b.run()
    code = {p.name: sha(p.read_bytes()) for p in CODE_FILES}
    sid = f"cs-{rid.rsplit('-', 1)[-1]}-" + sha(json.dumps({'release': rid, 'input': d['input_sha256'], 'code': code,
                                                             'config': CONFIG}, sort_keys=True).encode())[:12]
    return d, b, {'chunk_set_id': sid, 'code_sha256': code, 'elapsed_build_sec': round(time.perf_counter() - t0, 1)}


# ---------------- 저장 ----------------
TABLES = ['chunks', 'chunk_sources', 'chunk_cells', 'chunk_links', 'chunk_exclusions']


def rows(d, b, sid):
    rid = d['release_id']
    dump = db.dump
    return {
        'chunks': (['chunk_set_id', 'chunk_id', 'release_id', 'ordinal', 'kind', 'section_id', 'division', 'title', 'page_first',
                    'page_last', 'part_index', 'part_count', 'context_text', 'body_text', 'text', 'est_tokens', 'token_method',
                    'status', 'issues'],
                   [(sid, x['chunk_id'], rid, x['ordinal'], x['kind'], x['section_id'], x['division'], x['title'], x['page_first'],
                     x['page_last'], x['part_index'], x['part_count'], x['context_text'], x['body_text'], x['text'],
                     x['est_tokens'], x['token_method'], x['status'], dump(x['issues'])) for x in b.chunks]),
        'chunk_sources': (['chunk_set_id', 'chunk_id', 'ord', 'release_id', 'search_uid', 'role'],
                          [(sid, s['chunk_id'], s['ord'], rid, s['search_uid'], s['role']) for s in b.sources]),
        'chunk_cells': (['chunk_set_id', 'chunk_id', 'release_id', 'cell_node_id', 'role'],
                        sorted({(sid, x['chunk_id'], rid, x['cell_node_id'], x['role']) for x in b.cells})),
        'chunk_links': (['chunk_set_id', 'chunk_id', 'release_id', 'link_type', 'target_chunk_id', 'target_node_id',
                         'target_section_id', 'target_edge_id', 'confirmed', 'status', 'relation_id', 'link_ord'],
                        [(sid, l['chunk_id'], rid, l['link_type'], l['target_chunk_id'], l['target_node_id'], l['target_section_id'],
                          l['target_edge_id'], l['confirmed'], l['status'], l['relation_id'], l['link_ord']) for l in b.links]),
        'chunk_exclusions': (['chunk_set_id', 'release_id', 'search_uid', 'reason'],
                             [(sid, rid, e['search_uid'], e['reason']) for e in b.excl]),
    }


def stats(d, b):
    kinds = defaultdict(int)
    for ch in b.chunks:
        kinds[ch['kind']] += 1
    pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(len(xs) * p))] if xs else None
    size = {}
    for k in ('work', 'rule', 'table'):
        xs = [ch['est_tokens'] for ch in b.chunks if ch['kind'] == k]
        size[k] = {'count': len(xs), 'min': min(xs), 'median': pct(xs, .5), 'p95': pct(xs, .95), 'max': max(xs),
                   'over_target': sum(x > CONFIG['table_target_est_tokens' if k == 'table' else 'rule_target_est_tokens'] for x in xs),
                   'over_cap': sum(x > CONFIG['safety_cap_est_tokens'] for x in xs)}
    status = defaultdict(int)
    for ch in b.chunks:
        status[f"{ch['kind']}:{ch['status']}"] += 1
    tables_n = [nid for nid, x in d['nodes'].items() if x['kind'] == 'table']
    t_chunks = defaultdict(list)
    for l in b.links:
        if l['link_type'] == 'table_node':
            t_chunks[l['target_node_id']].append(l['chunk_id'])
    excl_reason = defaultdict(int)
    for e in b.excl:
        excl_reason[e['reason']] += 1
    return {'chunks_by_kind': dict(kinds), 'status': dict(status), 'size_est_tokens': size,
            'tables': {'total': len(tables_n), 'with_chunk': sum(1 for t in tables_n if t_chunks.get(t)),
                       'split_into_parts': sum(1 for t in tables_n if len(t_chunks.get(t, [])) > 1),
                       'without_chunk': sorted(t for t in tables_n if not t_chunks.get(t))},
            'input_rows': len(d['search']), 'excluded': dict(excl_reason),
            'used_rows': sum(1 for x in d['search'] if b.usage.get(x['search_uid'])),
            'issues': {k: sum(1 for ch in b.chunks if any(i.startswith(k) for i in ch['issues']))
                       for k in ('formula_unresolved', 'membership_unconfirmed', 'oversize', 'scope_quotes_limited', 'no_content')},
            'links_by_type': {t: sum(1 for l in b.links if l['link_type'] == t) for t in sorted({l['link_type'] for l in b.links})},
            'superseded_relations_excluded': sorted(b.superseded), 'relations_used_after_exclusion': b.used_relations,
            'edges_without_chunk': b.unlinked_edges}


def write_outputs(d, b, meta, rws):
    sid = meta['chunk_set_id']
    out = WORK / 'out' / 'chunks' / sid
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'chunks.jsonl', 'w', encoding='utf-8') as f:
        src = defaultdict(list)
        for s in b.sources:
            src[s['chunk_id']].append({'search_uid': s['search_uid'], 'role': s['role']})
        lk = defaultdict(list)
        for l in b.links:
            lk[l['chunk_id']].append({k: v for k, v in l.items() if k not in ('chunk_id', 'link_ord') and v is not None})
        cl = defaultdict(list)
        for x in sorted({(c['chunk_id'], c['cell_node_id'], c['role']) for c in b.cells}):
            cl[x[0]].append({'cell_node_id': x[1], 'role': x[2]})
        for ch in sorted(b.chunks, key=lambda x: x['ordinal']):
            f.write(json.dumps({'chunk_set_id': sid, 'release_id': d['release_id'], **ch, 'sources': src[ch['chunk_id']],
                                'cells': cl[ch['chunk_id']], 'links': lk[ch['chunk_id']]}, ensure_ascii=False) + '\n')
    ex = {e['search_uid']: e['reason'] for e in b.excl}
    with open(out / 'input_usage.jsonl', 'w', encoding='utf-8') as f:
        for x in d['search']:
            f.write(json.dumps({'search_uid': x['search_uid'], 'search_idx': x['search_idx'], 'page': x['page'],
                                'used_in': b.usage.get(x['search_uid'], []), 'excluded': ex.get(x['search_uid'])},
                               ensure_ascii=False) + '\n')
    st = stats(d, b)
    db.write(out / 'stats.json', st)
    imp = {t: {'rows': len(r), 'content_sha256': db.content_hash(c, r)} for t, (c, r) in rws.items()}
    man = {'chunk_set_id': sid, 'release_id': d['release_id'], 'input_sha256': d['input_sha256'], 'config': CONFIG,
           'code_sha256': meta['code_sha256'], 'tables': imp, 'elapsed_build_sec': meta['elapsed_build_sec']}
    db.write(out / 'import_manifest.json', man)
    db.write(out / 'manifest.json', {'chunk_set_id': sid, 'files_sha256': {p.name: sha(p.read_bytes())
                                                                           for p in sorted(out.iterdir()) if p.name != 'manifest.json'}})
    return out, st, man


def migrate():
    with psycopg.connect(db.dsn()) as c:
        c.execute(MIGRATION.read_text(encoding='utf-8'))
    print('migrated', MIGRATION.name)


def load(rid, fail_after=None):
    t0 = time.perf_counter()
    with psycopg.connect(db.dsn()) as c:
        d, b, meta = build(c, rid)
        sid = meta['chunk_set_id']
        rws = rows(d, b, sid)
        out, st, man = write_outputs(d, b, meta, rws)
        c.commit()
        try:
            with c.transaction():
                c.execute("""insert into rag_knowledge.chunk_sets(chunk_set_id, release_id, status, config, input_sha256, code_sha256)
                             values (%s,%s,'loading',%s,%s,%s) on conflict (chunk_set_id) do update set status='loading', completed_at=null""",
                          (sid, rid, db.dump(CONFIG), d['input_sha256'], db.dump(meta['code_sha256'])))
                for t in reversed(TABLES):
                    c.execute(f'delete from rag_knowledge.{t} where chunk_set_id=%s', (sid,))
                for t in TABLES:
                    cols, data = rws[t]
                    with c.cursor().copy(f"copy rag_knowledge.{t} ({','.join(cols)}) from stdin") as cp:
                        for r in data:
                            cp.write_row(r)
                    if fail_after == t:
                        raise RuntimeError(f'시험용 중단: {t} 적재 직후')
                got = {t: c.execute(f'select count(*) from rag_knowledge.{t} where chunk_set_id=%s', (sid,)).fetchone()[0] for t in TABLES}
                if got != {t: len(rws[t][1]) for t in TABLES}:
                    raise RuntimeError(f'적재 행 수 불일치 {got}')
                c.execute('set constraints all immediate')
                c.execute("update rag_knowledge.chunk_sets set status='complete', counts=%s, completed_at=now() where chunk_set_id=%s",
                          (db.dump({'rows': got, 'stats': {k: st[k] for k in ('chunks_by_kind', 'status')}}), sid))
        except Exception:
            with c.transaction():
                c.execute("""insert into rag_knowledge.chunk_sets(chunk_set_id, release_id, status, config, input_sha256, code_sha256)
                             values (%s,%s,'failed',%s,%s,%s) on conflict (chunk_set_id) do nothing""",
                          (sid, rid, db.dump(CONFIG), d['input_sha256'], db.dump(meta['code_sha256'])))
            raise
    print(json.dumps({'chunk_set_id': sid, 'out': str(out.relative_to(db.bi.ROOT)), 'rows': {t: len(r[1]) for t, r in rws.items()},
                      'chunks_by_kind': st['chunks_by_kind'], 'elapsed_sec': round(time.perf_counter() - t0, 1)}, ensure_ascii=False))
    return sid


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('cmd', choices=['migrate', 'load'])
    p.add_argument('--release', default=DEFAULT_RELEASE)
    p.add_argument('--fail-after')
    a = p.parse_args()
    migrate() if a.cmd == 'migrate' else load(a.release, a.fail_after)
