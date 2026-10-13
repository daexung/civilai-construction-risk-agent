"""두 릴리스를 DB에서 직접 비교한다. 대상 밖 차이가 있으면 종료 코드 1.

  python -B experiments/retrieval-v1/checks/compare_releases.py <이전 release_id> <새 release_id>
"""
import json
import sys
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
import db  # noqa: E402

# 표마다 비교할 열(release_id 제외)과 키
SPEC = {
    'nodes': ('node_id', ['document_id', 'kind', 'page', 'doc_order', 'odl_id', 'bbox', 'text', 'parent_node_id', 'division', 'region', 'structure']),
    'sections': ('section_id', ['division', 'level', 'number', 'title', 'title_raw', 'heading_node_id', 'parent_section_id',
                                'start_order', 'end_order', 'first_page', 'last_page', 'status', 'evidence']),
    'toc_entries': ('toc_id', ['node_id', 'division', 'number', 'title', 'printed_page', 'matched_section_id', 'match_status']),
    'source_records': ('record_uid', ['record_idx', 'kind', 'page', 'text', 'source_node_id', 'record', 'link', 'section_id']),
    'record_cells': ("record_uid || '|' || cell_node_id", []),
    'source_relations': ('relation_id', ['type', 'from_raw', 'to_raw', 'from_node_id', 'to_node_id', 'from_norm', 'to_norm',
                                         'confirmed', 'status', 'raw']),
    'edges': ('edge_id', ['origin', 'relation_id', 'from_node_id', 'expression', 'sentence', 'condition_text', 'target_division',
                          'target_number', 'target_subitem', 'target_status', 'reason', 'method', 'source_confirmed',
                          'source_status', 'evidence']),
    'edge_candidates': ("edge_id || '#' || rank", ['role', 'section_id', 'subitem_node_id', 'reason']),
}


def rows(c, rid, table, key, cols):
    sel = ', '.join([key] + cols) if cols else key
    return {r[0]: r[1:] for r in c.execute(f'select {sel} from rag_knowledge.{table} where release_id=%s', (rid,)).fetchall()}


def main(old, new):
    out = {'old_release': old, 'new_release': new, 'tables': {}}
    with psycopg.connect(db.dsn()) as c:
        for t, (key, cols) in SPEC.items():
            a, b = rows(c, old, t, key, cols), rows(c, new, t, key, cols)
            changed = []
            for k in sorted(set(a) & set(b)):
                diff = [cols[i] for i, (x, y) in enumerate(zip(a[k], b[k])) if x != y]
                if diff:
                    changed.append({'id': k, 'fields': diff,
                                    'before': {f: a[k][cols.index(f)] for f in diff}, 'after': {f: b[k][cols.index(f)] for f in diff}})
            out['tables'][t] = {'old': len(a), 'new': len(b), 'added': sorted(set(b) - set(a)), 'removed': sorted(set(a) - set(b)),
                                'changed': changed}
    corr = json.loads((WORK / 'corrections/shoulder_sections.json').read_text(encoding='utf-8'))
    members = {n for s in corr['sections'] for n in s['members']}
    prev = {f"pumsem-2026-errata1:civil:{s['expected_previous_section']}" for s in corr['sections']}
    T = out['tables']
    # 허용하는 차이(교정 대상): 새 절 3, 교정 노드 6, 앞 절 3개의 끝 범위, 목차 3줄의 대조, 대상 레코드의 절 소속
    allowed = {
        'nodes_added': all(x.startswith('corr:') for x in T['nodes']['added']) and len(T['nodes']['added']) == 6,
        'sections_added': len(T['sections']['added']) == 3,
        'sections_changed_only_previous_end': all(x['id'] in prev and set(x['fields']) <= {'end_order', 'last_page'}
                                                  for x in T['sections']['changed']),
        'toc_changed_only_three_matches': len(T['toc_entries']['changed']) == 3 and all(
            set(x['fields']) <= {'matched_section_id', 'match_status'} for x in T['toc_entries']['changed']),
        'records_changed_only_section_of_members': all(x['fields'] == ['section_id'] for x in T['source_records']['changed'])
            and len(T['source_records']['changed']) == 30,
    }
    others = {t: v for t, v in T.items() if t not in ('nodes', 'sections', 'toc_entries', 'source_records')}
    allowed['other_tables_identical'] = all(not v['added'] and not v['removed'] and not v['changed'] for v in others.values())
    allowed['nothing_removed'] = all(not v['removed'] for v in T.values())
    allowed['nodes_unchanged'] = not T['nodes']['changed']
    out['checks'] = allowed
    out['summary'] = {t: {'old': v['old'], 'new': v['new'], 'added': len(v['added']), 'removed': len(v['removed']),
                          'changed': len(v['changed'])} for t, v in T.items()}
    out['run_info_difference'] = '릴리스 ID만 다름(입력 해시는 같고, 교정 자료·교정 코드·두 번째 마이그레이션 해시가 더해짐)'
    dest = db.OUT / new / 'compare_with_previous_release.json'   # db.OUT: 격리 출력 확인 때 바꿔 쓴다
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    db.write_manifest(new)   # 이 파일도 자료 폴더 파일이므로 저장 뒤 해시 목록을 다시 만든다
    print(json.dumps({'summary': out['summary'], 'checks': allowed}, ensure_ascii=False, indent=1))
    return all(allowed.values())


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(0 if main(sys.argv[1], sys.argv[2]) else 1)
