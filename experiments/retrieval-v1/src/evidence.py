"""근거 조회(3단계): 찾은 청크 ID에서 원문·표·기준·설명·참조 절을 출처와 상태까지 가져온다. 읽기 전용, 임베딩·외부 API 없음.

  python -B experiments/retrieval-v1/src/evidence.py <chunk_id> [<chunk_id> ...] [--depth 1] [--budget 4000] [--text]

- 청킹 묶음이 연결한 원문 릴리스만 쓴다(PINNED). 버전이 다르거나 미완료면 거부한다. 최근 적재 기록(out/input_manifest.json)은 보지 않는다.
- 적용 여부는 판단하지 않는다(applicability=unknown). 대상 확인(target_status)·관계 확정(confirmed)·정상 계산 근거 여부를 따로 둔다.
- 길어깨 교정과 맞지 않는 원본 관계(superseded_relations)는 어떤 조회 경로에도 쓰지 않는다.
- 결과에 시각이 없다. 같은 입력이면 같은 JSON이다.
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chunking as ch  # noqa: E402
import db  # noqa: E402

PINNED = {'cs-37f81b5cfb1b-46f4f035c0fa': 'rk-complete-82c206c61e21-37f81b5cfb1b'}
DEFAULT_CS = 'cs-37f81b5cfb1b-46f4f035c0fa'
MAX_DEPTH = 2
# 예산을 쓰는 순서. 앞 단계가 먼저 담긴다.
TIERS = {0: 'selected', 1: 'structural_parent_child', 2: 'position_evidence_context', 3: 'reference_target_depth1',
         4: 'reference_target_depth2', 5: 'optional'}
NEED = {0: 'required', 1: 'required', 2: 'check_context', 3: 'reference_target', 4: 'reference_target', 5: 'optional'}
NOT_NORMAL = ('held', 'membership_unconfirmed', 'formula_unresolved', 'semantic_unconfirmed', 'no_content')
SOFT_CELLS = 400


def sha(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def link_state(confirmed, status):
    """관계 상태: 구조·위치로 확정 / 위치 근거(미확정) / 후보. 대상 확인(target_status)과는 다른 값이다."""
    if confirmed:
        return 'confirmed'
    return 'candidate' if (status or '').startswith('후보') else 'position_evidence_unconfirmed'


# ---------------- 순수 탐색(DB 없음): 순환·깊이 한도·중복 ----------------
def traverse(starts, outgoing, max_depth):
    """starts에서 outgoing(unit) -> [{'edge_id', 'status', 'targets': [unit...]}]를 따라 읽는다.
    같은 대상은 한 번만 읽고(순환 방지) 다시 만난 경로는 already_read로 남긴다. 깊이 한도에 걸린 연결은 cut에 이유와 경로를 남긴다.
    서로 다른 연결(edge_id)은 문장이 같아도 지우지 않는다."""
    reads = {s: {'depth': 0, 'path': [s]} for s in starts}
    steps, cut, frontier = [], [], list(starts)
    for level in range(1, max_depth + 2):
        nxt = []
        for u in frontier:
            for e in outgoing(u):
                step = {'depth': level, 'from_unit': u, 'edge_id': e['edge_id'], 'status': e['status'],
                        'path': reads[u]['path'] + [e['edge_id']]}
                if level > max_depth:
                    cut.append({**step, 'reason': 'depth_limit', 'max_depth': max_depth})
                    continue
                step['targets'] = []
                for t in e['targets']:
                    if t in reads:
                        step['targets'].append({'unit': t, 'already_read': True, 'first_path': reads[t]['path']})
                    else:
                        reads[t] = {'depth': level, 'path': step['path'] + [t]}
                        step['targets'].append({'unit': t, 'already_read': False})
                        nxt.append(t)
                steps.append(step)
        frontier = nxt
        if not frontier:
            break
    return {'reads': reads, 'steps': steps, 'cut': cut}


# ---------------- 조회 ----------------
class Reader:
    def __init__(self, conn, chunk_set_id=DEFAULT_CS):
        self.c = conn
        if chunk_set_id not in PINNED:
            raise ValueError(f'허용하지 않는 청킹 묶음: {chunk_set_id} (허용: {sorted(PINNED)})')
        row = self.q('select release_id, status, input_sha256, config from rag_knowledge.chunk_sets where chunk_set_id=%s', chunk_set_id)
        if not row or row[0][1] != 'complete':
            raise ValueError(f'청킹 묶음이 없거나 complete가 아님: {chunk_set_id} {row and row[0][1]}')
        self.cs, self.rid = chunk_set_id, row[0][0]
        if self.rid != PINNED[chunk_set_id]:
            raise ValueError(f'청킹 묶음이 연결한 원문 릴리스가 다름: {self.rid} != {PINNED[chunk_set_id]}')
        rs = self.q('select status from rag_knowledge.releases where release_id=%s', self.rid)
        if not rs or rs[0][0] != 'complete':
            raise ValueError(f'원문 릴리스가 complete가 아님: {self.rid}')
        self.chunk_input_sha256 = row[0][2]
        corr = [r[0] for r in self.q('select data from rag_knowledge.corrections where release_id=%s order by correction_id', self.rid)]
        self.corrections = {(d['division'], d['number']): d for d in corr}
        self.sup = {r['relation_id'] for d in corr for r in d.get('superseded_relations', [])}
        self.sup_dropped = 0
        self._ch, self._links, self._sec, self._node = {}, {}, {}, {}

    def q(self, sql, *a):
        return self.c.execute(sql, a).fetchall()

    # --- 기본 조회 ---
    def chunks(self, ids):
        need = [i for i in ids if i not in self._ch]
        if need:
            cols = ['chunk_id', 'kind', 'section_id', 'division', 'title', 'page_first', 'page_last', 'part_index', 'part_count',
                    'context_text', 'body_text', 'est_tokens', 'status', 'issues', 'ordinal']
            for r in self.q(f"select {','.join(cols)} from rag_knowledge.chunks where chunk_set_id=%s and chunk_id = any(%s)",
                            self.cs, need):
                self._ch[r[0]] = dict(zip(cols, r))
        return {i: self._ch[i] for i in ids if i in self._ch}

    def links(self, ids):
        need = [i for i in ids if i not in self._links]
        if need:
            for i in need:
                self._links[i] = []
            for r in self.q("""select chunk_id, link_type, target_chunk_id, target_node_id, target_section_id, target_edge_id,
                               confirmed, status, relation_id from rag_knowledge.chunk_links
                               where chunk_set_id=%s and chunk_id = any(%s) order by chunk_id, link_ord""", self.cs, need):
                if r[8] in self.sup:           # 교정과 맞지 않는 원본 관계는 조회 경로에 쓰지 않는다
                    self.sup_dropped += 1
                    continue
                self._links[r[0]].append({'type': r[1], 'chunk': r[2], 'node': r[3], 'section': r[4], 'edge': r[5],
                                          'confirmed': r[6], 'status': r[7], 'relation_id': r[8],
                                          'state': link_state(r[6], r[7])})
        return {i: self._links[i] for i in ids}

    def reverse(self, node_ids, types):
        out = []
        if node_ids:
            for r in self.q("""select chunk_id, link_type, target_node_id, confirmed, status, relation_id from rag_knowledge.chunk_links
                               where chunk_set_id=%s and target_node_id = any(%s) and link_type = any(%s) order by chunk_id, link_ord""",
                            self.cs, list(node_ids), list(types)):
                if r[5] in self.sup:
                    self.sup_dropped += 1
                    continue
                out.append({'chunk_id': r[0], 'type': r[1], 'node': r[2], 'confirmed': r[3], 'status': r[4],
                            'relation_id': r[5], 'state': link_state(r[3], r[4])})
        return out

    def table_chunks(self, table_node):
        return [r[0] for r in self.q("""select l.chunk_id from rag_knowledge.chunk_links l join rag_knowledge.chunks c
            on c.chunk_set_id=l.chunk_set_id and c.chunk_id=l.chunk_id where l.chunk_set_id=%s and l.link_type='table_node'
            and l.target_node_id=%s order by c.ordinal""", self.cs, table_node)]

    def section(self, sid):
        if sid not in self._sec:
            cols = ['section_id', 'division', 'level', 'number', 'title', 'first_page', 'last_page', 'status', 'parent_section_id',
                    'heading_node_id']
            r = self.q(f"select {','.join(cols)} from rag_knowledge.sections where release_id=%s and section_id=%s", self.rid, sid)
            self._sec[sid] = dict(zip(cols, r[0])) if r else None
        return self._sec[sid]

    def node(self, nid):
        if nid not in self._node:
            cols = ['node_id', 'kind', 'page', 'doc_order', 'bbox', 'text', 'parent_node_id', 'division', 'structure']
            r = self.q(f"select {','.join(cols)} from rag_knowledge.nodes where release_id=%s and node_id=%s", self.rid, nid)
            self._node[nid] = dict(zip(cols, r[0])) if r else None
        return self._node[nid]

    def section_chunks(self, sid):
        return [dict(zip(['chunk_id', 'kind', 'status', 'part_index', 'est_tokens', 'title', 'page_first'], r)) for r in self.q(
            """select chunk_id, kind, status, part_index, est_tokens, title, page_first from rag_knowledge.chunks
               where chunk_set_id=%s and section_id=%s order by ordinal""", self.cs, sid)]

    def node_chunks(self, node_id):
        """원문 노드를 원문 인용·소제목 문맥으로 가진 조각(문서 순서 번호가 없는 교정 노드도 찾는다)."""
        return [r[0] for r in self.q("""select distinct c.chunk_id, c.ordinal from rag_knowledge.chunk_sources s
            join rag_knowledge.search_records r on r.release_id=s.release_id and r.search_uid=s.search_uid
            join rag_knowledge.chunks c on c.chunk_set_id=s.chunk_set_id and c.chunk_id=s.chunk_id
            where s.chunk_set_id=%s and r.source_node_id=%s and s.role in ('body', 'context_subheading', 'context_basis')
            order by c.ordinal""", self.cs, node_id)]

    # --- 참조 ---
    def edge(self, eid):
        cols = ['edge_id', 'origin', 'relation_id', 'from_node_id', 'expression', 'sentence', 'condition_text', 'target_division',
                'target_number', 'target_subitem', 'target_status', 'reason', 'method', 'source_confirmed', 'source_status']
        r = self.q(f"select {','.join(cols)} from rag_knowledge.edges where release_id=%s and edge_id=%s", self.rid, eid)
        if not r:
            return None
        e = dict(zip(cols, r[0]))
        e['candidates'] = []
        for rank, role, sid, sub, why in self.q("""select rank, role, section_id, subitem_node_id, reason from rag_knowledge.edge_candidates
                                                   where release_id=%s and edge_id=%s order by rank""", self.rid, eid):
            s = self.section(sid)
            sn = self.node(sub) if sub else None
            e['candidates'].append({'rank': rank, 'role': role, 'section_id': sid, 'division': s['division'], 'number': s['number'],
                                    'title': s['title'], 'level': s['level'], 'page': s['first_page'], 'reason': why,
                                    'subitem_node_id': sub, 'subitem_text': sn['text'] if sn else None,
                                    'subitem_page': sn['page'] if sn else None})
        n = self.node(e['from_node_id'])
        e['from_page'] = n['page'] if n else None
        e['from_node_kind'] = n['kind'] if n else None
        return e

    def reference_edges(self, cid):
        return [self.edge(l['edge']) for l in self.links([cid])[cid] if l['type'] == 'reference']

    def target_chunks(self, e):
        """참조 대상의 조각들과 읽지 않은 이유. 확정 대상(role=target)만 따라간다. 후보는 따라가지 않는다."""
        units, notes = [], []
        if e['target_status'] not in ('resolved', 'partial'):
            return units, notes
        for t in e['candidates']:
            if t['role'] != 'target':
                continue
            sec = self.section(t['section_id'])
            own = self.section_chunks(t['section_id'])
            if not own:
                kids = [dict(zip(['section_id', 'number', 'title'], r)) for r in self.q(
                    """select section_id, number, title from rag_knowledge.sections where release_id=%s and parent_section_id=%s
                       order by start_order""", self.rid, t['section_id'])]
                for k in kids:
                    k['work_chunk_id'] = 'w:' + k['section_id'].split(':', 1)[1]
                notes.append({'kind': 'group_target_not_expanded', 'section_id': t['section_id'], 'level': sec['level'],
                              'detail': f"대상이 상위 묶음({sec['level']})이라 하위 절 {len(kids)}개 중 질문에 맞는 절을 골라 읽어야 함", 'children': kids})
                continue
            work = next((c['chunk_id'] for c in own if c['kind'] == 'work'), None)
            if work:
                units.append(work)
            if t['subitem_node_id']:
                hit = self.node_chunks(t['subitem_node_id'])
                hit = [h for h in hit if h in {c['chunk_id'] for c in own}]
                if not hit:
                    notes.append({'kind': 'subitem_chunk_not_found', 'section_id': t['section_id'], 'node_id': t['subitem_node_id'],
                                  'detail': '하위 항목 노드를 가진 조각을 찾지 못함'})
                units += hit
                rest = [c for c in own if c['chunk_id'] not in set(units)]
                for c in rest:
                    notes.append({'kind': 'section_chunk_not_read', 'chunk_id': c['chunk_id'], 'section_id': t['section_id'],
                                  'detail': '하위 항목이 가리키는 부분만 읽음. 같은 절의 다른 조각은 필요하면 따로 조회', 'est_tokens': c['est_tokens']})
            else:
                for c in own:
                    if c['kind'] == 'work':
                        continue
                    if c['status'] == 'membership_unconfirmed':
                        notes.append({'kind': 'membership_unconfirmed_not_auto_read', 'chunk_id': c['chunk_id'],
                                      'section_id': t['section_id'], 'detail': '소속 미확정 설명은 자동으로 붙이지 않음', 'est_tokens': c['est_tokens']})
                        continue
                    units.append(c['chunk_id'])
        seen, out = set(), []
        for u in units:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out, notes

    # --- 한 조각의 근거 ---
    def describe(self, cid, include_cells=True):
        c = self.chunks([cid])[cid]
        sec = self.section(c['section_id']) if c['section_id'] else None
        issues = c['issues'] if isinstance(c['issues'], list) else json.loads(c['issues'])
        flags = []
        if c['status'] != 'ok':
            flags.append(c['status'])
        flags += [i.split(':')[0] for i in issues if i.split(':')[0] not in flags]
        unit = {'chunk_id': cid, 'kind': c['kind'], 'title': c['title'], 'status': c['status'], 'issues': issues, 'flags': flags,
                'normal_calculation_basis': c['status'] == 'ok' and not any(f in NOT_NORMAL for f in flags),
                'pages': [c['page_first'], c['page_last']],
                'section': None if not sec else {k: sec[k] for k in ('section_id', 'division', 'level', 'number', 'title', 'first_page', 'last_page', 'status')},
                'part': {'index': c['part_index'], 'count': c['part_count']},
                'context_text': c['context_text'], 'body_text': c['body_text'], 'est_tokens_chunk': c['est_tokens'], 'links': []}
        if sec and (sec['division'], sec['number']) in self.corrections:
            k = self.corrections[(sec['division'], sec['number'])]
            unit['correction'] = {'correction_id': k['correction_id'], 'basis': '원문 대조 교정(원시 ODL에 제목·기준 줄이 없음)', 'page': k.get('page'),
                                  'evidence': k.get('evidence'), 'heading_pdf': k.get('heading_pdf'), 'basis_pdf': k.get('basis_pdf')}
        src = self.q("""select s.ord, s.role, s.search_uid, r.origin, r.record_uid, r.correction_id, r.kind, r.page, r.source_node_id,
                               r.section_text, r.text, n.bbox, n.division
                        from rag_knowledge.chunk_sources s
                        join rag_knowledge.search_records r on r.release_id=s.release_id and r.search_uid=s.search_uid
                        left join rag_knowledge.nodes n on n.release_id=r.release_id and n.node_id=r.source_node_id
                        where s.chunk_set_id=%s and s.chunk_id=%s order by s.ord""", self.cs, cid)
        unit['sources'] = []
        for ord_, role, uid, origin, ruid, corr, kind, page, nid, stext, text, bbox, div in src:
            body = text[len(stext) + 3:] if stext and text.startswith(stext + ' | ') else text
            if kind == 'text' and body.startswith('설명 | '):
                body = body[len('설명 | '):]
            unit['sources'].append({'role': role, 'search_uid': uid, 'origin': origin, 'record_uid': ruid, 'correction_id': corr,
                                    'kind': kind, 'page': page, 'node_id': nid, 'bbox': bbox, 'division': div, 'text': body,
                                    'quoted_in_body': role == 'body'})
        for l in self.links([cid])[cid]:
            unit['links'].append({k: v for k, v in l.items() if v is not None})
            if l['type'] == 'heading_node':        # 교정 제목 노드는 문서 순서 번호가 없다. 연결로 읽는다
                hn = self.node(l['node'])
                unit['heading_node'] = {'node_id': l['node'], 'page': hn['page'], 'text': hn['text'], 'doc_order': hn['doc_order'],
                                        'bbox': hn['bbox'], 'origin': (hn['structure'] or {}).get('origin', 'parsed')}
        if c['kind'] == 'table':
            unit['table'] = self.table_info(cid, unit, include_cells)
        return unit

    def table_info(self, cid, unit, include_cells):
        tnode = next(l['node'] for l in unit['links'] if l['type'] == 'table_node')
        n = self.node(tnode)
        st = n['structure']
        parts = [{'chunk_id': p, 'part_index': self.chunks([p])[p]['part_index'], 'selected': p == cid}
                 for p in self.table_chunks(tnode)]
        body = [s for s in unit['sources'] if s['role'] == 'body']
        recs = {}
        for r in self.q("select record_uid, record, link from rag_knowledge.source_records where release_id=%s and record_uid = any(%s)",
                        self.rid, [s['record_uid'] for s in body if s['record_uid']]):
            recs[r[0]] = (r[1], r[2])
        rows = []
        for s in body:
            rec, lk = recs.get(s['record_uid'], ({}, {}))
            rows.append({'record_uid': s['record_uid'], 'page': s['page'], 'grid_rows': lk.get('grid_rows'), 'text': s['text'],
                         'parts': rec.get('parts'), 'omitted': rec.get('omitted'), 'header': rec.get('header'),
                         'row_split': rec.get('row_split'), 'structure': rec.get('structure'),
                         'shared_cell_ids': lk.get('shared_cell_ids') or []})
        cell_rows = self.q("""select cc.cell_node_id, cc.role, n.page, n.bbox, n.text, n.structure
                              from rag_knowledge.chunk_cells cc join rag_knowledge.nodes n
                                on n.release_id=cc.release_id and n.node_id=cc.cell_node_id
                              where cc.chunk_set_id=%s and cc.chunk_id=%s order by cc.role, cc.cell_node_id""", self.cs, cid)
        shared = []
        for nid, role, page, bbox, text, s in cell_rows:
            if role != 'shared_value':
                continue
            users = self.q("""select r.record_idx, r.link->'grid_rows', r.page from rag_knowledge.record_cells rc
                              join rag_knowledge.source_records r on r.release_id=rc.release_id and r.record_uid=rc.record_uid
                              where rc.release_id=%s and rc.cell_node_id=%s order by r.record_idx""", self.rid, nid)
            shared.append({'cell_node_id': nid, 'text': text, 'page': page, 'bbox': bbox,
                           'span': {k: s.get(k) for k in ('r0', 'r1', 'c0', 'c1')},
                           'applies_to_grid_rows': sorted({x for u in users for x in (u[1] or [])}),
                           'rule': '여러 행에 표시된 같은 값. 행마다 중복 합산하지 않음(원문 표기)'})
        groups = [{'group_id': g[0], 'rows': (g[1] or {}).get('rows')} for g in self.q(
            "select node_id, structure from rag_knowledge.nodes where release_id=%s and kind='table_group' and parent_node_id=%s order by node_id",
            self.rid, tnode)]
        t = {'node_id': tnode, 'page': n['page'], 'bbox': n['bbox'], 'n_rows': st.get('n_rows'), 'n_cols': st.get('n_cols'),
             'col_path': st.get('col_path'), 'flags': st.get('flags'), 'role': st.get('role'), 'parts': parts,
             'row_groups': groups, 'rows': rows, 'shared_values': shared, 'cell_count': len(cell_rows)}
        if include_cells:
            t['cells'] = [{'cell_node_id': a, 'role': b, 'page': p, 'text': x, 'r0': s.get('r0'), 'r1': s.get('r1'),
                           'c0': s.get('c0'), 'c1': s.get('c1')} for a, b, p, _, x, s in cell_rows]
        basis = []
        for l in unit['links']:
            if l['type'] == 'basis':
                bn = self.node(l['node'])
                basis.append({'node_id': l['node'], 'text': bn['text'] if bn else None, 'page': bn['page'] if bn else None,
                              'state': l['state'], 'status': l['status'], 'relation_id': l.get('relation_id')})
        t['basis'] = basis
        return t

    # --- 주변 근거 ---
    def related(self, cid):
        """(다른 조각, tier, 이유). 확정 소속·구조와 위치 근거를 구별한다. 같은 절의 모든 글은 붙이지 않는다."""
        c = self.chunks([cid])[cid]
        L = self.links([cid])[cid]
        out = []

        def add(oid, tier, kind, state, status, via=None):
            out.append((oid, tier, {'kind': kind, 'from_chunk': cid, 'link_state': state, 'link_status': status, **(via or {})}))

        if c['kind'] == 'table':
            tnode = next((l['node'] for l in L if l['type'] == 'table_node'), None)
            for l in L:
                if l['type'] == 'parent_table':                     # 칸 안 작은 표 -> 부모 표(구조 확정). 부모 칸이 든 조각을 고른다
                    cell = next((x['node'] for x in L if x['type'] == 'parent_cell'), None)
                    cand = self.table_chunks(l['node'])
                    pick = [p for p in cand if cell and self.q(
                        "select 1 from rag_knowledge.chunk_cells where chunk_set_id=%s and chunk_id=%s and cell_node_id=%s",
                        self.cs, p, cell)] or cand
                    for p in pick:
                        add(p, 1, 'parent_table', l['state'], l['status'], {'parent_cell': cell})
                elif l['type'] == 'note_table_of':                  # 주석 표 -> 소속 표 후보(미확정)
                    for p in self.table_chunks(l['node']):
                        add(p, 2, 'note_table_owner_candidate', l['state'], l['status'])
                elif l['type'] == 'continues_candidate':
                    for p in self.table_chunks(l['node']):
                        add(p, 5, 'continues_candidate', l['state'], l['status'])
            if tnode:
                for r in self.reverse([tnode], ['parent_table']):   # 이 표 칸 안의 작은 표(구조 확정)
                    add(r['chunk_id'], 1, 'nested_table', r['state'], r['status'])
                for r in self.reverse([tnode], ['related_table']):  # 이 표의 설명 후보(위치 근거)
                    add(r['chunk_id'], 2, 'related_explanation', r['state'], r['status'], {'relation_id': r['relation_id']})
                for r in self.reverse([tnode], ['note_table_of']):  # 이 표의 주석 표 후보
                    add(r['chunk_id'], 2, 'note_table_candidate', r['state'], r['status'], {'relation_id': r['relation_id']})
                for r in self.reverse([tnode], ['continues_candidate']):
                    add(r['chunk_id'], 5, 'continued_from_candidate', r['state'], r['status'])
            if c['part_count'] > 1 and tnode:
                for p in self.table_chunks(tnode):
                    if p != cid:
                        add(p, 5, 'sibling_table_part', 'confirmed', '같은 표를 길이 때문에 원문 행 묶음 경계로 나눔')
        elif c['kind'] == 'rule':
            for l in L:
                if l['type'] == 'related_table':
                    for p in self.table_chunks(l['node']):
                        add(p, 2, 'related_table', l['state'], l['status'], {'relation_id': l['relation_id']})
                elif l['type'] == 'continues_part_of':
                    add(l['chunk'], 5, 'sibling_explanation_part', l['state'], l['status'])
        for l in L:
            if l['type'] == 'work_chunk' and l['chunk'] != cid:
                add(l['chunk'], 5, 'section_work_chunk', l['state'], l['status'])
        return out

    # --- 전체 ---
    def read(self, chunk_ids, depth=1, budget_tokens=4000, include_cells=True, include_optional=False, skip_related=()):
        if depth not in range(0, MAX_DEPTH + 1):
            raise ValueError(f'참조 깊이는 0~{MAX_DEPTH}')
        found = self.chunks(list(chunk_ids))
        bad = [i for i in chunk_ids if i not in found]
        if bad:
            raise ValueError(f'청킹 묶음에 없는 청크: {bad}')
        units = {}      # chunk_id -> {'tier', 'why': [...]}

        def put(cid, tier, why):
            u = units.setdefault(cid, {'tier': tier, 'why': []})
            u['tier'] = min(u['tier'], tier)
            if why not in u['why']:
                u['why'].append(why)

        for cid in chunk_ids:
            put(cid, 0, {'kind': 'selected'})
        listed = []         # 선택하지 않은 선택적 근거(나뉜 표의 다른 부분·이어짐 후보·같은 절 공종 조각)는 기본으로 붙이지 않고 목록만 남긴다
        for cid in chunk_ids:
            for oid, tier, why in self.related(cid):
                if why['kind'] in skip_related:          # 호출한 쪽이 질문과의 관련도로 따로 고르는 연결(예: 주석 표 후보)
                    continue
                if tier == 5 and not include_optional:
                    if oid not in chunk_ids:
                        listed.append((oid, why))
                    continue
                put(oid, tier, why)
        # 위치 근거로 붙은 표의 칸 안 작은 표·부모 표(구조 확정)도 같은 표의 일부이므로 함께 읽는다. 위치 근거를 거친 것은 그대로 표시한다
        for oid in [u for u, v in units.items() if v['tier'] == 2 and self.chunks([u])[u]['kind'] == 'table']:
            for o2, tier, why in self.related(oid):
                if why['kind'] in ('parent_table', 'nested_table'):
                    put(o2, 2, {**why, 'via_unconfirmed_membership': True})
        starts = [u for u, v in units.items() if v['tier'] <= 2]
        notes_by_edge, edge_cache = {}, {}

        def outgoing(u):
            res = []
            for e in self.reference_edges(u):
                edge_cache[e['edge_id']] = e
                tc, notes = self.target_chunks(e)
                notes_by_edge[e['edge_id']] = notes
                res.append({'edge_id': e['edge_id'], 'status': e['target_status'], 'targets': tc})
            return res

        tv = traverse(starts, outgoing, depth)
        for step in tv['steps']:
            via_unconf = units[step['from_unit']]['tier'] == 2 if step['from_unit'] in units else False
            for t in step['targets']:
                put(t['unit'], 3 if step['depth'] == 1 else 4,
                    {'kind': 'reference_target', 'edge_id': step['edge_id'], 'from_chunk': step['from_unit'], 'depth': step['depth'],
                     'via_unconfirmed_membership': via_unconf or any(
                         units.get(p, {}).get('tier', 0) == 2 for p in step['path'] if p in units)})
        # 단위 설명
        desc = {cid: self.describe(cid, include_cells) for cid in units}
        for cid, u in units.items():
            d = desc[cid]
            d['tier'], d['tier_name'], d['need'], d['why_included'] = u['tier'], TIERS[u['tier']], NEED[u['tier']], u['why']
            d['render'] = self.render(d)
            d['est_tokens'] = ch.est(d['render'])
        # 문맥 예산: 완결된 단위만 담는다
        order = sorted(units, key=lambda x: (units[x]['tier'], chunk_ids.index(x) if x in chunk_ids else 10 ** 6,
                                             self._ch[x]['ordinal'], x))
        used, included, excluded = 0, [], []
        for i, cid in enumerate(order):
            d = desc[cid]
            if used + d['est_tokens'] <= budget_tokens:
                included.append(cid)
                used += d['est_tokens']
            elif not included and d['tier'] == 0:          # 첫 선택 조각은 예산이 작아도 자르지 않고 과대로 표시해 담는다
                included.append(cid)
                used += d['est_tokens']
                d['oversize_for_budget'] = True
            else:
                excluded.append({'chunk_ids': [cid], 'reason': 'budget', 'need': d['need'], 'est_tokens': d['est_tokens'],
                                 'detail': f"남은 예산 {max(budget_tokens - used, 0)}토큰보다 큼(조각을 자르지 않음)"})
        for oid, why in listed:
            if oid not in units:
                oc = self.chunks([oid]).get(oid)
                excluded.append({'chunk_ids': [oid], 'reason': 'optional_not_requested', 'need': 'optional',
                                 'est_tokens': oc['est_tokens'] if oc else None,
                                 'detail': f"{why['kind']}({why['link_state']}): 필요하면 chunk_ids에 넣어 따로 조회", 'from_chunk': why['from_chunk']})
        # 읽지 않은 대상 조각과 사유
        for eid, notes in sorted(notes_by_edge.items()):
            grp = defaultdict(list)
            for n in notes:
                if n['kind'] in ('section_chunk_not_read', 'membership_unconfirmed_not_auto_read'):
                    grp[(n['kind'], n['section_id'])].append(n)
            for (kind, sid), ns in sorted(grp.items()):
                excluded.append({'chunk_ids': [n['chunk_id'] for n in ns], 'reason': kind, 'need': 'optional', 'edge_id': eid,
                                 'section_id': sid, 'est_tokens': sum(n['est_tokens'] for n in ns), 'detail': ns[0]['detail']})
        # 참조 단계와 미해결
        refs, unresolved = [], []
        ex_budget = {c for x in excluded if x['reason'] == 'budget' for c in x['chunk_ids']}
        for step in tv['steps']:
            e = edge_cache[step['edge_id']]
            targets = [t for t in e['candidates'] if t['role'] == 'target']
            cands = [t for t in e['candidates'] if t['role'] == 'candidate']
            rec = {'edge_id': e['edge_id'], 'origin': e['origin'], 'depth': step['depth'], 'from_chunk': step['from_unit'],
                   'path': step['path'], 'from_node_id': e['from_node_id'], 'from_page': e['from_page'],
                   'expression': e['expression'], 'sentence': e['sentence'], 'condition_text': e['condition_text'] or '',
                   'condition_state': 'extracted' if e['condition_text'] else 'not_extracted(조건이 비어 있음, 무조건 적용이 아님)',
                   'target_status': e['target_status'], 'status_reason': e['reason'], 'method': e['method'],
                   'source_confirmed': e['source_confirmed'], 'source_status': e['source_status'],
                   'applicability': 'unknown', 'targets': targets, 'candidates': cands,
                   'followed_chunks': [t['unit'] for t in step['targets']],
                   'via_unconfirmed_membership': units[step['from_unit']]['tier'] == 2 or any(
                       units.get(p, {}).get('tier') == 2 for p in step['path'][:-1] if p in units)}
            refs.append(rec)
            st = e['target_status']
            if st == 'ambiguous':
                unresolved.append({'kind': 'ambiguous_target', 'edge_id': e['edge_id'], 'detail': '후보만 표시하고 자동 선택하지 않음',
                                   'path': step['path'], 'candidates': [f"{t['division']} {t['number']} {t['title']}" for t in cands]})
            elif st == 'missing':
                unresolved.append({'kind': 'missing_target', 'edge_id': e['edge_id'], 'detail': e['reason'], 'path': step['path']})
            elif st == 'external':
                unresolved.append({'kind': 'external_target', 'edge_id': e['edge_id'], 'detail': e['reason'], 'path': step['path']})
            elif st == 'partial':
                unresolved.append({'kind': 'partial_target', 'edge_id': e['edge_id'], 'path': step['path'],
                                   'detail': f"절은 읽었으나 못 찾은 하위 항목: {e['target_subitem'] or e['expression']} ({e['reason']})"})
            for n in notes_by_edge.get(e['edge_id'], []):
                if n['kind'] in ('group_target_not_expanded', 'subitem_chunk_not_found'):
                    unresolved.append({**n, 'edge_id': e['edge_id'], 'path': step['path']})
            lost = [t['unit'] for t in step['targets'] if t['unit'] in ex_budget]
            if lost:
                unresolved.append({'kind': 'budget', 'edge_id': e['edge_id'], 'path': step['path'], 'chunks': lost,
                                   'detail': '참조 대상 조각이 문맥 예산에 들어가지 않음'})
        for cut in tv['cut']:
            e = edge_cache[cut['edge_id']]
            unresolved.append({'kind': 'depth_limit', 'edge_id': cut['edge_id'], 'path': cut['path'], 'target_status': e['target_status'],
                               'detail': f"참조 깊이 한도({depth}) 때문에 따라가지 않음", 'expression': e['expression']})
        req_lost = [x for x in excluded if x['reason'] == 'budget' and x['need'] in ('required', 'check_context', 'reference_target')]
        complete = not req_lost and not unresolved
        reasons = []
        if req_lost:
            reasons.append(f"예산 때문에 빠진 필수·확인·참조 조각 {len(req_lost)}개")
        kinds = sorted({u['kind'] for u in unresolved})
        if kinds:
            reasons.append('미해결 참조: ' + ', '.join(kinds))
        agg = sorted({f for cid in included for f in desc[cid]['flags']})
        text = '\n\n'.join(desc[c]['render'] for c in included)
        cites = [{'chunk_id': cid, 'division': (desc[cid]['section'] or {}).get('division'), 'section': (desc[cid]['section'] or {}).get('number'),
                  'pages': desc[cid]['pages'], 'source_records': sorted({s['record_uid'] for s in desc[cid]['sources'] if s['record_uid']}),
                  'source_nodes': sorted({s['node_id'] for s in desc[cid]['sources']})} for cid in included]
        result = {
            'versions': {'chunk_set_id': self.cs, 'release_id': self.rid, 'chunk_input_sha256': self.chunk_input_sha256,
                         'chunk_config': CONFIG_NOTE, 'token_method': ch.CONFIG['token_method'],
                         'evidence_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         'superseded_relations_excluded': sorted(self.sup),
                         'note': '청킹 묶음이 연결한 원문 릴리스만 사용. 최근 적재 기록을 따르지 않음'},
            'request': {'chunk_ids': list(chunk_ids), 'depth': depth, 'budget_tokens': budget_tokens,
                        'include_optional': include_optional, 'skip_related': list(skip_related)},
            'selected': list(chunk_ids),
            'units': {cid: desc[cid] for cid in sorted(desc)},
            'references': refs, 'unresolved_references': unresolved, 'excluded': excluded,
            'answer_context': {'budget_tokens': budget_tokens, 'used_est_tokens': used, 'included': included,
                               'over_budget': used > budget_tokens, 'token_method': ch.CONFIG['token_method'], 'text': text},
            'coverage': {'complete': complete, 'reasons_incomplete': reasons,
                         'meaning': 'complete=예산·깊이·미해결 참조 때문에 빠진 필요 근거가 없음. 적용 여부나 계산 가능 여부가 아님'},
            'quality_flags': agg,
            'all_included_normal_calculation_basis': all(desc[c]['normal_calculation_basis'] for c in included),
            'applicability': 'unknown(이 단계에서 판단하지 않음)',
            'citations': cites,
        }
        result['result_sha256'] = sha({k: v for k, v in result.items() if k != 'result_sha256'})
        return result

    @staticmethod
    def render(d):
        sec = d['section'] or {}
        head = f"[근거 {d['chunk_id']}] {sec.get('division', '')} {sec.get('number', '')} {sec.get('title', '')} · {d['kind']} · " \
               f"{d['pages'][0]}쪽 · 상태 {d['status']}"
        marks = []
        if d.get('why_included'):
            w = d['why_included'][0]
            if w['kind'] != 'selected':
                marks.append('관계 ' + w['kind'] + (f"({w['link_state']})" if w.get('link_state') else '')
                             + (f" {w['edge_id']}" if w.get('edge_id') else ''))
            if any(x.get('via_unconfirmed_membership') for x in d['why_included']):
                marks.append('미확정 소속 설명을 거친 참조')
        marks += [f for f in d['flags'] if f != 'ok']
        if not d['normal_calculation_basis']:
            marks.append('정상 계산 근거 아님')
        lines = [head + (' · ' + ', '.join(marks) if marks else ''), '문맥(검색용, 원문 아님):', d['context_text']]
        if d['body_text']:
            lines += ['원문:', d['body_text']]
        return '\n'.join(lines)


CONFIG_NOTE = ch.CONFIG['rule_version']


def open_reader(chunk_set_id=DEFAULT_CS):
    """읽기 전용 연결로 Reader를 만든다. 조회는 데이터를 바꾸지 않는다."""
    conn = psycopg.connect(db.dsn())
    conn.read_only = True
    return Reader(conn, chunk_set_id), conn


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser()
    a.add_argument('chunk_ids', nargs='+')
    a.add_argument('--chunk-set', default=DEFAULT_CS)
    a.add_argument('--depth', type=int, default=1)
    a.add_argument('--budget', type=int, default=4000)
    a.add_argument('--text', action='store_true', help='답변에 넣을 문맥 글만 출력')
    args = a.parse_args()
    reader, conn = open_reader(args.chunk_set)
    with conn:
        res = reader.read(args.chunk_ids, args.depth, args.budget)
    print(res['answer_context']['text'] if args.text else json.dumps(res, ensure_ascii=False, indent=1, default=str))
