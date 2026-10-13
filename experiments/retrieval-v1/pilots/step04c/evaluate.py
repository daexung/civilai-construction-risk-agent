"""4c 평가: 고정한 기대값(expectations_fixed.json)과 저장된 응답(responses/)을 대조한다. 모델 호출 없음, DB 읽기 전용.

지표 정의(결과를 보기 전에 고정):
- 순위 지표: 모델 ranking(후보 별칭 C만, 앞에서 k개) 또는 검색 순서 또는 4b 선택 순서의 상위 k(1·3·5)에서
  필수 조각 포함 수 / 금지 조각 포함 수. 목록 질문은 상위 k 조각이 속한 절 중 필수 절 포함 수.
- 선택 집합(모델): primary_ids ∪ supporting_ids. 필수 누락, 금지 조각의 주 근거 포함, 절 단위 불필요·금지 절.
- 상태: 허용 상태 안인지, 정상 질문 거부(not_found), 자료 없음 정상 처리(not_found이고 주 근거 없음), 소속 미확정·부분 참조를 supported로 승격했는지.
- 최종 전달 문맥: 선택된 조각을 4b와 같은 설정(깊이 1, 예산 max(4000, 1200×개수), 셀 제외, 주석 표 후보 연결 제외, 표 앞 소제목 조각 추가)으로
  evidence.Reader에 넘겨 필수 조각이 유닛·문맥에 있는지 본다.
- 원인 분류(필수 조각별): candidate_miss(후보·연결 문맥에 없음) / linked_only(순위 후보는 아니고 연결 문맥에만 있음) /
  selection_miss(문맥에 있으나 선택 안 됨) / lookup_omission(선택됐으나 최종 문맥에 없음) / ok.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(HERE))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402
import llm_select as ls  # noqa: E402

PFX = 'pumsem-2026-errata1:'
NUM = re.compile(r'\d+(?:\.\d+)?')
ANNOT = re.compile(r'\s*\[공동값[^\]]*\]')
SKIP = ('note_table_candidate', 'note_table_owner_candidate')
B4_RESULTS = WORK / 'out/verification_runs/cs-37f81b5cfb1b-46f4f035c0fa/20261012T123241-eval_selection_new/new_selection_results.json'


def ws(s):
    return re.sub(r'\s+', '', s or '')


def read_final(rt, sel, ids):
    """4b와 같은 설정으로 선택 조각을 읽는다. 절별로 묶어 읽고 합친다."""
    by_sec = defaultdict(list)
    for cid in ids:
        if cid in rt.by_id:
            by_sec[rt.by_id[cid]['section_id']].append(cid)
    units, ctx, refs, excl = {}, '', [], []
    for sid, cids in by_sec.items():
        full = list(cids)
        for cid in cids:
            lab = sel._label_chunk(rt.pos[cid])
            if lab and lab not in full and rt.by_id[cid]['kind'] == 'table':
                full.append(lab)
        r = rt.reader.read(full, 1, max(4000, 1200 * len(full)), include_cells=False, skip_related=SKIP)
        for k, u in r['units'].items():
            units.setdefault(k, u)
        ctx += '\n' + r['answer_context']['text']
        refs += r['references']
        excl += r['excluded']
    return units, ctx, refs, excl


def final_checks(q, units, ctx, refs, excl):
    out = {'required_in_units': [c for c in q['required_chunks'] if c in units],
           'required_in_context': [c for c in q['required_chunks'] if f'[근거 {c}]' in ctx],
           'forbidden_in_units': [c for c in q['forbidden_chunks'] if c in units]}
    toks = set()
    for k, v in (q['expected_values'] or {}).items():
        if isinstance(v, str) and k != '조건':
            toks |= set(NUM.findall(v))
    out['value_tokens_missing'] = sorted(t for t in toks if t not in ctx) if toks else []
    rr = []
    for rf in q['required_references']:
        hit = [x for x in refs if x['edge_id'] == rf['edge_id']]
        rr.append({'edge_id': rf['edge_id'], 'found': bool(hit), 'ok': bool(hit) and hit[0]['target_status'] == rf['target_status'] and hit[0]['applicability'] == 'unknown'})
    out['required_references'] = rr
    st = {}
    for key in q['required_states']:
        if key in units:
            u = units[key]
            st[key] = bool((not u['normal_calculation_basis']) or any(w.get('link_state') not in (None, 'confirmed') for w in u['why_included']))
        else:
            hit = [x for x in refs if x['edge_id'] == key]
            st[key] = bool(hit) and hit[0]['target_status'] in ('partial', 'ambiguous')
    out['state_marked'] = st
    out['budget_excluded'] = sorted({c for e in excl if e['reason'] == 'budget' for c in e['chunk_ids']})
    return out


def topk(q, ranked, rt, ks=(1, 3, 5)):
    out = {}
    req, forb = set(q['required_chunks']), set(q['forbidden_chunks'])
    rs = {PFX + s for s in q['required_sections']}
    fs = {PFX + s for s in q['forbidden_sections']}
    for k in ks:
        top = ranked[:k]
        d = {'req_hit': len(req & set(top)), 'forb_hit': len(forb & set(top))}
        secs = {rt.by_id[c]['section_id'] for c in top if c in rt.by_id}
        if rs:
            d['req_sections_hit'] = len(rs & secs)
        d['forb_sections_hit'] = len(fs & secs)
        out[k] = d
    return out


def parse(rec, d):
    """응답 파싱과 코드 검증(별칭 존재, 인용이 원문에 있음)."""
    try:
        o = json.loads(rec['raw_text'])
    except Exception as e:
        return {'parse_ok': False, 'error': str(e)[:100]}
    alias = {c['alias']: c['chunk_id'] for c in d['candidates']}
    alias.update({v['alias']: k for k, v in d['linked_passages'].items()})
    text_of = {c['chunk_id']: c['text'] for c in d['candidates']}
    text_of.update({k: v['text'] for k, v in d['linked_passages'].items()})
    cand_alias = {c['alias'] for c in d['candidates']}
    inval = []

    def m(ids):
        out = []
        for a in ids:
            if a in alias:
                if alias[a] not in out:
                    out.append(alias[a])
            elif a in text_of:               # 실제 조각 ID를 그대로 쓴 경우도 후보 안에 있으면 받는다
                out.append(a)
            else:
                inval.append(a)
        return out
    rank_raw = o.get('ranking', [])
    rank = m([a for a in rank_raw if a in cand_alias or a in text_of])
    inval += [a for a in rank_raw if a not in alias and a not in text_of]
    ranking_noncand = [a for a in rank_raw if a in alias and a not in cand_alias]
    prim, sup = m(o.get('primary_ids', [])), m(o.get('supporting_ids', []))
    qn_ok = qn_bad = qn_tol = 0
    bad_q = []
    for qt in o.get('quotes', []):
        cid = alias.get(qt.get('id')) or (qt.get('id') if qt.get('id') in text_of else None)
        if cid and ws(qt.get('quote')) and ws(qt['quote']) in ws(text_of[cid]):
            qn_ok += 1
        elif cid and ws(qt.get('quote')) and ws(qt['quote']) in ws(ANNOT.sub('', text_of[cid])):
            qn_tol += 1                    # 인용이 [공동값 …] 주석 표기만 뺀 경우(값은 같음). 엄격 판정에서는 불일치로 센다
            qn_bad += 1
            bad_q.append({'id': qt.get('id'), 'quote': (qt.get('quote') or '')[:60], 'only_annotation_removed': True})
        else:
            qn_bad += 1
            bad_q.append({'id': qt.get('id'), 'quote': (qt.get('quote') or '')[:60]})
    return {'parse_ok': True, 'ranking': rank, 'primary': prim, 'supporting': [c for c in sup if c not in prim], 'status': o.get('evidence_status'),
            'needs_extra_lookup': o.get('needs_extra_lookup'), 'extra_lookup_requests': o.get('extra_lookup_requests', []),
            'missing': o.get('missing', []), 'status_reason': o.get('status_reason', ''),
            'invalid_ids': inval, 'ranking_non_candidate_aliases': ranking_noncand,
            'quotes': {'total': qn_ok + qn_bad, 'valid': qn_ok, 'invalid': bad_q, 'invalid_only_annotation_removed': qn_tol}}


def main():
    exp = json.loads((HERE / 'expectations_fixed.json').read_text(encoding='utf-8'))
    Q = {q['id']: q for q in exp['questions']}
    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    b4_rows = {r['id']: r for r in json.loads(B4_RESULTS.read_text(encoding='utf-8'))['rows']}
    est = json.loads((HERE / 'precall_estimate.json').read_text(encoding='utf-8'))
    results = {}
    for qid, q in Q.items():
        d = json.loads((HERE / 'candidates' / f'{qid}.json').read_text(encoding='utf-8'))
        cids = [c['chunk_id'] for c in d['candidates']]
        linked_only = {k for k, v in d['linked_passages'].items() if v['alias'].startswith('L')}
        dropped = {x['chunk_id'] for x in d['dropped_as_duplicate']}
        pool_secs = {c['section_id'] for c in d['candidates']}
        res = {'qid': qid, 'category': q['category'], 'role': q['pilot_role'], 'question': q['question'],
               'candidate_set_sha256': d['candidate_set_sha256'], 'context_sha256': est['questions'][qid]['context_sha256'],
               'prompt_sha256': est['questions'][qid]['prompt_sha256'],
               'n_candidates': len(cids), 'n_linked_only': len(linked_only)}
        res['presence'] = {c: ('candidate' if c in cids else 'linked_only' if c in linked_only else 'dropped_duplicate' if c in dropped else 'miss')
                           for c in q['required_chunks']}
        res['required_sections_in_pool'] = {s: (PFX + s) in pool_secs for s in q['required_sections']}
        res['forbidden_chunks_in_pool'] = [c for c in q['forbidden_chunks'] if c in cids]
        # 검색 순서(재순위 없음) 기준선
        res['search_order'] = topk(q, cids, rt)
        # 4b 원래 결과(저장된 독립 평가 행) + 선택 순서 재현
        b = b4_rows[qid]
        run = sel.run(q['question'])
        flat = []
        for e in run.get('evidence_sets', []):
            if e['role'] in ('primary', 'complement'):
                flat += [c['chunk_id'] for c in e['selected'] if c['chunk_id'] not in flat]
        res['b4_selected_outside_pool'] = [c for c in flat if c not in cids and c not in d['linked_passages']]
        res['b4'] = {'status': b['status'], 'status_reproduced': run['status'] == b['status'], 'intent': b['system_intent'],
                     'final_sections': [s.split(':', 1)[1] for s in b['final_sections']],
                     'alternatives': [s.split(':', 1)[1] for s in b['alternatives']],
                     'selected_order': flat, 'topk': topk(q, flat, rt) if flat else None,
                     'required_in_primary_selected': b['required_in_primary_selected'], 'required_in_units': b['required_in_units'],
                     'required_in_context': b['required_in_context'], 'forbidden_in_primary_selected': b['forbidden_in_primary_selected'],
                     'forbidden_in_units': b['forbidden_in_units'], 'forbidden_sections_in_final': b['forbidden_sections_in_final'],
                     'answer_recall_final': b.get('answer_recall_final'), 'all_answer_in_final': b.get('all_answer_in_final'),
                     'unneeded_sections': [s.split(':', 1)[1] for s in b.get('unneeded_sections', [])],
                     'state_marked': b.get('state_marked'), 'required_references': b.get('required_references'),
                     'no_data_correct': b.get('no_data_correct'), 'value_tokens_missing': b.get('value_tokens_missing')}
        # 검색 순서 상위 3개의 고정 예산 진단(재순위 상위 3 진단의 비모델 대응)
        if not q['is_list'] and not q['no_data']:
            u, ctx, refs, ex = read_final(rt, sel, cids[:3])
            res['search_top3_final'] = final_checks(q, u, ctx, refs, ex)
        # 모델 응답
        res['llm'] = {}
        for rid_dir in sorted((HERE / 'responses').iterdir()):
            f = rid_dir / f'{qid}.json'
            if not f.exists():
                continue
            rec = json.loads(f.read_text(encoding='utf-8'))
            L = {'run_id': rec['run_id'], 'ok': rec['ok'], 'attempts': rec['attempts'], 'latency_sec': rec['latency_sec'], 'cost_usd': rec['cost_usd'],
                 'usage': rec['usage_per_attempt'], 'model': rec['model'], 'provider': rec['provider']}
            if rec['ok']:
                p = parse(rec, d)
                L.update(p)
                if p['parse_ok']:
                    selset = list(dict.fromkeys(p['primary'] + p['supporting']))
                    req, forb = set(q['required_chunks']), set(q['forbidden_chunks'])
                    L['topk'] = topk(q, p['ranking'], rt)
                    L['required_missing_in_selected'] = sorted(req - set(selset))
                    L['required_missing_in_primary'] = sorted(req - set(p['primary']))
                    L['forbidden_in_primary'] = sorted(forb & set(p['primary']))
                    L['forbidden_in_supporting'] = sorted(forb & set(p['supporting']))
                    psecs = {rt.by_id[c]['section_id'] for c in p['primary'] if c in rt.by_id}
                    L['primary_sections'] = sorted(s.split(':', 1)[1] for s in psecs)
                    rs = {PFX + s for s in q['required_sections']}
                    if rs:
                        ok_s = {PFX + s for s in q['acceptable_sections']}
                        L['required_sections_covered'] = f"{len(rs & psecs)}/{len(rs)}"
                        L['required_sections_missing'] = sorted(s.split(':', 1)[1] for s in rs - psecs)
                        L['unneeded_sections'] = sorted(s.split(':', 1)[1] for s in psecs - rs - ok_s)
                        L['acceptable_sections_included'] = sorted(s.split(':', 1)[1] for s in psecs & ok_s)
                    if rs:
                        ssecs = {rt.by_id[c]['section_id'] for c in selset if c in rt.by_id}
                        L['required_sections_covered_selected_set'] = f"{len(rs & ssecs)}/{len(rs)}"
                        L['required_sections_missing_selected_set'] = sorted(x.split(':', 1)[1] for x in rs - ssecs)
                        L['unneeded_sections_selected_set'] = sorted(x.split(':', 1)[1] for x in ssecs - rs - ok_s)
                    L['forbidden_sections_in_primary'] = sorted(s.split(':', 1)[1] for s in psecs & {PFX + s for s in q['forbidden_sections']})
                    L['status_allowed'] = p['status'] in q['allowed_status']
                    L['normal_rejected'] = (not q['no_data']) and p['status'] == 'not_found'
                    if q['no_data']:
                        L['no_data_correct'] = p['status'] == 'not_found' and not p['primary']
                        L['no_data_leak'] = not L['no_data_correct']
                    L['promoted_unconfirmed'] = bool(q['hold'] and p['status'] == 'supported')
                    if not q['is_list'] and not q['no_data'] and p['status'] != 'not_found':
                        u, ctx, refs, ex = read_final(rt, sel, selset)
                        L['final'] = final_checks(q, u, ctx, refs, ex)
                    # 필수 조각별 원인 분류
                    cause = {}
                    for c in q['required_chunks']:
                        pres = res['presence'][c]
                        if c in selset:
                            fin = L.get('final')
                            cause[c] = 'ok' if (fin is None or c in fin['required_in_context']) else 'lookup_omission'
                        else:
                            fin = L.get('final')
                            if fin is not None and c in fin['required_in_context']:
                                cause[c] = 'not_selected_but_reached_by_lookup'     # 선택 집합엔 없지만 구조 연결 조회로 최종 문맥에 들어옴
                            else:
                                cause[c] = 'candidate_miss' if pres == 'miss' else ('linked_only' if pres == 'linked_only' else 'selection_miss')
                    L['cause_by_required'] = cause
            res['llm'][rec['run_id']] = L
        results[qid] = res
    rt.close()
    # 반복 변동
    for qid in ('V09', 'V11', 'V12', 'V20'):
        runs = results[qid]['llm']
        keys = sorted(runs)
        sig = lambda r: (r.get('status'), tuple(sorted(r.get('primary', []))), tuple(sorted(r.get('supporting', []))))
        results[qid]['repeat'] = {'runs': keys, 'identical_status': len({runs[k].get('status') for k in keys}) == 1,
                                  'identical_primary': len({tuple(sorted(runs[k].get('primary', []))) for k in keys}) == 1,
                                  'identical_selected_set': len({sig(runs[k]) for k in keys}) == 1,
                                  'identical_top5': len({tuple(runs[k].get('ranking', [])[:5]) for k in keys}) == 1}
    (HERE / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    print('saved results.json')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
