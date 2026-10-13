"""4d 검증 순서 1: 저장된 4c 응답(모델 호출 없음)을 새 검증·상태 경로에 통과시킨다.

4c 응답은 별칭과 글 인용으로 되어 있으므로 먼저 인용을 원문 줄·행으로 되돌려 찾고(찾지 못하거나 이어 붙인 인용은 그대로 기록),
그 선택을 4d 검증기(validate_selection)와 상태 결정(resolve_status)에 넣는다. 4c 보고서에서 확인한 인용 불일치 4건이 여기서 잡히는지 본다.
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402
import select_verified as sv  # noqa: E402

C4 = WORK / 'pilots/step04c'
ANNOT = re.compile(r'\s*\[공동값[^\]]*\]')
norm = sv.norm


def locate(pool, store, chunk_id, quote):
    """인용 글을 원문 줄로 되돌려 찾는다. 반환: (분류, [줄 식별자], 설명)."""
    segs = [s.strip() for s in re.split(r'\s*(?:\.\.\.|…)\s*|\n', quote or '') if s.strip()]
    if not segs:
        return 'empty', [], '빈 인용'
    blk = pool.blocks[pool.by_chunk[chunk_id]]
    found, status = [], 'exact_span'
    for seg in segs:
        hit = [ln for ln in blk['lines'] if norm(seg) in norm(ln['text'])]
        if hit:
            found.append(hit[0]['n'])
            continue
        fr = [x for x in store.chunk[chunk_id]['context'] if norm(seg) in norm(x)]
        if fr:
            status = 'frame_line_not_selectable'
            continue
        hit = [ln for ln in blk['lines'] if norm(seg) in norm(ANNOT.sub('', ln['text']))]
        if hit:
            found.append(hit[0]['n'])
            status = 'annotation_removed_restored'
            continue
        # 연속한 두세 줄을 이어 붙인 글(한 줄이 아니라 이웃 줄에 걸친 인용)
        win = [lines for lines in ([blk['lines'][i:i + k] for i in range(len(blk['lines'])) for k in (2, 3)]) if len(lines) in (2, 3)
               and norm(seg) in norm(''.join(x['text'] for x in lines))]
        if win:
            found += [x['n'] for x in win[0]]
            status = 'multi_line_contiguous' if status == 'exact_span' else status
            continue
        other = [(b['alias'], ln['n']) for b in pool.blocks.values() if b is not blk for ln in b['lines'] if norm(seg) in norm(ln['text'])]
        if other:
            return 'wrong_candidate', [f'{a}.{n}' for a, n in other[:2]], f"인용 글이 {blk['alias']}가 아니라 {other[0][0]}의 줄에 있음"
        return 'not_verbatim', [], '원문 줄 어디에도 글자 그대로 있지 않음(열을 건너뛰거나 바꿔 씀)'
    if len(segs) > 1:
        ns = sorted(set(found))
        contiguous = all(b - a == 1 for a, b in zip(ns, ns[1:]))
        if not contiguous:
            status = 'merged_noncontiguous'
    return status, [f"{blk['alias']}.{n}" for n in dict.fromkeys(found)], ''


def main():
    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    sv._SEC = sel.sec
    store = sv.Store(rt)
    exp = json.loads((C4 / 'expectations_fixed.json').read_text(encoding='utf-8'))
    out = []
    for q in exp['questions']:
        qid = q['id']
        pool = sv.build_pool(rt, store, sel, q['question'])
        c4 = json.loads((C4 / 'candidates' / f'{qid}.json').read_text(encoding='utf-8'))
        a2c = {c['alias']: c['chunk_id'] for c in c4['candidates']}
        a2c.update({k: v['chunk_id'] if 'chunk_id' in v else k for k, v in c4['linked_passages'].items()} if False else {})
        a2c.update({v['alias']: k for k, v in c4['linked_passages'].items()})
        stems = sel.analyze(q['question'])['all_stems']
        for rd in sorted(p.name for p in (C4 / 'responses').iterdir()):
            f = C4 / 'responses' / rd / f'{qid}.json'
            if not f.exists():
                continue
            o = json.loads(json.loads(f.read_text(encoding='utf-8'))['raw_text'])
            loc, newprim, newsup = [], [], []
            qmap = {}
            for qt in o.get('quotes', []):
                cid = a2c.get(qt['id'])
                if cid is None or cid not in pool.by_chunk:
                    loc.append({'id': qt['id'], 'quote': qt['quote'][:70], 'class': 'unknown_candidate', 'spans': []})
                    continue
                cls, spans, why = locate(pool, store, cid, qt['quote'])
                loc.append({'id': qt['id'], 'quote': qt['quote'][:70], 'class': cls, 'spans': spans, 'why': why})
                qmap.setdefault(qt['id'], []).extend(spans)
            for pid in o.get('primary_ids', []):
                cid = a2c.get(pid)
                if cid is None or cid not in pool.by_chunk:
                    continue
                al = pool.by_chunk[cid]
                spans = qmap.get(pid, [])
                own = [s for s in spans if s.startswith(al + '.')]
                # 지지 줄: 인용이 다른 후보의 줄이면 그 줄을 대상 근거로 든 것으로 본다
                supp = []
                for s in spans:
                    term = next((t for t in stems if norm(t) in norm(next(x['text'] for x in pool.blocks[sv.parse_span(s)[0]]['lines'] if x['n'] == sv.parse_span(s)[1]))), None) or stems[0] if stems else ''
                    supp.append({'span': s, 'term': term})
                newprim.append({'candidate': al, 'rows': own, 'support': supp, 'why': ''})
            for sid in o.get('supporting_ids', []):
                cid = a2c.get(sid)
                if cid is None or cid not in pool.by_chunk:
                    continue
                al = pool.by_chunk[cid]
                newsup.append({'candidate': al, 'spans': [s for s in qmap.get(sid, []) if s.startswith(al + '.')], 'role': ''})
            resp = {'primary': newprim, 'supporting': newsup, 'competing': [], 'needed_references': [], 'ranking': [], 'missing': o.get('missing', []),
                    'advisory_status': o.get('evidence_status')}
            val = sv.validate_selection(pool, store, resp, stems)
            ids = list(dict.fromkeys([p['chunk_id'] for p in val['primary']] + [p['chunk_id'] for p in val['supporting']]))
            fr = sv.read_final(rt, sel, ids) if ids else {'units': {}, 'context': '', 'references': [], 'excluded': [], 'n_reads': 0}
            fin = sv.resolve_status(pool, store, val, fr, o.get('evidence_status'), o.get('missing') or [], [])
            req = set(q['required_chunks'])
            forb = set(q['forbidden_chunks'])
            out.append({'qid': qid, 'run': rd, 'c4_status': o.get('evidence_status'), 'c4_primary': [a2c.get(x) for x in o.get('primary_ids', [])],
                        'quote_location': loc, 'rejected': val['rejected'], 'dropped_primary': val['dropped_primary'],
                        'competing': val['competing'], 'primary_chunks': [p['chunk_id'] for p in val['primary']],
                        'supporting_chunks': [p['chunk_id'] for p in val['supporting']],
                        'support_kinds': [[s['kind'] + ':' + s['state'] for s in p['support']] for p in val['primary']],
                        'attribution': [[(a['stem'], a['state']) for a in p['attribution']] for p in val['primary']],
                        'new_status': fin['status'], 'reasons': [r['rule'] for r in fin['reasons']], 'allowed': q['allowed_status'],
                        'status_allowed': fin['status'] in q['allowed_status'],
                        'forbidden_primary': sorted(forb & {p['chunk_id'] for p in val['primary']}),
                        'required_in_validated': sorted(req & set(ids))})
    (HERE / 'replay_4c_results.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    # 검증기에 4c의 글 인용을 그대로 넣어(식별자 없이) 거부·복원 여부를 직접 본다
    direct = []
    for q in exp['questions']:
        qid = q['id']
        pool = sv.build_pool(rt, store, sel, q['question'])
        c4 = json.loads((C4 / 'candidates' / f'{qid}.json').read_text(encoding='utf-8'))
        a2c = {c['alias']: c['chunk_id'] for c in c4['candidates']}
        a2c.update({v['alias']: k for k, v in c4['linked_passages'].items()})
        stems = sel.analyze(q['question'])['all_stems']
        for rd in sorted(p.name for p in (C4 / 'responses').iterdir()):
            f = C4 / 'responses' / rd / f'{qid}.json'
            if not f.exists():
                continue
            o = json.loads(json.loads(f.read_text(encoding='utf-8'))['raw_text'])
            for qt in o.get('quotes', []):
                cid = a2c.get(qt['id'])
                if cid is None or cid not in pool.by_chunk:
                    continue
                al = pool.by_chunk[cid]
                v = sv.validate_selection(pool, store, {'supporting': [{'candidate': al, 'spans': [qt['quote']], 'role': 'quote'}], 'primary': [],
                                                        'competing': [], 'needed_references': [], 'ranking': []}, stems)
                sp = v['supporting'][0] if v['supporting'] else None
                direct.append({'qid': qid, 'run': rd, 'quote': qt['quote'][:80], 'accepted': bool(sp and sp['spans']),
                               'via': (sp['quotes'][0].get('resolved_via') if sp and sp['quotes'] else None),
                               'span': (sp['spans'][0] if sp and sp['spans'] else None), 'reject_reasons': [x['reason'] for x in v['rejected']]})
    (HERE / 'replay_4c_direct.json').write_text(json.dumps(direct, ensure_ascii=False, indent=1), encoding='utf-8')
    rt.close()
    sys.stdout.reconfigure(encoding='utf-8')
    for r in out:
        bad = [l for l in r['quote_location'] if l['class'] not in ('exact_span',)]
        print(r['qid'], r['run'], '4c:', r['c4_status'], '-> new:', r['new_status'], 'allowed' if r['status_allowed'] else 'NOT_ALLOWED', '| reasons', r['reasons'],
              '| forb_primary', r['forbidden_primary'], '| rejected', [(x['reason']) for x in r['rejected']], '| quotes', [(l['class']) for l in bad])


if __name__ == '__main__':
    main()
