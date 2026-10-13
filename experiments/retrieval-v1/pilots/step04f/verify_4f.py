"""4f 검증 도구: 질문 낱말 역할 구분·번호 범위 판정·대상 대조·부정 표지가 의도대로 동작하는지 가상 입력으로 확인한다.
(모델 호출 없음, 질문 임베딩 호출 없음(캐시된 벡터만), DB 읽기 전용, 결과는 step04f 폴더에만 기록)

  python -B verify_4f.py        # 결과: verify_4f_result.json, 통과/실패 목록

- 가상 응답은 사람이 만든 것이다. 선택·대조 의미의 정확성은 평가 결과로 따로 본다.
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
import select_verified as sv  # noqa: E402
import specs  # noqa: E402

SPECQ = {s['id']: s['question'] for s in specs.load_specs()}
DEV4E = json.loads((WORK / 'pilots/step04e/dev_cases_4e.json').read_text(encoding='utf-8'))
DEVQ = {c['id']: c['question'] for k in ('colloquial_normal', 'similar_no_data', 'number_only') for c in DEV4E[k]}
BASE = {'question_type': 'value', 'ranking': [], 'primary': [], 'supporting': [], 'needed_references': [], 'competing': [], 'missing': [],
        'list_scope': '', 'extra_lookup': {'kind': 'none', 'query': '', 'reason': ''}, 'advisory_status': 'supported', 'reason': ''}


class FakeCaller:
    """역할별로 정해 둔 응답을 돌려준다(없으면 호출 실패). 호출 횟수를 센다."""
    model, provider = 'fake', 'fake'

    def __init__(self, by_role=None):
        self.by_role, self.n = by_role or {}, {}

    def call(self, role, system, prompt, schema, qid=None, run_id=None):
        self.n[role] = self.n.get(role, 0) + 1
        r = self.by_role.get(role)
        if r is None:
            return {'ok': False, 'error': 'no_fake_response', 'attempts': 0, 'cost_usd': 0.0, 'cached': False, 'role': role}
        return {'ok': True, 'raw_text': json.dumps(r, ensure_ascii=False), 'cached': False, 'attempts': 0, 'cost_usd': 0.0, 'role': role}


def main():
    rt = rv.Retriever(embed_queries=False)
    vs0 = sv.VerifiedSelector(rt, FakeCaller())
    sel, store = vs0.sel, vs0.store
    res = []

    def check(name, ok, detail=None):
        res.append({'name': name, 'passed': bool(ok), 'detail': detail})

    def roles(q):
        return {r['surface']: r for r in vs0.question_roles(sel.analyze(q))}

    # ---------------- 1) 질문 낱말 역할
    r = roles('아스팔트 포장 150m를 절단하려는데 하루 시공량이 어떻게 돼?')['절단하려는데']
    check("'절단하려는데' → 작업 어간 '절단'(원문에 있음) + 요청 꼬리 '하려는데'", r['stem'] == '절단' and r['tail'] == '하려는데' and r['role'] == 'task' and r['present'], r)
    r = roles('철도 노선측량을 하려는데 근거가 어디 있어?')['하려는데']
    check("'하려는데'는 꼬리만 있는 요청 표현(대상 낱말이 아님)", r['role'] == 'request' and r['stem'] == '', r)
    r = roles('콘크리트 균열 보수 방법별로 어떤 품이 있어?')['방법별로']
    check("'방법별로'는 요청 표현(비교·목록 요청, '방법'은 일반 낱말)", r['role'] == 'request', r)
    r = roles('포크레인으로 터파기하면 하루에 몇 ㎥ 팔 수 있어?')['포크레인으로']
    check("원문에 없는 대상은 어간만 남긴다('포크레인으로' → '포크레인' + '으로', 부재 대상)", r['stem'] == '포크레인' and r['tail'] == '으로' and r['role'] == 'target' and not r['present'], r)
    r = roles('풍력 발전기 날개 교체하는 품은 얼마야?')
    check("꼬리로 나눌 수 없는 부재 낱말은 통째로 대상으로 남음('풍력')", r['풍력']['role'] == 'target' and not r['풍력']['present'], r['풍력'])
    r = roles('아스팔트 포장을 절삭하지 않고 덧씌우기만 하려면 품이 어떻게 돼?')
    check("부정 표현('않고')은 역할로 남고 활용형 '절삭하지'는 작업 어간 '절삭'을 유지", r['않고']['role'] == 'negation' and r['절삭하지']['stem'] == '절삭', [r['않고']['role'], r['절삭하지']])
    r = roles('6-1-3 몇 인이야?')
    check('절 번호는 number 역할', r['6-1-3']['role'] == 'number')
    r = roles('건축부문 6-1-3 일당 시공량')
    check("부문 표기는 division 역할", r['건축부문']['role'] == 'division')
    absent_all = {}
    for qid, q in {**SPECQ, **DEVQ}.items():
        absent_all[qid] = vs0.absent_terms(sel.analyze(q))
    check('V13·V18·V04의 요청 표현·활용형이 부재 대상에서 빠짐', not absent_all['V13'] and not absent_all['V18'] and not absent_all['V04'], {k: absent_all[k] for k in ('V13', 'V18', 'V04')})
    check('자료 없음 질문의 실제 부재 대상은 그대로 남음(N19 bim, 태양광, 풍력발전기, 포크레인, 아시바)',
          absent_all['N19'] == ['bim'] and absent_all['V19'] == ['태양광'] and absent_all['V20'] == ['풍력발전기'] and absent_all['E02'] == ['포크레인'] and absent_all['E03'] == ['아시바'],
          {k: absent_all[k] for k in ('N19', 'V19', 'V20', 'E02', 'E03')})
    spurious = {k: v for k, v in absent_all.items() if v and k not in ('N19', 'V19', 'V20', 'Q20', 'N20', 'E01', 'E02', 'E03', 'E04', 'E05', 'E06')}
    check('정상 질문 60문+개발 사례에서 위 자료 없음·부재 질문 밖에 낱말 부재가 새로 생기지 않음', not spurious, spurious)

    # ---------------- 2) 번호 범위
    def nl(q):
        x = vs0.number_lookup(q, sel.analyze(q))
        return None if x is None else {n: sorted({s['division'] for s in v}) for n, v in x['ambiguous'].items()}
    three = ['공통부문', '건축부문', '기계설비부문']
    check("'6-1-3 몇 인이야?' → 3개 부문 대안", nl('6-1-3 몇 인이야?') == {'6-1-3': sorted(three)})
    check("'6-1-3 일당 시공량은?' → 3개 부문 대안(일당·시공량은 요청 정보)", nl('6-1-3 일당 시공량은?') == {'6-1-3': sorted(three)})
    check("'6-1-3 기준이 뭐야' → 3개 부문 대안", nl('6-1-3 기준이 뭐야') == {'6-1-3': sorted(three)})
    x = nl('6-1-3과 6-1-4 품 알려줘')
    check('여러 번호: 번호마다 후보를 조회해 모호성을 각각 유지', x is not None and set(x) == {'6-1-3', '6-1-4'} and len(x['6-1-4']) == 2, x)
    check("'1-1-1 기준이 뭐야' → 5개 부문 대안", nl('1-1-1 기준이 뭐야') is not None and len(nl('1-1-1 기준이 뭐야')['1-1-1']) == 5)
    check('부문 명시 + 요청 표현 → 정상 경로', nl('건축부문 6-1-3 일당 시공량') is None)
    check("구별되는 제목('표면 마무리') + 요청 표현 → 정상 경로", nl('6-1-3 표면 마무리 일당 시공량') is None)
    check("제목에 흔한 일반 낱말('설치')은 부문을 가르지 못함 → 3개 부문 대안", nl('6-1-3 설치 품') == {'6-1-3': sorted(three)})
    check("한 번호의 한 부문만 구별 제목으로 좁혀지면 정상 경로('6-1-4 누름철물 설치')", nl('6-1-4 누름철물 설치 품') is None)
    check('같은 번호 절이 한 부문에만 있고 요청 표현이 붙은 질문은 정상 경로', nl('9-5-10 몇 인이야?') is None)
    check('색인에 없는 번호는 대안을 만들지 않음', nl('99-9-9 일당 시공량') is None)
    x = vs0.number_lookup('6-1-3 몇 인이야?', sel.analyze('6-1-3 몇 인이야?'))
    check('대안은 목차·상위 묶음이 아니라 본문 절이며 번호 형식을 일반 규칙으로 처리(번호 상수 없음)',
          all(sel.sec[s['section_id']]['level'] == 'section' for v in x['ambiguous'].values() for s in v))

    # ---------------- 3) 대상·작업 대조 (가상 응답)
    def run_n19(compare_resp, select_resp=None):
        q = SPECQ['N19']
        pool = sv.build_pool(rt, store, sel, q)
        cid = 't:full-p560-o81581#p1'
        al = pool.by_chunk[cid]
        sresp = select_resp or {**BASE, 'primary': [{'candidate': al, 'rows': [f'{al}.1'], 'support': [], 'why': ''}], 'ranking': [al]}
        cr = None if compare_resp is None else compare_resp(al, pool)
        fc = FakeCaller({'select': sresp, **({'target_compare': cr} if cr is not None else {})})
        vs = sv.VerifiedSelector(rt, fc, sel)
        out = vs.run(q, qid='v4f', fallback=False)
        return out, fc, al
    good = lambda al, pool: {'items': [{'candidate': al, 'verdict': 'different', 'span': f'{al}.1', 'reason': '다른 작업'}]}
    r, fc, al = run_n19(good)
    f = r['final']
    check('다른 대상·작업(유효한 줄 근거)이면 주·보조·확인용 문맥에서 제외하고 진단 후보로 보관, 상태 not_found(읽은 범위)',
          f['status'] == 'not_found' and not r['validated']['primary'] and not f['confirmed_chunks'] and not f['confirmation_only_chunks']
          and not r['final_context_chunks'] and r['target_excluded'] and any(x['rule'] == 'target_different' for x in f['reasons']),
          [f['status'], [x['rule'] for x in f['reasons']]])
    check('제외한 근거의 인용은 DB 글이고 판정은 참고용으로 표시', r['target_compare']['items'][0]['quote'] and f['target_compare']['note'].startswith('모델 판정은 참고용'))
    bad_span = lambda al, pool: {'items': [{'candidate': al, 'verdict': 'different', 'span': 'C99.1', 'reason': '다른 작업'}]}
    r, fc, al = run_n19(bad_span)
    check('반환 줄 식별자가 선택한 근거 안에 없으면 판정을 쓰지 않고(판단 불가) 제외하지 않음',
          r['final']['status'] == 'needs_confirmation' and r['validated']['primary'] and not r['target_excluded']
          and r['target_compare']['items'][0]['effective_verdict'] == 'cannot_judge', r['final']['status'])
    same = lambda al, pool: {'items': [{'candidate': al, 'verdict': 'same', 'span': f'{al}.1', 'reason': '같은 작업'}]}
    r, fc, al = run_n19(same)
    f = r['final']
    check("모델이 'same'이어도 원문으로 확인되지 않은 동등성은 확정으로 올리지 않음(확인 필요 + 확인용)",
          f['status'] == 'needs_confirmation' and not f['confirmed_chunks'] and f['confirmation_only_chunks'] and not r['target_excluded'], f['status'])
    cj = lambda al, pool: {'items': [{'candidate': al, 'verdict': 'cannot_judge', 'span': '', 'reason': '판단 불가'}]}
    r, fc, al = run_n19(cj)
    check('판단 불가이면 4e와 같이 확인 필요 + 확인용 + 부족한 대상 표시', r['final']['status'] == 'needs_confirmation' and r['final'].get('missing_targets') == ['bim'])
    r, fc, al = run_n19(None)
    check('대조 호출이 실패하면 4e 동작을 유지(확인 필요, 제외 없음)', r['final']['status'] == 'needs_confirmation' and not r['target_excluded'] and r['target_compare']['error'])
    r, fc, al = run_n19(lambda al, pool: {'items': [{'candidate': 'C98', 'verdict': 'different', 'span': 'C98.1', 'reason': 'x'}]})
    check('선택하지 않은 후보 별칭의 판정은 무시', not r['target_excluded'] and r['final']['status'] == 'needs_confirmation')
    # 동의어 확인된 정상 질문은 대조 호출을 하지 않음
    q = DEVQ['E01']
    pool = sv.build_pool(rt, store, sel, q)
    c = next(a for a, b in pool.blocks.items() if b['is_candidate'] and b['kind'] == 'table' and '굴착기' in sv.norm(' '.join(l['text'] for l in b['lines'])))
    fc = FakeCaller({'select': {**BASE, 'primary': [{'candidate': c, 'rows': [f'{c}.1'], 'support': [], 'why': ''}]}})
    r = sv.VerifiedSelector(rt, fc, sel).run(q, fallback=False)
    check('기존 동의어로 동등성이 확인된 정상 질문은 대조 호출을 하지 않음(호출 1회)', fc.n.get('target_compare', 0) == 0 and r['alias_confirmed'] == {'포클레인': '굴착기'}, fc.n)
    # 요청 표현만 있는 정상 질문은 낱말 부재로 보류하지 않음(V13 저장 응답 입력으로 같은 경로 확인)
    q = SPECQ['V13']
    pool = sv.build_pool(rt, store, sel, q)
    c = pool.by_chunk['t:full-p929-o135154']
    fc = FakeCaller({'select': {**BASE, 'primary': [{'candidate': c, 'rows': [f'{c}.1'], 'support': [], 'why': ''}]}})
    r = sv.VerifiedSelector(rt, fc, sel).run(q, fallback=False)
    check('V13: 요청 표현 때문에 target_term_unconfirmed로 보류하지 않음, 대조 호출 없음',
          not any(x['rule'] in ('target_term_unconfirmed', 'term_absent_in_corpus') for x in r['final']['reasons']) and fc.n.get('target_compare', 0) == 0
          and all(v == 'confirmed' for v in r['final']['evidence_roles'].values()), [x['rule'] for x in r['final']['reasons']])

    # ---------------- 4) 정적 검사
    src = (WORK / 'src/select_verified.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', src))
    pats = {'질문 ID': r"['\"][NVQEFGH]\d{2}['\"]", '조각 ID': r"['\"][trw]:(?:full-p|complete-|common|civil|arch|mech|maint)", '참조 ID': r"rel\d{3,}",
            '절 번호 상수': r"['\"]\d{1,2}-\d{1,2}-\d{1,2}['\"]", '질문 파일': r"new_questions|dev_questions|expected_|dev_cases",
            '실패 낱말(4c~4f)': r"병원건물|혼합토사|서양식|풍력|태양광|일반업무용|준설|도배|BIM|bim|정사영상|지상기준점|포크레인|포클레인|아시바|프린팅|농약|방제|절단하려|하려는데|방법별로"}
    hit = {k: re.findall(p_, code) for k, p_ in pats.items()}
    check('실행 코드·프롬프트에 질문 ID·조각 ID·절 번호 상수·실패 낱말·특정 활용형 예외를 직접 쓰지 않음', not any(hit.values()), {k: v[:3] for k, v in hit.items() if v})
    rt.close()
    out = {'passed': sum(c['passed'] for c in res), 'failed': sum(not c['passed'] for c in res),
           'note': '가상 입력 검사: 4f 변경이 의도대로 동작하는지 본다. 선택·대조 의미의 정확성은 평가 결과로 따로 본다.', 'checks': res}
    (HERE / 'verify_4f_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for c in res:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:240]}"))
    print(out['passed'], 'passed', out['failed'], 'failed')


if __name__ == '__main__':
    main()
