"""5b단계 시험 질문을 실제 로컬 API(/api/local-trial/ask)로 보내고 기대(trial_questions_05b.json)와 대조한다.

  python -B run_trial_05b.py --ids G03 G01 --out trial_results_05b_dev1.json
  python -B run_trial_05b.py --out trial_results_05b_final.json      # 전체(G03은 repeat 만큼 반복)
저장 JSON을 돌려주는 모의 서비스가 아니라 실제 경로(검색 → 답변 생성 → 코드 인용)를 호출한다. 호출 수는 서버 원장(ledger_05b.jsonl)이 센다.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent


def post(base, q):
    req = urllib.request.Request(base + '/api/local-trial/ask', data=json.dumps({'message': q}).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=240) as r:
        body = json.loads(r.read().decode('utf-8'))
    return body, round((time.perf_counter() - t) * 1000)


def check(spec, r):
    notes = []
    ok = True
    if r['search_status'] != spec['expected_search_status']:
        ok = False
        notes.append(f"검색 상태 {r['search_status']} (기대 {spec['expected_search_status']})")
    if r['answer_status'] != spec['expected_answer_status']:
        ok = False
        notes.append(f"답변 상태 {r['answer_status']} (기대 {spec['expected_answer_status']}; 이유 {r['answer_status_reason']['code']}, 생성 {r['generation'].get('code')})")
    ans = r.get('answer') or ''
    cites = r.get('citations', [])
    exp = spec['expected_answer_status']
    if exp == 'confirmed':
        v = spec.get('expected_value', '')
        if re.fullmatch(r'[\d.]+', v):
            if v not in ans:
                ok = False
                notes.append(f'답변에 값 {v} 없음')
            if not any(v in c['quote'] for c in cites):
                ok = False
                notes.append(f'인용 줄에 값 {v} 없음')
            claim = next((c for c in r.get('value_claims', []) if c['value'] == v), None)
            if not claim:
                ok = False
                notes.append('값 기록 없음')
            elif spec.get('expected_column') and spec['expected_column'] not in (claim.get('column_name') or ''):
                ok = False
                notes.append(f"열 이름 {claim.get('column_name')} (기대 {spec['expected_column']})")
        es = spec.get('expected_source')
        if es:
            hit = [s for s in r['sources'] if s.get('section_no') == es['section_no'] and s.get('division') == es['division'] and s.get('kind') == es['kind']]
            cited_hit = [s for s in hit if s.get('cited')]
            if not cited_hit:
                ok = False
                notes.append(f"인용한 출처에 {es['division']} {es['section_no']} {es['kind']} 없음")
            else:
                if es.get('pdf_page') and not any(s.get('pdf_page') == es['pdf_page'] for s in cited_hit):
                    ok = False
                    notes.append(f"쪽 불일치 {[s.get('pdf_page') for s in cited_hit]}")
                if es.get('printed_page') and not any(s.get('printed_page') == es['printed_page'] for s in cited_hit):
                    ok = False
                    notes.append(f"인쇄 쪽 불일치 {[s.get('printed_page') for s in cited_hit]}")
                if es.get('line_contains') and not any(es['line_contains'] in l['text'] and l.get('cited') for s in cited_hit for l in s['lines']):
                    ok = False
                    notes.append(f"인용 줄에 '{es['line_contains']}' 없음")
        cited_sections = {(s.get('division'), s.get('section_no')) for s in r['sources'] if s.get('cited')}
        extra = cited_sections - ({(es['division'], es['section_no'])} if es else set()) - ({(spec['expected_reference']['division'], spec['expected_reference']['section_no'])} if spec.get('expected_reference') else set())
        if extra:
            notes.append(f'(주의) 기대 밖 절을 인용: {sorted(extra)}')
        shown = {(s['id'], l['n']) for s in r['sources'] for l in s['lines'] if l.get('cited')}
        if {(c['chunk_id'], c['line']) for c in cites} != shown:
            ok = False
            notes.append('인용 위치와 출처 카드 표시 불일치')
    if exp == 'condition_unconfirmed':
        for bad in spec.get('must_not', []):
            if re.fullmatch(r'[\d.]+', bad) and bad in ans:
                ok = False
                notes.append(f'다른 조건 값 {bad}을 답변에 씀')
        if cites or any(s.get('cited') for s in r['sources']):
            ok = False
            notes.append('확정하지 않았는데 인용 표시가 남음')
        if not r['sources']:
            ok = False
            notes.append('원문 출처를 볼 수 없음')
    if exp in ('needs_confirmation', 'not_found'):
        if r['sources'] and exp == 'needs_confirmation':
            ok = False
            notes.append('확인 필요인데 확정 출처 영역이 보임')
        er = spec.get('expected_review_source')
        if er and not any(s.get('section_no') == er['section_no'] and s.get('division') == er['division'] for s in r['review_material'] + r.get('related', [])):
            ok = False
            notes.append(f"검토용·관련 원문에 {er['division']} {er['section_no']} 없음")
        if exp == 'not_found' and (r['sources'] or r['review_material'] or r.get('related')):
            ok = False
            notes.append('근거 못 찾음인데 출처·검토용이 보임')
        if spec.get('expected_alternatives'):
            got = {f"{a['division']} {a['number']} {a['title']}" for a in r['alternatives']}
            if not set(spec['expected_alternatives']) <= got:
                ok = False
                notes.append('대안 누락')
    if r.get('applicability', 'unknown') != 'unknown':
        ok = False
        notes.append('applicability가 unknown이 아님')
    return ok, notes


def main(base, ids, out, repeat_g03):
    spec = json.loads((HERE / 'trial_questions_05b.json').read_text(encoding='utf-8'))
    rows = []
    sys.stdout.reconfigure(encoding='utf-8')
    for q in spec['questions']:
        if ids and q['id'] not in ids:
            continue
        for k in range(repeat_g03 if (q['id'] == 'G03' and repeat_g03) else 1):
            try:
                body, ms = post(base, q['question'])
            except Exception as exc:
                rows.append({'id': q['id'], 'run': k + 1, 'error': f'{type(exc).__name__}: {str(exc)[:120]}'})
                print(q['id'], 'ERROR', exc)
                continue
            ok, notes = check(q, body)
            g = body['generation']
            rows.append({'id': q['id'], 'run': k + 1, 'question': q['question'], 'passed': ok, 'notes': notes, 'client_ms': ms, 'response': body})
            print(f"{q['id']}#{k + 1}", body['search_status'], '->', body['answer_status'], 'PASS' if ok else 'FAIL', notes,
                  '| src', len(body['sources']), 'rev', len(body['review_material']), '| gen', g.get('source'), g.get('state'), g.get('code'),
                  '| cites', [c['location'] for c in body.get('citations', [])], '| vals', [(v['value'], v.get('column_name')) for v in body.get('value_claims', [])],
                  '|', ms, 'ms', (g.get('usage') or {}).get('cost_usd'))
            if g.get('code') and g.get('state') != 'answered':
                print('    detail:', {k_: g.get(k_) for k_ in ('error', 'detail', 'location', 'value', 'unit', 'raw_locations', 'model_status', 'unmatched', 'rejected_claim')})
    (HERE / out).write_text(json.dumps({'base': base, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8010')
    ap.add_argument('--ids', nargs='*', default=[])
    ap.add_argument('--out', default='trial_results_05b.json')
    ap.add_argument('--repeat-g03', type=int, default=0)
    a = ap.parse_args()
    main(a.base, a.ids, a.out, a.repeat_g03)
