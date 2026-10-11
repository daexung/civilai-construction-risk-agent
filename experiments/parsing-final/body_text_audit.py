"""본문 완전성 확인: 원시 출력의 표 밖 글 전체를 최종 레코드까지 추적하고, 수정 전 결과와 비교한다.

출력
  out/body_text_trace.json      원시 글 노드마다 전달 위치(레코드·제목·기준·제외 사유). 설명 없는 항목이 있으면 실패
  out/dropped_623_ledger.json   이전에 보고된 623개 각각의 원시 항목·전체 원문·레코드·복구 여부
  out/before_after_compare.json 수정 전(local/baseline/body-text)과 비교: 표·기존 글 레코드·관계·번호 변화
"""
import collections
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parent
sys.path.insert(0, str(W))
import run  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
OUT, BEFORE = W / 'out', W / 'local/baseline/body-text'
read = run.read


def records(p):
    return [json.loads(x) for x in (p / 'records.jsonl').read_text(encoding='utf-8').splitlines()]


def one_line(t):
    return ' '.join((t or '').split())


raw = read(run.RAW)
new, old = read(OUT / 'store.json'), read(BEFORE / 'store.json')
nrec, orec = records(OUT), records(BEFORE)
nlinks, olinks = read(OUT / 'links.json'), read(BEFORE / 'links.json')
ngen, ogen = nlinks['generation']['id'], olinks['generation']['id']

# ---------------- 1. 원시 표 밖 글 전체 추적 ----------------
nodes = []          # (node, 상위 id 목록, 하위 글 위치인지)
node_types = {}


def walk(n, chain, hidden):
    node_types[n['id']] = n.get('type')
    if n.get('type') == 'table':
        return
    if isinstance(n.get('content'), str) and n['content'].strip():
        nodes.append((n, chain, hidden))
    for k in ('kids', 'list items'):
        for ch in n.get(k) or []:
            walk(ch, chain + [n['id']], hidden or n.get('type') in ('list item', 'text block'))


for k in raw['kids']:
    walk(k, [], False)

note_by_odl = {n['odl_id']: n for n in new['notes']}
basis_by_odl = collections.defaultdict(list)
for b in new['basis']:
    basis_by_odl[b['odl_id']].append(b)
head_by_odl = {h['odl_id']: h for h in new['headings']}
skip_by_odl = {s['odl_id']: s for s in new['skipped_text']}
rec_by_source = collections.defaultdict(list)
for i, l in enumerate(nlinks['record_links']):
    rec_by_source[l['source_id']].append((i, l))

# 기존 표 교정이 원시 글을 대체·합친 기록(source_corrections.apply의 correction_audit). 이번 수정과 무관한 기존 동작이다
replaced, merged = {}, {}
for a in read(OUT / 'correction_audit.json'):
    if a['kind'] == 'missing_tables':
        for n in a['removed_overlapping_nodes']:
            replaced[n['id']] = a['page']
    elif a['kind'] == 'formula':
        for i in a['ids'][:-1]:
            merged[i] = a['ids'][-1]
recovered_text, recovered_words = collections.defaultdict(str), collections.defaultdict(collections.Counter)
for t in new['tables']:
    if (t.get('correction') or {}).get('kind') == 'missing_table':
        recovered_text[t['page']] += re.sub(r'\s+', '', ''.join(c['text_raw'] for c in t['cells']))
        recovered_words[t['page']].update(w for c in t['cells'] for w in c['text_raw'].split())
trace, unexplained = [], []
for n, chain, hidden in nodes:
    oid, text = n['id'], n['content'].strip()
    item = {'odl_id': oid, 'page': n['page number'], 'odl_type': n['type'], 'bbox': n.get('bounding box'),
            'container_odl_ids': chain, 'read_position': '하위 글' if hidden else '맨 위', 'source_text': text}
    covered = next((skip_by_odl[c] for c in [oid] + chain[::-1] if c in skip_by_odl), None)
    if oid in note_by_odl:
        nt = note_by_odl[oid]
        recs = rec_by_source[nt['note_id']]
        ok = (len(recs) == 1 and recs[0][1]['source_text'] == nt['text']
              and nrec[recs[0][0]]['text'].endswith(one_line(nt['text'])))
        same_raw = nt['text'] == text or bool(nt.get('correction'))
        item.update(status='본문 레코드로 전달' if ok and same_raw else '레코드 불일치', note_id=nt['note_id'],
                    record_uid=recs[0][1]['record_uid'] if recs else None, record_idx=recs[0][0] if recs else None,
                    scope=nt['scope'], nesting=nt.get('nesting'), table_region=nt.get('table_region'))
    elif oid in head_by_odl:
        h = head_by_odl[oid]
        recs = rec_by_source[h['heading_id']]
        item.update(status='제목 레코드로 전달' if recs else '제목 문맥(절 경로·section)으로 전달',
                    heading_id=h['heading_id'], record_uid=recs[0][1]['record_uid'] if recs else None)
    elif oid in basis_by_odl:
        bs = basis_by_odl[oid]
        recs = [r for b in bs for r in rec_by_source[b['basis_id']]]
        item.update(status='기준 레코드로 전달' if recs else '기준 관계로 전달(제목 레코드가 글을 담음)',
                    basis_ids=[b['basis_id'] for b in bs], record_uid=recs[0][1]['record_uid'] if recs else None)
    elif any(c in replaced for c in [oid] + chain):
        lines = [re.sub(r'\s+', '', x) for x in text.split(chr(10)) if x.strip()]
        inside = all(x in recovered_text[n['page number']] for x in lines)
        words = not inside and not (collections.Counter(text.split()) - recovered_words[n['page number']])
        item.update(status='정상 제외' if inside or words else '표 대체 후 칸에서 찾지 못함',
                    reason='기존 누락 표 보충 교정이 표 영역 글을 표로 대체(줄마다 보충 표 칸 글에 있음)' if inside else
                    '기존 누락 표 보충 교정이 표 영역 글을 표로 대체(낱말마다 같은 쪽 보충 표 칸에 있음. 원시 줄이 여러 칸에 걸쳐 줄 단위 대조는 안 됨)'
                    if words else '기존 누락 표 보충 교정이 표 영역 글을 지웠으나 보충 표 칸에서 글을 찾지 못함',
                    excluded_by=next(c for c in [oid] + chain if c in replaced))
    elif oid in merged:
        item.update(status='정상 제외', reason='기존 분수식 교정이 이 글을 다른 원시 항목의 읽기용 식으로 합침',
                    excluded_by=merged[oid])
    elif covered is not None:
        item.update(status='정상 제외', reason=covered['reason'], excluded_by=covered['odl_id'],
                    table_id=covered.get('table_id'))
    else:
        item.update(status='설명 없는 누락')
    if item['status'] in ('설명 없는 누락', '레코드 불일치', '표 대체 후 칸에서 찾지 못함'):
        unexplained.append(item)
    trace.append(item)

# ---------------- 2. 이전 보고 623개 ----------------
dropped = read(BEFORE / 'dropped_text_nodes.json')
pool = collections.defaultdict(list)
for t in trace:
    if t['read_position'] == '하위 글':
        pool[t['page']].append(t)
used, ledger = set(), []
listed_counts = collections.Counter(tuple(item) for item in dropped)
group_candidates = {}
for signature, count in listed_counts.items():
    page, parent, prefix = signature
    longer_prefixes = [other for other_page, other_parent, other in listed_counts
                       if other_page == page and other_parent == parent
                       and len(other) > len(prefix) and other.startswith(prefix)]
    group_candidates[signature] = [
        t for t in pool[page]
        if t['container_odl_ids']
        and node_types.get(t['container_odl_ids'][-1]) == parent
        and t['source_text'].replace('\n', '/').startswith(prefix)
        and not any(t['source_text'].replace('\n', '/').startswith(other)
                    for other in longer_prefixes)
    ]
occurrences = collections.Counter()
for page, parent, prefix in dropped:
    signature = (page, parent, prefix)
    m = group_candidates[signature]
    occurrence = occurrences[signature]
    occurrences[signature] += 1
    # The old list contains only prefixes. Repeated entries are accounted for
    # as a whole group, then paired by their preserved source traversal order.
    if len(m) != listed_counts[signature] or m[occurrence]['odl_id'] in used:
        ledger.append({'page': page, 'listed_prefix': prefix, 'status': '원시 항목 대응 미확정',
                       'candidate_odl_ids': [t['odl_id'] for t in m],
                       'listed_count': listed_counts[signature]})
        continue
    t = m[occurrence]
    used.add(t['odl_id'])
    recovered = t['status'] == '본문 레코드로 전달'
    ledger.append({'page': page, 'listed_parent': parent, 'listed_prefix': prefix, 'odl_id': t['odl_id'],
                   'listed_occurrence': occurrence, 'matching_group_count': len(m),
                   'odl_type': t['odl_type'], 'bbox': t['bbox'], 'container_odl_ids': t['container_odl_ids'],
                   'source_text': t['source_text'], 'record_uid': t.get('record_uid'), 'record_idx': t.get('record_idx'),
                   'note_id': t.get('note_id'), 'scope': t.get('scope'), 'table_region': t.get('table_region'),
                   'was_in_before_output': False,
                   'status': '복구' if recovered else t['status'],
                   'reason': t.get('reason'), 'excluded_into_table': t.get('table_id')})
old_ids = {x['odl_id'] for k in ('notes', 'basis', 'headings') for x in old[k]}
for x in ledger:
    if x.get('odl_id') in old_ids:
        x['was_in_before_output'] = True

# ---------------- 3. 수정 전과 비교 ----------------
def strip_uid(x):
    return {k: v for k, v in x.items() if k not in ('record_uid', 'record_idx', 'generation_id')}


def norm_uid(u):
    return u.split(':', 1)[1] if isinstance(u, str) and ':' in u else u


new_note_ids = {n['note_id'] for n in new['notes'] if n.get('nesting')}
kept = [(r, l) for r, l in zip(nrec, nlinks['record_links']) if l.get('note_id') not in new_note_ids]
same_records = [strip_uid(r) for r, _ in kept] == [strip_uid(r) for r in orec]
same_links = [strip_uid(l) for _, l in kept] == [strip_uid(l) for l in olinks['record_links']]
uid_changes = sum(norm_uid(r['record_uid']) != norm_uid(o['record_uid']) for (r, _), o in zip(kept, orec))


def no_order(x):
    """문서 순서 번호(order)만 뺀다. 표에 붙은 기준 항목 안의 순서 번호도 함께 뺀다."""
    if isinstance(x, dict):
        return {k: no_order(v) for k, v in x.items() if k != 'order'}
    if isinstance(x, list):
        return [no_order(v) for v in x]
    return x


ot_, nt_ = {t['table_id']: t for t in old['tables']}, {t['table_id']: t for t in new['tables']}
table_diff = [k for k in ot_ if no_order(ot_[k]) != no_order(nt_.get(k, {}))]
order_only = [k for k in ot_ if ot_[k] != nt_[k] and k not in table_diff]
old_rel = [{k: v for k, v in r.items() if k != 'relation_id'} for r in olinks['relations']]
new_rel = [{k: v for k, v in r.items() if k != 'relation_id'} for r in nlinks['relations']
           if not (r['from'] in new_note_ids)]
added_rel = collections.Counter(r['type'] for r in nlinks['relations'] if r['from'] in new_note_ids)
shared_same = ([{**s, 'record_uids': [norm_uid(u) for u in s['record_uids']]} for s in olinks['shared_values']]
               == [{**s, 'record_uids': [norm_uid(u) for u in s['record_uids']]} for s in nlinks['shared_values']])
held = {k: t['calc_status'] for k, t in nt_.items() if t['flags']}
p758 = [r['text'] for r in nrec if r.get('table_id') == 'full-p758-o107176']
compare = {
    'before_generation': ogen, 'after_generation': ngen,
    'tables_before': len(ot_), 'tables_after': len(nt_),
    'records_before': len(orec), 'records_after': len(nrec), 'records_added': len(nrec) - len(orec),
    'added_records_are_new_body_text': len(nrec) - len(kept) == len(new_note_ids),
    'existing_records_identical_except_uid': same_records,
    'existing_record_links_identical_except_uid': same_links,
    'record_uid_changes_beyond_generation_prefix': uid_changes,
    'tables_with_content_change': table_diff,
    'tables_with_order_number_change_only': len(order_only),
    'existing_relations_identical': old_rel == new_rel,
    'added_relations_for_new_body_text': dict(added_rel),
    'shared_values_identical_except_uid_prefix': shared_same,
    'basis_same_except_order': [no_order(x) for x in old['basis']] == [no_order(x) for x in new['basis']],
    'headings_same_except_order': [no_order(x) for x in old['headings']] == [no_order(x) for x in new['headings']],
    'existing_notes_same_except_order': [no_order(x) for x in old['notes']] == [no_order(x) for x in new['notes'] if not x.get('nesting')],
    'other_store_fields_same': {k: old[k] == new[k] for k in ('pages', 'page_height', 'printed_page', 'part_marks',
                                                              'logical_tables', 'boundaries', 'context_out')},
    'open_items_same': olinks['open_items'] == nlinks['open_items'],
    'held_tables_after': held,
    'p758_values_kept': [t for t in p758 if '0.215' in t and '0.415' in t],
    'code_changed': sorted(k for k in nlinks['generation']['code_sha256']
                           if nlinks['generation']['code_sha256'][k] != olinks['generation']['code_sha256'][k]),
    'data_versions_same': all(nlinks['generation'][k] == olinks['generation'][k] for k in
                              ('raw_sha256', 'pdf_sha256', 'corrections_sha256', 'row_mappings_sha256',
                               'completeness_sha256', 'reviewed_tables_sha256', 'diagram_tables_sha256')),
}

counts = collections.Counter(t['status'] for t in trace)
hidden_counts = collections.Counter(t['status'] for t in trace if t['read_position'] == '하위 글')
reasons = collections.Counter(t.get('reason') for t in trace if t['status'] == '정상 제외' and t['read_position'] == '하위 글')
summary = {
    'raw_text_nodes_outside_tables': len(trace), 'by_status': dict(counts),
    'nested_text_nodes': sum(t['read_position'] == '하위 글' for t in trace), 'nested_by_status': dict(hidden_counts),
    'nested_excluded_reasons': dict(reasons),
    'nested_not_in_623_list': sum(1 for t in trace if t['read_position'] == '하위 글' and t['odl_id'] not in used),
    'unexplained': len(unexplained),
    'listed_623': {'total': len(ledger), **collections.Counter(x['status'] for x in ledger)},
    'nested_in_table_region_unresolved': sum(1 for t in trace if t.get('table_region')),
}
run.write(OUT / 'body_text_trace.json', {'summary': summary, 'unexplained': unexplained, 'nodes': trace})
run.write(OUT / 'dropped_623_ledger.json', ledger)
run.write(OUT / 'before_after_compare.json', compare)
print(json.dumps(summary, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in compare.items() if k not in ('held_tables_after',)}, ensure_ascii=False, indent=1))
ok = (not unexplained and compare['existing_records_identical_except_uid'] and compare['existing_record_links_identical_except_uid']
      and not compare['tables_with_content_change'] and compare['existing_relations_identical']
      and compare['shared_values_identical_except_uid_prefix'] and compare['added_records_are_new_body_text']
      and len(ledger) == 623 and all(x['status'] in ('복구', '정상 제외') for x in ledger))
print('PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
