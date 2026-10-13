"""4d 검증 도구: 가상 입력으로 원문 위치·관계·상태 검증이 동작하는지 확인한다(모델 호출 없음, DB 읽기 전용).

  python -B verify_4d.py        # 결과: verify_4d_result.json, 통과/실패 목록

- 이 검사는 '검증 코드가 잘못된 입력을 막는가'를 보는 것이다. 선택 의미의 정확성(올바른 표를 골랐는가)은 평가 결과(evaluate_4d.py)로 따로 본다.
- 실제 질문의 후보 풀(V12·V17·V09·V15)에 모델 응답을 사람이 만든 가상 응답으로 바꿔 끼워 넣는다.
"""
import json
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402
import select_verified as sv  # noqa: E402

Q = {
    'V12': '병원건물에서 강관 배관재의 관이음부속과 관지지물 금액 비율은 얼마야? 냉온수배관 기계실 기준으로.',
    'V17': '터널 발파굴착에서 B군일 때 1발파당 작업인원과 B군은 어떤 경우인지 알려줘',
    'V09': '흙깎기(기계) 작업에서 혼합토사 대규모일 때 불도저 32ton의 일당 시공량이 얼마야?',
    'V15': '도로 연약지반에 육상으로 토목섬유 매트를 깔 때 하루에 몇 ㎡ 깔 수 있어?',
}


def alias(pool, chunk_id):
    return pool.by_chunk[chunk_id]


def main():
    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    sv._SEC = sel.sec
    store = sv.Store(rt)
    pools = {k: sv.build_pool(rt, store, sel, q) for k, q in Q.items()}
    stems = {k: sel.analyze(q)['all_stems'] for k, q in Q.items()}
    res = []

    def check(name, ok, detail=None):
        res.append({'name': name, 'passed': bool(ok), 'detail': detail})

    def val(k, resp, fetch=None):
        v = sv.validate_selection(pools[k], store, resp, stems[k], **({'fetch': fetch} if fetch else {}))
        return v

    def final(k, v, advisory=None, missing=()):
        ids = list(dict.fromkeys([p['chunk_id'] for p in v['primary']] + [p['chunk_id'] for p in v['supporting']]))
        fr = sv.read_final(rt, sel, ids) if ids else {'units': {}, 'context': '', 'references': [], 'excluded': [], 'n_reads': 0}
        return sv.resolve_status(pools[k], store, v, fr, advisory, list(missing), [])

    base = {'primary': [], 'supporting': [], 'competing': [], 'needed_references': [], 'ranking': [], 'missing': [], 'advisory_status': 'supported'}

    # ---- 위치·ID 검증
    p12 = pools['V12']
    c3, c1 = alias(p12, 't:full-p69-o4229'), alias(p12, 't:full-p68-ocorrection:p68-t0')
    v = val('V12', {**base, 'primary': [{'candidate': 'C99', 'rows': ['C99.1'], 'support': [], 'why': ''}]})
    check('목록에 없는 후보 별칭은 거부', v['rejected'] and v['rejected'][0]['reason'] == 'unknown_candidate' and not v['primary'])
    v = val('V12', {**base, 'primary': [{'candidate': c3, 'rows': [f'{c3}.99'], 'support': [], 'why': ''}]})
    check('범위를 벗어난 줄 식별자는 거부하고 필요한 행이 없어졌음을 상태에 반영',
          any(x['reason'] == 'span_out_of_range' for x in v['rejected']) and v['primary'] and v['primary'][0]['rows_rejected'])
    f = final('V12', v, 'supported')
    check('행 식별자가 모두 거부되면 supported로 내보내지 않음', f['status'] != 'supported' and any(r['rule'] == 'rows_rejected' for r in f['reasons']), f['status'])
    v = val('V12', {**base, 'primary': [{'candidate': c3, 'rows': [f'{c1}.1'], 'support': [], 'why': ''}]})
    check('다른 후보의 줄을 이 후보의 행으로 쓰면 거부', any(x['reason'] == 'span_not_in_candidate' for x in v['rejected']))
    v = val('V12', {**base, 'primary': [{'candidate': c3, 'rows': [f'{c3}.1 그리고 {c3}.2'], 'support': [], 'why': ''}]})
    check('한 문자열 안의 식별자 여러 개는 각각 별도 줄로 읽음(합치지 않음)', len(v['primary'][0]['quotes']) == 2 and
          v['primary'][0]['quotes'][0]['span_id'] != v['primary'][0]['quotes'][1]['span_id'])
    # ---- 버전
    v = val('V12', {**base, 'primary': [{'candidate': c3, 'rows': [f'{c3}.1'], 'support': [], 'why': ''}]}, fetch=lambda s, cid: 'changed text')
    f = final('V12', v, 'supported')
    check('선택 시점과 글이 다르면(버전 불일치) 거부하고 supported로 내보내지 않음',
          any(x['reason'] == 'version_mismatch' for x in v['rejected']) and f['status'] != 'supported', f['status'])
    fake = types.SimpleNamespace(conn=rt.conn, reader=types.SimpleNamespace(rid='rk-other-release'))
    try:
        sv.Store(fake)
        ok = False
    except AssertionError:
        ok = True
    check('다른 원문 릴리스에서는 저장소를 열지 않음(버전 고정)', ok)
    # ---- 인용은 코드가 가져옴
    t09 = alias(pools['V09'], 't:full-p124-o10583')
    v = val('V09', {**base, 'primary': [{'candidate': t09, 'rows': [f'{t09}.1'], 'support': [], 'why': ''}]})
    q = v['primary'][0]['quotes'][0]
    check('표 값 인용에 행 이름·열 머리글·기준(단위)·절이 함께 옴', q['row_label'] and q['column_header'] and q['unit_basis'] and q['section'], {k: q[k] for k in ('row_label', 'unit_basis')})
    check('공동값 표지가 인용에 그대로 남음', q['shared_value_marker'] and '[공동값' in q['text'])
    p15 = pools['V15']
    t15 = alias(p15, 't:full-p165-o15940')
    v = val('V15', {**base, 'primary': [{'candidate': t15, 'rows': [f'{t15}.1', f'{t15}.3'], 'support': [], 'why': ''}]})
    check('떨어진 두 행은 각각의 원문으로 표시(하나의 인용으로 합치지 않음)', len(v['primary'][0]['quotes']) == 2 and
          v['primary'][0]['quotes'][0]['text'] != v['primary'][0]['quotes'][1]['text'])
    # 4c 인용 불일치 4건과 같은 유형의 글 인용(식별자 없이 글만 준 경우)
    line = p15.blocks[t15]['lines'][0]['text']
    stripped = sv.re.sub(r'\s*\[공동값[^\]]*\]', '', line)
    v = val('V15', {**base, 'primary': [{'candidate': t15, 'rows': [stripped], 'support': [], 'why': ''}]})
    check('4c 유형1: 공동값 표지를 뺀 글 인용은 위치로 되돌리지 않고 거부', not v['primary'][0]['rows'] and any(x['reason'] == 'unknown_span' for x in v['rejected']))
    v = val('V15', {**base, 'primary': [{'candidate': t15, 'rows': [line], 'support': [], 'why': ''}]})
    check('원문 줄을 글자 그대로 준 경우에만 글 포인터로 위치를 찾고 DB 글을 인용', v['primary'][0]['rows'] and
          v['primary'][0]['quotes'][0]['resolved_via'] == 'text_pointer' and v['primary'][0]['quotes'][0]['text'] == line)
    l1, l2 = p15.blocks[t15]['lines'][0]['text'], p15.blocks[t15]['lines'][-1]['text']
    v = val('V15', {**base, 'primary': [{'candidate': t15, 'rows': [l1[:30] + ' ... ' + l2[-30:]], 'support': [], 'why': ''}]})
    check('4c 유형3: 떨어진 두 구간을 이어 붙인 글 인용은 거부', not v['primary'][0]['rows'])
    c2 = alias(p12, 'r:complete-82c206c61e21:full-p69:n4313#0')
    c4 = alias(p12, 'r:complete-82c206c61e21:full-p68:n4211#0')
    txt_other = p12.blocks[c2]['lines'][0]['text']
    v = val('V12', {**base, 'supporting': [{'candidate': c4, 'spans': [txt_other], 'role': 'x'}]})
    check('4c 유형2: 다른 조각의 문장을 이 후보의 인용으로 옮기면 거부', v['supporting'] and not v['supporting'][0]['spans'] and v['supporting'][0]['spans_rejected'])
    p17 = pools['V17']
    r17 = alias(p17, 't:full-p397-o53599')
    row = p17.blocks[r17]['lines'][-1]['text']
    parts = row.split(' | ')
    skipped = ' | '.join([parts[0], parts[1], parts[3]]) if len(parts) > 3 else row[:20] + row[-10:]
    v = val('V17', {**base, 'primary': [{'candidate': r17, 'rows': [skipped], 'support': [], 'why': ''}]})
    check('4c 유형4: 열을 건너뛰고 이어 쓴 표 행 글은 거부', not v['primary'][0]['rows'])
    # ---- 관계·방향
    t4 = alias(p12, 'r:complete-82c206c61e21:full-p68:n4211#0')
    v = val('V12', {**base, 'primary': [{'candidate': c1, 'rows': [f'{c1}.1'], 'support': [{'span': f'{t4}.10', 'term': '병원건물'}], 'why': ''}]})
    check('다른 표의 제목 줄을 이 표의 대상 근거로 든 선택은 주 근거에서 제외하고 경쟁 후보로 이동',
          not v['primary'] and any(x['reason'] == 'other_table_title' for x in v['rejected']) and v['competing'], [x['reason'] for x in v['rejected']])
    f = final('V12', v, 'supported')
    check('대상이 다른 표만 고른 경우 supported도 not_found도 아닌 확인 필요(경쟁 후보 반환)', f['status'] == 'needs_confirmation', f['status'])
    # 모델이 supported를 주장해도 소속 미확정에 기대면 올리지 않음
    v = val('V12', {**base, 'primary': [{'candidate': c3, 'rows': [f'{c3}.1'], 'support': [{'span': f'{t4}.10', 'term': '병원건물'}], 'why': ''}],
                    'supporting': [{'candidate': c2, 'spans': [f'{c2}.1'], 'role': 'definition'}]})
    f = final('V12', v, 'supported')
    check('모델 supported + 소속 미확정 설명·소유 경쟁 제목 줄 → 최종 needs_confirmation', f['status'] == 'needs_confirmation' and
          {'unconfirmed_chunk', 'attribution_unconfirmed'} <= {r['rule'] for r in f['reasons']}, [r['rule'] for r in f['reasons']])
    check('올바른 표(병원)를 주 근거로 두고 경쟁 표를 따로 둘 수 있음', v['primary'] and v['primary'][0]['chunk_id'] == 't:full-p69-o4229')
    # 모델이 설명 끝 제목 줄을 근거로 인용했는지(C04 줄 10)와 표의 방향
    tl = v['primary'][0]['title_lines']
    check('표 앞 제목 줄이 코드가 가져온 원문 줄로 전달되고 다른 표의 주석 기록(소유 경쟁)이 표시됨',
          any('병원건물' in x['text'] and x['claimed_by_other_tables'] for x in tl), [x['text'] for x in tl])
    # V17 부분 참조
    t53599 = alias(p17, 't:full-p397-o53599')
    t53561 = alias(p17, 't:full-p397-o53561')
    v = val('V17', {**base, 'primary': [{'candidate': t53599, 'rows': [f'{t53599}.3'], 'support': [], 'why': ''},
                                       {'candidate': t53561, 'rows': [], 'support': [], 'why': ''}]})
    f = final('V17', v, 'supported')
    check('모델 supported + 부분 참조의 대상을 근거로 쓰면 → needs_confirmation(참조 상태 별도 필드)',
          f['status'] == 'needs_confirmation' and any(x['target_status'] == 'partial' for x in f['reference_states']) and f['applicability'] == 'unknown',
          [r['rule'] for r in f['reasons']])
    v = val('V17', {**base, 'primary': [{'candidate': t53599, 'rows': [f'{t53599}.3'], 'support': [], 'why': ''}], 'needed_references': ['R99']})
    check('목록에 없는 참조 식별자는 거부', any(x['reason'] == 'unknown_reference' for x in v['rejected']))
    # 필요하지 않은 주변 후보의 미확정 상태는 전체를 보류하지 않음
    v = val('V09', {**base, 'primary': [{'candidate': t09, 'rows': [f'{t09}.1'], 'support': [], 'why': ''}]})
    f = final('V09', v, 'supported')
    check('선택하지 않은 주변 후보의 미확정 상태로는 보류하지 않음(정상 사례)', f['status'] == 'supported', [r['rule'] for r in f['reasons']])
    # 자료 없음
    v = val('V09', {**base, 'advisory_status': 'not_found'})
    f = final('V09', v, 'not_found')
    check('모델이 주 근거를 내지 않고 not_found면 현재 읽은 범위의 not_found로 기록(문서 전체 부재 단정 아님)',
          f['status'] == 'not_found' and '현재 읽은 범위' in f['reasons'][0]['detail'])
    # 모델 호출 실패 시 기존 방식으로 전환하고 표시
    class FailCaller:
        def call(self, *a, **k):
            return {'ok': False, 'error': 'simulated', 'attempts': 1, 'cost_usd': 0.0, 'cached': False}
    vs = sv.VerifiedSelector(rt, FailCaller(), sel)
    r = vs.run(Q['V09'])
    check('모델 호출 실패 시 4b 방식으로 전환하고 전환 사실·불완전·미검증을 표시',
          r['method'] == 'fallback_4b' and r['fallback']['used'] and r['incomplete'] and r['final']['sufficiency'] == 'unverified', r['final'].get('status'))
    # ---- 정적 검사: 실행 코드·프롬프트에 질문 ID·정답 조각·참조 ID·실패 낱말을 직접 쓰지 않는다
    import re
    src = (WORK / 'src/select_verified.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', src))
    pats = {'질문 ID': r"['\"][NVQ]\d{2}['\"]", '조각 ID': r"['\"][trw]:(?:full-p|complete-|common|civil|arch|mech|maint)", '참조 ID': r"rel\d{3,}",
            '절 ID': r"pumsem-2026-errata1:(?:common|civil|arch|mech|maint):\d", '질문 파일': r"new_questions|dev_questions|expected_",
            '4c·4d에서 본 실패 낱말': r"병원건물|혼합토사|서양식|풍력|태양광|일반업무용|준설|도배|BIM|군 구분|벽 연결재"}
    hit = {k: re.findall(p_, code) for k, p_ in pats.items()}
    check('실행 코드·프롬프트에 질문 ID·정답 조각·참조 ID·실패 낱말이 없음(하드코딩 금지)', not any(hit.values()), {k: v[:3] for k, v in hit.items() if v})
    rt.close()
    out = {'passed': sum(c['passed'] for c in res), 'failed': sum(not c['passed'] for c in res),
           'note': '가상 입력 검사: 검증 코드가 잘못된 입력을 막는지 본다. 선택 의미의 정확성은 평가 결과로 따로 본다.', 'checks': res}
    (HERE / 'verify_4d_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for c in res:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:160]}"))
    print(out['passed'], 'passed', out['failed'], 'failed')


if __name__ == '__main__':
    main()
