"""5단계 시험 10문을 실제 로컬 API(/api/local-trial/ask)로 보내고 결과를 기록·대조한다. 저장 JSON을 반환하는 모의 서비스가 아니라 실제 경로를 부른다.

  python -B run_trial_05.py [--base http://127.0.0.1:8010] [--out trial_results_05.json]
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
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read().decode('utf-8'))
    return body, round((time.perf_counter() - t) * 1000)


def check(spec, r):
    notes = []
    ok = r['status'] == spec['expected_status']
    if not ok:
        notes.append(f"상태 {r['status']} (기대 {spec['expected_status']})")
    src_text = ' '.join(l['text'] for s in r['sources'] for l in s['lines'])
    ans = r.get('answer') or ''
    if spec.get('expected_value') and spec['expected_status'] == 'supported':
        v = spec['expected_value']
        if re.fullmatch(r'[\d.]+', v) and v not in ans:
            ok = False
            notes.append(f'답변에 값 {v} 없음')
        if re.fullmatch(r'[\d.]+', v) and v not in src_text:
            ok = False
            notes.append(f'출처 원문에 값 {v} 없음')
    es = spec.get('expected_source')
    if es:
        hit = [s for s in r['sources'] if s.get('section_no') == es['section_no'] and s.get('division') == es['division']]
        if not hit:
            ok = False
            notes.append(f"출처에 {es['division']} {es['section_no']} 없음")
        elif es.get('pdf_page') and not any(s.get('pdf_page') == es['pdf_page'] for s in hit):
            ok = False
            notes.append(f"출처 쪽 불일치 {[s.get('pdf_page') for s in hit]}")
        elif es.get('printed_page') and not any(s.get('printed_page') == es['printed_page'] for s in hit):
            ok = False
            notes.append(f"인쇄 쪽 불일치 {[s.get('printed_page') for s in hit]}")
    er = spec.get('expected_review_source')
    if er:
        pool = r['review_material'] + r['sources']
        if not any(s.get('section_no') == er['section_no'] and s.get('division') == er['division'] for s in pool):
            ok = False
            notes.append(f"검토용·출처에 {er['division']} {er['section_no']} 없음")
        if r['status'] == 'needs_confirmation' and any(s.get('section_no') == er['section_no'] for s in r['sources']) and spec['id'] in ('G09', 'N19'):
            notes.append('(주의) 확정 출처 영역에 노출')
    if spec['expected_status'] == 'not_found' and (r['sources'] or r['review_material']):
        ok = False
        notes.append('근거 못 찾음인데 출처·검토용이 보임')
    if spec['id'] == 'N19' and (r['sources'] and r['status'] != 'needs_confirmation'):
        ok = False
    if spec.get('expected_alternatives'):
        got = {f"{a['division']} {a['number']} {a['title']}" for a in r['alternatives']}
        if not set(spec['expected_alternatives']) <= got:
            ok = False
            notes.append('대안 누락')
    if r['status'] == 'supported' and r['generation'].get('source') != 'llm':
        notes.append(f"설명 생성 {r['generation'].get('source')} ({r['generation'].get('error')})")
    return ok, notes


def main(base, out):
    spec = json.loads((HERE / 'trial_questions_05.json').read_text(encoding='utf-8'))
    rows = []
    sys.stdout.reconfigure(encoding='utf-8')
    for q in spec['questions']:
        try:
            body, ms = post(base, q['question'])
        except Exception as exc:
            rows.append({'id': q['id'], 'error': f'{type(exc).__name__}: {str(exc)[:120]}'})
            print(q['id'], 'ERROR', exc)
            continue
        ok, notes = check(q, body)
        rows.append({'id': q['id'], 'question': q['question'], 'passed': ok, 'notes': notes, 'client_ms': ms, 'response': body})
        print(q['id'], body['status'], 'PASS' if ok else 'FAIL', notes, '| src', len(body['sources']), 'review', len(body['review_material']), 'diag', len(body['diagnostic']),
              '| gen', body['generation'].get('source'), body['generation'].get('error'), '|', ms, 'ms')
    (HERE / out).write_text(json.dumps({'base': base, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8010')
    ap.add_argument('--out', default='trial_results_05.json')
    a = ap.parse_args()
    main(a.base, a.out)
