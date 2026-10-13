"""근거 선택(4b) 동작·보존 검사. 질문 임베딩 호출 없이 캐시된 개발 질문만 쓴다. 검색 품질 평가가 아니다.

  python -B experiments/retrieval-v1/checks/verify_selection.py

- 선택 코드가 질문 ID·정답 조각·참조 ID를 직접 쓰지 않는지(정답 하드코딩 금지), 추가 검색 2회 한도, 근거 없음 처리,
  부문 한정, 잘못된 길어깨 관계 15건 미사용, 같은 입력 같은 결과, 읽기 전용, 버전 고정을 확인한다.
- 결과: out/verification_runs/<청킹 묶음 ID>/<run_id>/verification.json
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import embed_index as ei  # noqa: E402
import retrieve as rv  # noqa: E402
import run_records as rr  # noqa: E402
import select_evidence as se  # noqa: E402


def sha(o):
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def main():
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})

    src = (WORK / 'src/select_evidence.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', src))
    pats = {'질문 ID': r"['\"][NVQ]\d{2}['\"]", '조각 ID': r"['\"][trw]:(?:full-p|complete-|common|civil|arch|mech|maint)",
            '참조 ID': r"rel\d{3,}", '절 ID': r"pumsem-2026-errata1:", '질문 파일': r"new_questions|dev_questions|expected_"}
    hit = {k: re.findall(p, code) for k, p in pats.items()}
    check('선택 코드가 질문 ID·정답 조각·참조 ID·질문 파일을 직접 쓰지 않음', not any(hit.values()), {k: v[:3] for k, v in hit.items() if v})

    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    qs = {
        'value': '벽돌 0.5B 쌓기 하루에 몇 ㎡ 쌓아? 시공높이 3.6m 이하로 봐줘.',
        'rule': '벽돌 쌓기 품에 모르타르 비빔 작업도 들어 있어? 배합이 필요하면 어디를 봐야 해?',
        'list': '페인트칠 종류별로 어떤 품이 있어?',
        'nodata': 'BIM 모델링 작업은 품이 몇 인이야?',
        'multi': '블록 쌓기하면서 개구부 위 인방보도 같이 설치하는 경우 필요한 품 근거를 알려줘',
        'division': '건축부문 방수 프라이머 바름 품',
        'group': '목재면에 오일스테인 칠할 때 바탕만들기까지 포함한 견적 근거를 알려줘',
    }
    out = {}
    for k, q in qs.items():
        try:
            out[k] = sel.run(q)
        except RuntimeError as e:        # 캐시에 없는 질문(호출을 끈 상태)이면 건너뛴다
            out[k] = None
            check(f'질문 벡터 캐시 확인: {k}', False, str(e)[:80])
    ok = {k: v for k, v in out.items() if v}
    check('상태가 세 값(supported·needs_confirmation·not_found) 중 하나', all(v['status'] in ('supported', 'needs_confirmation', 'not_found') for v in ok.values()),
          {k: v['status'] for k, v in ok.items()})
    check('추가 검색은 질문마다 최대 2회(상위 묶음 탐색 포함)', all(v['extra_searches_used'] <= 2 and len(v['extra_searches']) <= 2 for v in ok.values()),
          {k: v['extra_searches_used'] for k, v in ok.items()})
    nd = ok.get('nodata')
    check('관련 근거를 찾지 못함: 정상 근거로 내보내지 않고 진단 정보로만 남김',
          nd and nd['status'] == 'not_found' and not nd['evidence_sets'] and not nd['sections'] and 'diagnostic_candidates' in nd, nd and nd['status'])
    div = ok.get('division')
    check('질문에 부문이 명시되면 그 부문 절만 근거로 선택', div and all(s['division'] == '건축부문' for s in div['sections']), div and [s['division'] for s in div['sections']])
    lst = ok.get('list')
    grp = ok.get('group')
    gs = (grp or {}).get('group_target_search', [])
    check('상위 묶음 참조: 하위 절 후보만 제시하고 선택·확정하지 않으며 추가 검색 횟수에 포함',
          grp and gs and all(g['selected'] is None and g['status'] in ('candidates_not_confirmed', 'unresolved') for g in gs) and
          any(e['kind'] == 'group_target' for e in grp['extra_searches']) and grp['extra_searches_used'] <= 2, gs and [g['status'] for g in gs])
    check('목록: 정해진 5개를 넘는 공종 집합과 선택 사유를 반환', lst and lst['list'] and len(lst['sections']) > 5 and all(s.get('why') for s in lst['sections']),
          lst and len(lst['sections']))
    val = ok.get('value')
    prim = [e for e in (val or {}).get('evidence_sets', []) if e['role'] == 'primary']
    check('특정 값: 선택 조각마다 선택 사유와 점수가 있고 같은 절의 모든 조각을 붙이지 않음',
          prim and all('reasons' in c and 'score' in c for c in prim[0]['selected']) and len(prim[0]['selected']) < len(sel.chunks_of[prim[0]['section_id']]),
          prim and len(prim[0]['selected']))
    a1, a2 = sel.run(qs['value']), sel.run(qs['value'])
    strip = lambda r: {k: v for k, v in r.items() if k not in ('embed_api_sec',)}
    check('같은 질문은 같은 선택 결과', sha(strip(a1)['evidence_sets']) == sha(strip(a2)['evidence_sets']) and a1['status'] == a2['status'])
    sup = rt.reader.sup
    leak = []
    for v in ok.values():
        for e in v.get('evidence_sets', []):
            for cid, u in e['result']['units'].items():
                leak += [l.get('relation_id') for l in u['links'] if l.get('relation_id') in sup]
    check('잘못된 길어깨 관계 15건이 선택 결과의 연결에 없음', len(sup) == 15 and not leak, {'excluded': len(sup), 'leak': leak[:3]})
    check('버전: 청킹 묶음·원문이 고정값', (rt.reader.cs, rt.reader.rid) == (ei.CS, 'rk-complete-82c206c61e21-37f81b5cfb1b'))
    v = se.versions(sel)
    check('버전 기록에 선택 코드·설정 해시가 있음', len(v['select_code_sha256']) == 64 and len(v['select_config_sha256']) == 64)
    try:
        rt.conn.execute("update rag_knowledge.chunk_sets set status='failed' where chunk_set_id=%s", (ei.CS,))
        wrote = True
    except Exception:
        wrote = False
    check('조회 연결은 읽기 전용(쓰기 거부)', not wrote)
    rt.close()
    return checks


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run = rr.start(ei.CS, 'verify_selection', None, note='4b 선택 동작·보존 검사(질문 임베딩 호출 없음)')
    try:
        checks = main()
        res = {'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks),
               'note': '동작·보존 검사. 검색 품질 평가가 아니다.', 'checks': checks}
        meta = rr.finish(run, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:200]}"))
    print('run', meta['run_id'], meta['status'])
    sys.exit(0 if meta['status'] == 'passed' else 1)
