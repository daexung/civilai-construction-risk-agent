"""4c 공통 후보·문맥 생성. 기존 결합 검색(retrieve.Retriever.search hybrid)의 fused 목록을 그대로 후보로 쓰고, 후보마다 문맥을 붙인다.
질문 벡터는 캐시만 쓴다(임베딩 호출 없음). 정답을 알고 후보를 보충하지 않는다. 결과는 candidates/<질문>.json에 한 번 쓰고 해시를 고정한다.
선택기(모델)에는 질문 글과 후보 문맥만 전달한다. 질문 ID는 파일 이름과 기록에만 쓴다."""
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402

OUT = HERE / 'candidates'
READ_BUDGET = 20000          # 연결 문맥을 읽을 때 예산 때문에 빠지지 않게 큰 값(빠지면 excluded에 기록)


def sha(o):
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def main():
    exp = json.loads((HERE / 'expectations_fixed.json').read_text(encoding='utf-8'))
    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    OUT.mkdir(exist_ok=True)
    vers = se.versions(sel)
    index = {}
    for q in exp['questions']:
        s = rt.search(q['question'], 'hybrid')
        cands, linked = [], {}
        for rank, h in enumerate(s['fused'], 1):
            cid = h['chunk_id']
            i = rt.pos[cid]
            x = rt.items[i]
            sec = sel.sec.get(x['section_id'], {})
            par = sel.sec.get(sec.get('parent'), {})
            r = rt.reader.read([cid], 1, READ_BUDGET, include_cells=False)
            links, refs = [], []
            for lid, u in r['units'].items():
                if lid == cid or u.get('tier', 9) > 2:
                    continue
                w = u['why_included'][0] if u['why_included'] else {}
                links.append({'chunk_id': lid, 'kind': u['kind'], 'relation': w.get('kind'), 'link_state': w.get('link_state', 'confirmed'),
                               'status': u['status'], 'normal_calculation_basis': u['normal_calculation_basis'], 'relation_id': w.get('relation_id')})
                if lid not in linked:
                    linked[lid] = {'chunk_id': lid, 'kind': u['kind'], 'section_id': rt.by_id[lid]['section_id'], 'status': u['status'],
                                   'text': rt.by_id[lid]['text']}
            for ref in r['references']:
                if ref['from_chunk'] != cid:
                    continue
                refs.append({'edge_id': ref['edge_id'], 'expression': ref['expression'], 'sentence': ref['sentence'],
                             'target_status': ref['target_status'], 'status_reason': ref['status_reason'], 'applicability': ref['applicability'],
                             'targets': [{'section_id': t['section_id'], 'title': t['title']} for t in ref.get('targets', [])],
                             'followed_chunks': ref.get('followed_chunks', [])})
            subhead = next((l[len('소제목:'):].strip() for l in x['text'].split('\n') if l.startswith('소제목:')), None)
            cands.append({
                'chunk_id': cid, 'rank': rank, 'rrf': round(h['score'], 6), 'bm25_rank': h['bm25_rank'], 'bm25_score': h['bm25_score'],
                'vector_rank': h['vector_rank'], 'cosine': h['cosine'],
                'kind': x['kind'], 'section_id': x['section_id'],
                'section_path': f"{x['division']} {sec.get('number', '')} {sec.get('title', '')}".strip(),
                'parent_title': par.get('title'), 'status': x['status'], 'issues': x['issues'],
                'basis': sel.basis.get(i), 'label_from_preceding_rule': sel.label.get(i) or None, 'subheading_in_text': subhead,
                'text': x['text'], 'linked': links, 'references': refs,
                'read_excluded': [e['reason'] for e in r['excluded'] if e['reason'] != 'optional_not_requested'],
            })
        for n, c in enumerate(cands, 1):
            c['alias'] = f'C{n:02d}'
        for n, k in enumerate(sorted(l for l in linked if l not in {c['chunk_id'] for c in cands}), 1):
            linked[k]['alias'] = f'L{n:02d}'
        for k, l in linked.items():                  # 후보이기도 한 연결 조각은 후보 별칭을 쓴다
            if 'alias' not in l:
                l['alias'] = next(c['alias'] for c in cands if c['chunk_id'] == k)
        data = {'qid': q['id'], 'question': q['question'], 'normalized_query': s['normalized_query'], 'division_filter': s['division_filter'],
                'candidates': cands, 'linked_passages': linked, 'dropped_as_duplicate': s['dropped'],
                'search': {'n_bm25': len(s['bm25']), 'n_vector': len(s['vector']), 'n_fused_kept': len(cands), 'n_dropped': len(s['dropped'])}}
        data['candidate_set_sha256'] = sha([[c['chunk_id'], c['rank'], c['rrf'], c['bm25_rank'], c['vector_rank']] for c in cands] + [vers['chunk_set_id'] if 'chunk_set_id' in vers else None])
        (OUT / f"{q['id']}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        index[q['id']] = {'n_candidates': len(cands), 'n_linked_only': sum(1 for l in linked.values() if l['alias'].startswith('L')),
                          'candidate_set_sha256': data['candidate_set_sha256']}
    (HERE / 'candidate_index.json').write_text(json.dumps({'versions': vers, 'questions': index}, ensure_ascii=False, indent=1), encoding='utf-8')
    rt.close()
    print(json.dumps(index, ensure_ascii=False))


if __name__ == '__main__':
    main()
