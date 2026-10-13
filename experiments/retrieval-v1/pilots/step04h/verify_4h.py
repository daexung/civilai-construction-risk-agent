"""4h 검증 도구: 질문 원문 보존·대조 결과의 권한·구조 보존·목록 완전성 의미가 의도대로 동작하는지 가상 입력으로 확인한다.
(모델 호출 없음, 질문 임베딩 호출 없음(캐시된 벡터만), DB 읽기 전용, 결과는 step04h 폴더에만 기록)

  python -B verify_4h.py
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
G = {q['id']: q['question'] for q in json.loads((WORK / 'eval/questions_04g_2026-10-12.json').read_text(encoding='utf-8'))['questions']}
BASE = {'question_type': 'value', 'ranking': [], 'primary': [], 'supporting': [], 'needed_references': [], 'competing': [], 'missing': [],
        'list_scope': '', 'extra_lookup': {'kind': 'none', 'query': '', 'reason': ''}, 'advisory_status': 'supported', 'reason': ''}


class FakeCaller:
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

    def run(q, by_role):
        fc = FakeCaller(by_role)
        return sv.VerifiedSelector(rt, fc, sel).run(q, qid='v4h', fallback=False), fc

    def roles(q):
        return {r['surface']: r for r in vs0.question_roles(sel.analyze(q))}

    def ev(q, text):
        return vs0.absent_terms(sel.analyze(q), text)

    # ---- 1) 질문 원문·약한 분석
    r = roles(G['G03'])
    check('규격 연결 표현 `짜리`는 수치·단위 바로 뒤 위치로 요청 역할(spec_connector)을 받고 부재 후보가 아님',
          r['짜리']['role'] == 'spec_connector' and not r['짜리']['absent_candidate'], r['짜리'])
    check('원래 어절이 그대로 남는다(surface) — 잘린 어간은 약한 분석(analysis_confidence=weak)으로만 기록',
          roles('절단하려는데 품이 어떻게 돼?')['절단하려는데']['surface'] == '절단하려는데' and roles('절단하려는데 품이 어떻게 돼?')['절단하려는데']['analysis_confidence'] == 'weak')
    q9 = G['G09']
    ab = ev(q9, None)
    check('`호퍼스케일`은 잘린 `호퍼스케`가 아니라 원래 어절로 기록', '호퍼스케일' in ab and '호퍼스케' not in ab, ab)
    check('G03·G10의 `짜리`는 부재 대상이 되지 않음', '짜리' not in ev(G['G03'], None) and '짜리' not in ev(G['G10'], None))
    check('약한 분석의 앞부분이 직접 선택한 근거 글에 있으면 부재 대상으로 보지 않음(`절단하려는데` ↔ 근거의 `절단`)',
          ev('아스팔트 포장 150m를 절단하려는데 하루 시공량이 어떻게 돼?', sv.norm('아스팔트 포장 절단 시공량 인')) == [] and
          ev('아스팔트 포장 150m를 절단하려는데 하루 시공량이 어떻게 돼?', sv.norm('콘크리트 타설 시공량')) == ['절단하려는데'])
    check('원문에 실제로 없는 대상은 그대로 부재(광케이블, bim, 포클레인 표기)',
          [x.startswith('광케이블') for x in ev(G['G15'], None)] == [True] and ev(SPECQ['N19'], None) == ['bim'])
    check('부정·작업·단위는 지우지 않음(부정 `않고`, 작업 `절삭하지`)',
          roles('아스팔트 포장을 절삭하지 않고 덧씌우기만 하려면 품이 어떻게 돼?')['않고']['role'] == 'negation' and
          roles('아스팔트 포장을 절삭하지 않고 덧씌우기만 하려면 품이 어떻게 돼?')['절삭하지']['role'] == 'task')

    # ---- 2) 대조 모델의 권한 제거
    def run_g(qid, sel_chunks, compare):
        q = G[qid]
        pool = sv.build_pool(rt, store, sel, q)
        prim = []
        for c in sel_chunks:
            al = pool.by_chunk[c]
            prim.append({'candidate': al, 'rows': [f'{al}.1'], 'support': [], 'why': ''})
        resp = {**BASE, 'primary': prim}
        by = {'select': resp}
        if compare:
            by['target_compare'] = compare(pool)
        return run(q, by), pool

    # G03: 잘못된 대조 응답을 줄 식별자 형식이 아니라 후보 별칭 형식으로 바꾼 입력(정답 표를 'different'로 판정)
    def g03_bad(pool):
        al = pool.by_chunk['t:full-p978-o141173']
        return {'items': [{'candidate': al, 'verdict': 'different', 'span': f'{al}.1', 'reason': '철판 두께와 규격이 일치하지 않는다.'}]}
    # 4g 질문 G03은 `짜리`가 부재 대상이 아니므로 대조가 안 일어난다. 대조를 일으키는 입력(원문에 없는 낱말 추가)으로 같은 경로를 시험한다
    q_force = G['G03'] + ' 비엠'
    pool = sv.build_pool(rt, store, sel, G['G03']) if False else None
    # 질문 벡터 캐시가 없는 새 질문은 쓰지 않는다. 대조 경로는 G09(호퍼스케일) 입력으로 시험한다
    (r, fc), pool = run_g('G09', ['complete-82c206c61e21:full-p776:n109525#0', 't:full-p775-o109468'] if False else ['r:complete-82c206c61e21:full-p776:n109525#0', 't:full-p775-o109468'],
                          lambda pl: {'items': [{'candidate': pl.by_chunk['t:full-p775-o109468'], 'verdict': 'different', 'span': pl.by_chunk['t:full-p775-o109468'] + '.1',
                                                 'reason': '다른 작업'}]})
    f = r['final']
    check('대조가 `different`(유효한 줄)라도 선택한 표·설명을 제외하지 않는다(주·보조 유지, 자동 not_found 아님)',
          f['status'] != 'not_found' and len(r['validated']['primary']) == 2 and not r['target_excluded'] and r['target_compare']['authority'] == 'advisory_only', f['status'])
    check('대조 경고는 사유·원문 위치와 함께 기록되고 supported로 승격하지 않는다',
          any(x['rule'] == 'target_mismatch_warning' for x in f['reasons']) and f['status'] == 'needs_confirmation' and r['target_compare']['warnings'], [x['rule'] for x in f['reasons']])
    # 후보 식별자 형식이 줄 식별자 형태('C07.1')여도 결과가 같다
    (r2, fc2), pool2 = run_g('G09', ['r:complete-82c206c61e21:full-p776:n109525#0', 't:full-p775-o109468'],
                             lambda pl: {'items': [{'candidate': pl.by_chunk['t:full-p775-o109468'] + '.1', 'verdict': 'different', 'span': pl.by_chunk['t:full-p775-o109468'] + '.1',
                                                    'reason': '다른 작업'}]})
    check('판정 후보 식별자가 `C07.1` 형식이어도 같은 결과(형식 오류가 결과를 바꾸지 않음)',
          [x['rule'] for x in r2['final']['reasons']] == [x['rule'] for x in r['final']['reasons']] and len(r2['validated']['primary']) == 2 and
          r2['target_compare']['warnings'] and r['final']['status'] == r2['final']['status'])
    (r3, _), _ = run_g('G09', ['r:complete-82c206c61e21:full-p776:n109525#0', 't:full-p775-o109468'],
                       lambda pl: {'items': [{'candidate': pl.by_chunk['t:full-p775-o109468'], 'verdict': 'same', 'span': pl.by_chunk['t:full-p775-o109468'] + '.1', 'reason': '같음'}]})
    check("대조 `same`은 소속 미확정 보류를 해제하지 않음(needs_confirmation 유지, 확정 선택 0)", r3['final']['status'] == 'needs_confirmation' and not r3['final']['confirmed_chunks'])
    (r4, _), _ = run_g('G09', ['r:complete-82c206c61e21:full-p776:n109525#0'], None)
    check('대조 호출 실패·없음이어도 근거를 잃지 않음(4e 동작)', r4['final']['status'] == 'needs_confirmation' and len(r4['validated']['primary']) == 1)

    # ---- 3) 유효하지 않은 ID·버전은 계속 거부
    pool = sv.build_pool(rt, store, sel, G['G07'])
    stems = sel.analyze(G['G07'])['all_stems']
    v = sv.validate_selection(pool, store, {**BASE, 'primary': [{'candidate': 'C99', 'rows': ['C99.1'], 'support': [], 'why': ''}]}, stems)
    check('없는 후보 식별자는 계속 거부', not v['primary'] and v['rejected'])
    al = pool.by_chunk['r:complete-82c206c61e21:full-p729:n103599#0']
    v = sv.validate_selection(pool, store, {**BASE, 'primary': [{'candidate': al, 'rows': [f'{al}.1'], 'support': [], 'why': ''}]}, stems, fetch=lambda s_, c: 'changed')
    check('글이 달라진 버전은 계속 거부', any(x['reason'] == 'version_mismatch' for x in v['rejected']) and not v['primary'])

    # ---- 4) 설명에서 필요한 표를 구조로 조회
    (r5, _), _ = run_g('G09', ['r:complete-82c206c61e21:full-p776:n109525#0'], None)
    ctx = set(r5['final_context_chunks'])
    check('설명만 선택해도 인접 설명 연쇄가 닿는 표·비고가 검토용 원문으로 전달됨(모델 보조 선택 불필요)',
          't:full-p775-o109468' in ctx and 'r:complete-82c206c61e21:full-p776:n109522#0' in ctx and 't:full-p775-o109468' in r5['final']['review_chunks'], sorted(c.split(':')[-1] for c in ctx))
    check('검토용 원문은 정상 답변 근거에 들어가지 않고 미확정 설명은 확정으로 올라가지 않음',
          not (set(r5['final']['review_chunks']) & set(r5['final']['answer_evidence_chunks'])) and not r5['final']['confirmed_chunks'] and r5['final']['status'] == 'needs_confirmation')
    check('같은 절의 다른 표를 모두 더하지 않음(검토용 보존 조각 ≤ 인접 연쇄 2 + 표 1)', len(r5['retained_review']) <= 3, len(r5['retained_review']))
    (r6, _), _ = run_g('G10', ['r:complete-82c206c61e21:full-p150:n13876#0'], None)
    check('G10: 조건 규칙만 선택해도 기준 표가 읽힘(기존 related_table 조회)', 't:full-p149-o13841' in set(r6['final_context_chunks']))

    # ---- 5) 정적 검사
    src = (WORK / 'src/select_verified.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', src))
    pats = {'질문 ID': r"['\"][NVQEFGH]\d{2}['\"]", '조각 ID': r"['\"][trw]:(?:full-p|complete-|common|civil|arch|mech|maint)", '참조 ID': r"rel\d{3,}",
            '절 번호 상수': r"['\"]\d{1,2}-\d{1,2}-\d{1,2}['\"]", '질문 파일': r"new_questions|dev_questions|expected_|dev_cases|questions_04g",
            '실패 낱말': r"병원건물|혼합토사|서양식|풍력|태양광|일반업무용|준설|도배|BIM|bim|정사영상|포크레인|포클레인|아시바|프린팅|농약|방제|호퍼|스케일|짜리|절단하려|하려는데|방법별로|계량기|송풍기"}
    hit = {k: re.findall(p_, code) for k, p_ in pats.items()}
    check('실행 코드·프롬프트에 질문 ID·조각 ID·절 번호 상수·실패 낱말을 직접 쓰지 않음(정답 ID 삽입 금지)', not any(hit.values()), {k: v_[:3] for k, v_ in hit.items() if v_})
    rt.close()
    out = {'passed': sum(c['passed'] for c in res), 'failed': sum(not c['passed'] for c in res), 'checks': res,
           'note': '가상 입력 검사: 4h 변경이 의도대로 동작하는지 본다. 의미 정확성은 평가 결과로 따로 본다.'}
    (HERE / 'verify_4h_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for c in res:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:240]}"))
    print(out['passed'], 'passed', out['failed'], 'failed')


if __name__ == '__main__':
    main()
