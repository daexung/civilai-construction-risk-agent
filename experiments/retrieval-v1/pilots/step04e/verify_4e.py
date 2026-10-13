"""4e 검증 도구: 가상 입력으로 번호 조회·인접 근거·동의어 확인·낱말 부재·확인용 문맥이 의도대로 동작하는지 확인한다.
(모델 호출 없음, 질문 임베딩 호출 없음(캐시된 벡터만), DB 읽기 전용, 결과는 step04e 폴더에만 기록)

  python -B verify_4e.py        # 결과: verify_4e_result.json, 통과/실패 목록

- 가상 응답은 사람이 만든 것이다. 선택 의미의 정확성(올바른 표를 골랐는가)은 평가 결과로 따로 본다.
- 4d의 위치·ID·버전·인용 검사(verify_4d.py, 26개)는 그 파일을 다시 실행하지 않고 같은 항목 일부만 새 코드로 다시 확인한다.
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'pilots/step04d'))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402
import select_verified as sv  # noqa: E402
import specs  # noqa: E402

DEV = json.loads((HERE / 'dev_cases_4e.json').read_text(encoding='utf-8'))
DEVQ = {c['id']: c['question'] for k in ('colloquial_normal', 'similar_no_data', 'number_only') for c in DEV[k]}
SPECQ = {s['id']: s['question'] for s in specs.load_specs()}


class FakeCaller:
    """모델 대신 정해 둔 응답을 돌려준다. 호출 횟수를 센다."""
    model, provider = 'fake', 'fake'

    def __init__(self, resp=None):
        self.resp, self.n = resp, 0

    def call(self, role, system, prompt, schema, qid=None, run_id=None):
        self.n += 1
        if self.resp is None:
            raise AssertionError('모델을 부르면 안 되는 경로에서 호출됨')
        return {'ok': True, 'raw_text': json.dumps(self.resp, ensure_ascii=False), 'cached': False, 'attempts': 0, 'cost_usd': 0.0, 'role': role}


BASE = {'question_type': 'value', 'ranking': [], 'primary': [], 'supporting': [], 'needed_references': [], 'competing': [], 'missing': [],
        'list_scope': '', 'extra_lookup': {'kind': 'none', 'query': '', 'reason': ''}, 'advisory_status': 'supported', 'reason': ''}


def main():
    rt = rv.Retriever(embed_queries=False)
    vs0 = sv.VerifiedSelector(rt, FakeCaller())
    sel, store = vs0.sel, vs0.store
    res = []

    def check(name, ok, detail=None):
        res.append({'name': name, 'passed': bool(ok), 'detail': detail})

    def run(question, resp):
        fc = FakeCaller(resp)
        vs = sv.VerifiedSelector(rt, fc, sel)
        return vs.run(question, qid='v4e', fallback=False), fc

    def pool_of(q):
        return sv.build_pool(rt, store, sel, q)

    def find(sub, kind=None):
        return [c for c, v in store.chunk.items() if sub in c and (kind is None or v['kind'] == kind)]

    # ---------------- 1) 번호만 있는 질문
    r, fc = run('6-1-3 품', None)
    divs = sorted({a['division'] for a in r.get('alternatives', [])})
    check('번호만 있는 질문: 구조 조회만으로 여러 부문 대안과 부문 선택 필요를 반환하고 모델을 부르지 않음',
          r['method'] == 'structural_number_lookup' and fc.n == 0 and r.get('division_choice_required') and len(divs) >= 3, divs)
    check('대안은 후보 범위일 뿐 정답·계산 적용 대상으로 표시하지 않음(applies unknown, 근거·최종 문맥 비어 있음)',
          all(a['applies'] == 'unknown' and a['role'] == 'candidate_scope' for a in r['alternatives']) and not r['validated']['primary']
          and not r['final_context_chunks'] and r['final']['status'] == 'needs_confirmation' and r['final']['applicability'] == 'unknown')
    check('대안은 목차·상위 묶음이 아니라 실제 본문 절(level=section)이고 절 색인에 있는 식별자',
          all(sel.sec[a['section_id']]['level'] == 'section' and a['title'] for a in r['alternatives']))
    r2, fc2 = run('1-1-1 품 알려줘', None)
    check('다른 번호의 모호한 사례도 일반 규칙으로 처리(부문 5개)', r2['method'] == 'structural_number_lookup' and fc2.n == 0
          and len({a['division'] for a in r2['alternatives']}) >= 4, sorted({a['division'] for a in r2['alternatives']}))
    an = sel.analyze('건축부문 6-1-3 품')
    check('부문을 명시한 질문은 대안 목록으로 되돌리지 않음(번호 조회 단락 없음)', vs0.number_lookup('건축부문 6-1-3 품', an) is None)
    an = sel.analyze('6-1-3 표면 마무리 품')
    check('번호에 구별되는 제목이 있으면 번호만 있는 질문이 아님(단락 없음)', vs0.number_lookup('6-1-3 표면 마무리 품', an) is None)
    one = next((n for n in sorted({x['number'] for x in sel.sec.values() if x['level'] == 'section'})
                if len({x['division'] for x in sel.sec.values() if x['level'] == 'section' and x['number'] == n}) == 1 and NUM_OK(n)), None)
    an = sel.analyze(f'{one} 품')
    check('한 부문에만 있는 번호는 대안 목록으로 단락하지 않음', one is not None and vs0.number_lookup(f'{one} 품', an) is None, one)
    an = sel.analyze('99-9-9 품')
    check('색인에 없는 번호는 대안을 만들지 않음', vs0.number_lookup('99-9-9 품', an) is None)

    # ---------------- 2) 위치 인접 근거
    p08 = pool_of(SPECQ['N08'])
    n_adj = n_far = 0
    adj_states = set()
    for b in p08.blocks.values():
        if b['kind'] != 'table' or b['chunk_id'] not in store.chunk:
            continue
        pv = store.prev_chunk(b['chunk_id'])
        for sb in p08.blocks.values():
            if sb['kind'] != 'rule' or sb is b:
                continue
            k, st, _ = sv.support_kind(store, p08, b, sb, 1)
            if k in ('adjacent_before', 'adjacent_after'):
                n_adj += 1
                adj_states.add(st)
            if k == 'unrelated':
                n_far += 1
    check('문서 순서상 바로 앞·뒤 설명은 위치 근거(미확정)로 인정되되 정상(clean)으로 올리지 않음', n_adj > 0 and adj_states == {'unconfirmed'}, [n_adj, sorted(adj_states)])
    check('인접하지도 연결되지도 않은 설명은 여전히 unrelated(거부)', n_far > 0, n_far)

    # ---------------- 3) 동의어 확인
    sel_text = sv.norm('굴착기의 시간당 작업량')
    ok, bad = vs0.alias_check(['포클레인'], sel_text)
    check('기존 동의어 규칙(포클레인→굴착기)은 선택 근거 글에 바꾼 낱말이 있을 때 확인됨', ok == {'포클레인': '굴착기'} and not bad, ok)
    ok, bad = vs0.alias_check(['포크레인'], sel_text)
    check('동의어 규칙에 없는 철자 변형은 확인하지 못함', not ok and bad == ['포크레인'], bad)
    ok, bad = vs0.alias_check(['포클레인'], sv.norm('불도저의 시간당 작업량'))
    check('바꾼 낱말이 선택한 근거 글에 없으면 동등성을 확인하지 않음', not ok and bad == ['포클레인'], bad)

    # ---------------- 4) 낱말 부재
    def sel_resp(pool, cand_pred, term_rows=1):
        c = next(a for a, b in pool.blocks.items() if b['is_candidate'] and b['kind'] == 'table' and cand_pred(b))
        return {**BASE, 'primary': [{'candidate': c, 'rows': [f'{c}.{term_rows}'], 'support': [], 'why': ''}], 'ranking': [c]}, c

    def has_excavator(b):
        return '굴착기' in sv.norm(' '.join(l['text'] for l in b['lines']))

    q02, q01 = DEVQ['E02'], DEVQ['E01']
    p02 = pool_of(q02)
    resp02, c02 = sel_resp(p02, has_excavator)
    r, fc = run(q02, resp02)
    f = r['final']
    check('낱말 부재만으로 검증된 주 근거를 비우거나 not_found로 바꾸지 않음(확인 필요 + 부족한 대상 표시)',
          bool(r['validated']['primary']) and f['status'] == 'needs_confirmation' and f.get('missing_targets') == r['absent_terms']
          and any(x['rule'] == 'target_term_unconfirmed' for x in f['reasons']), [f['status'], r['absent_terms']])
    check('동등성 미확인 근거는 확인용(confirmation_only)으로만 표시하고 확정 근거로 세지 않음',
          f['confirmed_chunks'] == [] and f['confirmation_only_chunks'] and all(v == 'confirmation_only' for v in f['evidence_roles'].values()))
    check('읽은 범위를 명시하고 문서 전체 부재를 단정하지 않음', all('문서 전체' in x.get('detail', '') or '읽은 범위' in x.get('detail', '')
                                                     for x in f['reasons'] if x['rule'] == 'target_term_unconfirmed'))
    p01 = pool_of(q01)
    resp01, c01 = sel_resp(p01, has_excavator)
    r, fc = run(q01, resp01)
    f = r['final']
    check('기존 동의어 규칙으로 동등성이 확인되면 확인용으로 낮추지 않고 alias_confirmed를 기록(거부 아님)',
          f['status'] != 'not_found' and list(r['alias_confirmed'].values()) == ['굴착기'] and all(k.startswith('포클레인') for k in r['alias_confirmed']) and any(x['rule'] == 'alias_confirmed' for x in f['reasons'])
          and not any(x['rule'] == 'target_term_unconfirmed' for x in f['reasons']), [f['status'], r['alias_confirmed']])
    # 자료 없음: 고른 근거가 없으면 not_found, 단 후보를 정상 근거로 보내지 않음
    q04 = DEVQ['E04']
    r, fc = run(q04, {**BASE, 'advisory_status': 'not_found'})
    f = r['final']
    check('자료 없음(근거 없음): not_found, 확정·확인용 근거 0, 최종 문맥 비어 있음, 읽은 범위 명시',
          f['status'] == 'not_found' and not f['confirmed_chunks'] and not f['confirmation_only_chunks'] and not r['final_context_chunks']
          and any('읽은 범위' in x.get('detail', '') for x in f['reasons']), [f['status'], [x['rule'] for x in f['reasons']]])
    p04 = pool_of(q04)
    c_any = next(a for a, b in p04.blocks.items() if b['is_candidate'] and b['kind'] == 'table')
    r, fc = run(q04, {**BASE, 'primary': [{'candidate': c_any, 'rows': [f'{c_any}.1'], 'support': [], 'why': ''}]})
    f = r['final']
    check('자료 없음 질문에서 모델이 관련 없는 후보를 골라도 정상 근거(확정)로 내보내지 않음', f['status'] != 'supported' and not f['confirmed_chunks'],
          [f['status'], f['confirmed_chunks']])

    # ---------------- 5) 확인용 문맥
    qn8 = SPECQ['N08']
    o86, o06 = find('o80886', 'table'), find('o80906', 'table')
    n85, n05, n76 = find('n80885', 'rule'), find('n80905', 'rule'), find('n80976', 'rule')
    sib = find('o80829', 'table') + find('n80855') + find('n80826')
    if o86 and n85:
        pn = pool_of(qn8)
        al = {c: a for a, b in pn.blocks.items() for c in [b['chunk_id']]}
        cands = [o86[0]] + ([o06[0]] if o06 and o06[0] in al else [])
        resp = {**BASE, 'primary': [{'candidate': al[c], 'rows': [f'{al[c]}.1'], 'support': [], 'why': ''} for c in cands if c in al], 'advisory_status': 'needs_confirmation'}
        r, fc = run(qn8, resp)
        cc = {c['chunk_id'] for c in r['confirmation_context']}
        ctx = set(r['final_context_chunks'])
        check('구조상 연결된 주석 표 설명·수식 미확정 조각을 확인용 문맥으로 보존(원문 읽기 가능)',
              any(c in cc for c in n85 + n05 + n76) and any(c in ctx for c in n85 + n05 + n76), sorted(cc))
        check('확인용 문맥을 확정 선택으로 올리지 않음(confirmed 역할이 아님)',
              not (cc & set(r['final']['confirmed_chunks'])) and not (cc & {p['chunk_id'] for p in r['validated']['primary'] + r['validated']['supporting']}))
        check('같은 소제목의 다른 대상 표·경쟁 표는 확인용 문맥에 섞지 않음', not (cc & set(sib)) and not (ctx & set(sib)), sorted(cc & set(sib)))
        check('수식 미확정 조각이 있으면 supported로 내보내지 않음', r['final']['status'] == 'needs_confirmation' and r['final']['applicability'] == 'unknown',
              [x['rule'] for x in r['final']['reasons']])
    else:
        check('N08 구조 식별 가능', False, [o86, n85])
    # V12: 일반업무용 표(다른 대상) 혼입 방지
    q12 = SPECQ['V12']
    p12 = pool_of(q12)
    t_hosp = next((a for a, b in p12.blocks.items() if b['chunk_id'].endswith('o4229')), None)
    t_other = next((b['chunk_id'] for a, b in p12.blocks.items() if 'p68-t0' in b['chunk_id']), None)
    if t_hosp:
        resp = {**BASE, 'primary': [{'candidate': t_hosp, 'rows': [f'{t_hosp}.1'], 'support': [], 'why': ''}], 'advisory_status': 'needs_confirmation'}
        r, fc = run(q12, resp)
        cc = {c['chunk_id'] for c in r['confirmation_context']}
        check('V12: 다른 대상(일반업무용) 표는 확인용 문맥·최종 문맥에 들어가지 않음', t_other is not None and t_other not in cc and t_other not in set(r['final_context_chunks']),
              [t_other, sorted(cc)])
    else:
        check('V12 병원 표를 후보에서 찾음', False)
    # 없는 식별자·잘못된 버전은 그대로 거부
    pp = pool_of(SPECQ['V09'])
    st = store
    stems = sel.analyze(SPECQ['V09'])['all_stems']
    t09 = next(a for a, b in pp.blocks.items() if b['is_candidate'] and b['kind'] == 'table')
    v = sv.validate_selection(pp, st, {**BASE, 'primary': [{'candidate': 'C99', 'rows': ['C99.1'], 'support': [], 'why': ''}]}, stems)
    check('목록에 없는 식별자는 그대로 거부', not v['primary'] and v['rejected'] and v['rejected'][0]['reason'] == 'unknown_candidate')
    v = sv.validate_selection(pp, st, {**BASE, 'primary': [{'candidate': t09, 'rows': [f'{t09}.1'], 'support': [], 'why': ''}]}, stems, fetch=lambda s, cid: 'changed')
    check('글이 달라진 버전은 그대로 거부', any(x['reason'] == 'version_mismatch' for x in v['rejected']) and not v['primary'])

    # ---------------- 6) 정적 검사
    src = (WORK / 'src/select_verified.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', src))
    pats = {'질문 ID': r"['\"][NVQEG]\d{2}['\"]", '조각 ID': r"['\"][trw]:(?:full-p|complete-|common|civil|arch|mech|maint)", '참조 ID': r"rel\d{3,}",
            '절 번호 상수': r"['\"]\d{1,2}-\d{1,2}-\d{1,2}['\"]", '질문 파일': r"new_questions|dev_questions|expected_|dev_cases",
            '실패 낱말(4c~4e)': r"병원건물|혼합토사|서양식|풍력|태양광|일반업무용|준설|도배|BIM|정사영상|지상기준점|포크레인|아시바|비계|굴착기"}
    hit = {k: re.findall(p_, code) for k, p_ in pats.items()}
    check('실행 코드·프롬프트에 질문 ID·조각 ID·절 번호 상수·실패 낱말을 직접 쓰지 않음(하드코딩 금지)', not any(hit.values()), {k: v[:3] for k, v in hit.items() if v})
    rt.close()
    out = {'passed': sum(c['passed'] for c in res), 'failed': sum(not c['passed'] for c in res),
           'note': '가상 입력 검사: 4e 변경이 의도대로 동작하는지 본다. 선택 의미의 정확성은 평가 결과로 따로 본다.', 'checks': res}
    (HERE / 'verify_4e_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for c in res:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:200]}"))
    print(out['passed'], 'passed', out['failed'], 'failed')


def NUM_OK(n):
    return bool(sv.NUM_RE.fullmatch(n))


if __name__ == '__main__':
    main()
