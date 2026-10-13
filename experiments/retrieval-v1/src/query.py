"""적재한 릴리스를 읽는 얇은 조회 경로(EvidenceStore 초안). 적용 여부는 판단하지 않는다."""
import json


def walk(start_ids, next_fn, max_depth=2):
    """참조를 따라 읽는다. 방문한 노드는 다시 읽지 않고(순환 방지), 깊이 한도에 걸린 경로는 남긴다."""
    visited, frontier, steps, cut = set(start_ids), list(start_ids), [], []
    for depth in range(1, max_depth + 1):
        nxt = []
        for nid in frontier:
            for edge in next_fn(nid):
                steps.append({'depth': depth, 'from': nid, **edge})
                for t in edge.get('target_nodes', []):
                    if t in visited:
                        continue
                    visited.add(t)
                    nxt.append(t)
        frontier = nxt
    for nid in frontier:
        if next_fn(nid):
            cut.append(nid)
    return {'steps': steps, 'visited': sorted(visited), 'unresolved_references': cut}


class EvidenceStore:
    def __init__(self, conn, release_id):
        self.c, self.rid = conn, release_id

    def references_from(self, node_id, origins=('existing_reference', 'scan_candidate')):
        """노드에서 나가는 참조(기존 232건과 추가 후보 9건, origin으로 구분). 절 제목 노드면 그 절 안 모든 노드의 참조를 본다.
        청크 단위 근거 조회는 src/evidence.py를 쓴다."""
        ids = [node_id] + [r[0] for s in self.c.execute(
            "select section_id from rag_knowledge.sections where release_id=%s and heading_node_id=%s",
            (self.rid, node_id)).fetchall() for r in self.section_nodes(s[0])]
        rows = self.c.execute("""
            select e.edge_id, e.expression, e.target_status, e.reason, e.condition_text, e.source_confirmed, e.origin,
                   coalesce(json_agg(json_build_object('role', k.role, 'section_id', k.section_id,
                            'heading_node_id', s.heading_node_id, 'subitem_node_id', k.subitem_node_id,
                            'division', s.division, 'number', s.number, 'title', s.title, 'page', s.first_page))
                            filter (where k.edge_id is not null), '[]')
            from rag_knowledge.edges e
            left join rag_knowledge.edge_candidates k on k.release_id = e.release_id and k.edge_id = e.edge_id
            left join rag_knowledge.sections s on s.release_id = k.release_id and s.section_id = k.section_id
            where e.release_id = %s and e.from_node_id = any(%s) and e.origin = any(%s)
            group by e.release_id, e.edge_id order by e.edge_id""", (self.rid, ids, list(origins))).fetchall()
        out = []
        for eid, expr, st, why, cond, conf, origin, cands in rows:
            cands = cands if isinstance(cands, list) else json.loads(cands)
            out.append({'edge_id': eid, 'origin': origin, 'expression': expr, 'target_status': st, 'reason': why, 'condition_text': cond,
                        'source_confirmed': conf, 'applicability': 'unknown(질문별 판단)',
                        'targets': [x for x in cands if x['role'] == 'target'],
                        'candidates': [x for x in cands if x['role'] == 'candidate'],
                        # 확정 대상만 따라간다. 후보는 따라가지 않는다
                        'target_nodes': [x['subitem_node_id'] or x['heading_node_id'] for x in cands if x['role'] == 'target']
                        if st in ('resolved', 'partial') else []})
        return out

    def section_nodes(self, section_id):
        """절 범위 안 글 노드(문서 순서). 표는 노드로, 칸은 표에서 읽는다.
        원문 대조 교정으로 더한 제목·기준 노드는 문서 순서 번호가 없어 범위 조회로 잡히지 않으므로 교정 장부로 따로 더한다."""
        rows = self.c.execute("""
            select n.node_id, n.kind, n.page, left(coalesce(n.text, ''), 120)
            from rag_knowledge.sections s join rag_knowledge.nodes n
              on n.release_id = s.release_id and n.division = s.division and n.region = 'body'
             and n.doc_order >= s.start_order and n.doc_order < s.end_order
            where s.release_id = %s and s.section_id = %s order by n.doc_order""", (self.rid, section_id)).fetchall()
        corr = self.c.execute("""
            select n.node_id, n.kind, n.page, left(coalesce(n.text, ''), 120)
            from rag_knowledge.sections s join rag_knowledge.corrections k
              on k.release_id = s.release_id and k.data->>'division' = s.division and k.data->>'number' = s.number
            join rag_knowledge.nodes n on n.release_id = s.release_id and n.structure->>'correction_id' = k.data->>'correction_id'
            where s.release_id = %s and s.section_id = %s order by n.node_id""", (self.rid, section_id)).fetchall()
        return list(corr) + list(rows)

    def follow_references(self, node_ids, max_depth=2):
        return walk(node_ids, self.references_from, max_depth)
