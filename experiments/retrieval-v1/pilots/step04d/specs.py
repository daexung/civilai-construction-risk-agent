"""4d 평가 질문 60개(기존 세 질문 세트) 명세. 원본 파일은 수정하지 않고 읽어서 같은 모양으로 바꾼다.

- 기존 질문 세트 3개: dev_questions_2026-10-10.json(20), new_questions_2026-10-12.json(20), new_questions_04b_2026-10-12.json(20).
- 개발 12문(V02·V09·V11·V12·V20 + V01·V05·V07·V15·V16·V17·V19)은 세 번째 세트 안에 있으므로 60문에 포함된다(합계 72문이 아니다).
- 같은 질문 글은 한 번만 센다(글 정규화로 중복 검사). Q05는 다공종 질문 1개(작업 3개)로 센다.
- 모두 이미 결과를 본 개발·회귀 자료다. 새 독립 평가가 아니다.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
WORK = HERE.parents[1]
PFX = 'pumsem-2026-errata1:'
DIVS = {'공통': 'common', '토목': 'civil', '건축': 'arch', '기계설비': 'mech', '유지관리': 'maint'}
DEV12 = ['V02', 'V09', 'V11', 'V12', 'V20', 'V01', 'V05', 'V07', 'V15', 'V16', 'V17', 'V19']
HOLD_ONLY_NEEDS = {'N08', 'N12', 'N17', 'N18', 'V12', 'V17'}


def _sec(x):
    return [PFX + s for s in x]


def load_specs():
    ev = WORK / 'eval'
    out = []
    old = json.loads((ev / 'dev_questions_2026-10-10.json').read_text(encoding='utf-8'))['questions']
    for q in old:
        tasks = q.get('tasks')
        spec_any = q.get('expect_any') or []
        spec_all = q.get('expect_all') or q.get('expect_set') or []
        mode = 'all' if spec_all else 'any'
        sections = [f'{PFX}{DIVS[d]}:{n}' for d, n in (spec_all or spec_any)]
        s = {'id': q['id'], 'set': 'dev_old', 'question': q['text'], 'category': q['intent'], 'answer_sections': sections, 'section_mode': mode,
             'acceptable_sections': [], 'forbidden_sections': [], 'required_chunks': [], 'forbidden_chunks': [], 'required_references': [],
             'required_states': {}, 'expected_values': {}, 'evidence_regex': q.get('evidence_regex'),
             'evidence_in': [f'{PFX}{DIVS[d]}:{n}' for d, n in q.get('evidence_in', [])], 'no_data': bool(q.get('expect_none')), 'hold': False,
             'is_list': q['intent'] == 'list', 'metric': q.get('metric'), 'expect_primary': [f'{PFX}{DIVS[d]}:{n}' for d, n in q.get('expect_primary', [])]}
        if tasks:
            s['tasks'] = [{'query': t['query'], 'answer_sections': [f'{PFX}{DIVS[d]}:{n}' for d, n in t.get('expect_any', [])], 'mode': 'any'} for t in tasks]
        out.append(s)
    for fname, tag in (('new_questions_2026-10-12.json', 'dev_n4'), ('new_questions_04b_2026-10-12.json', 'indep_04b_used')):
        for q in json.loads((ev / fname).read_text(encoding='utf-8'))['questions']:
            nd = q['category'] == 'no_data'
            out.append({'id': q['id'], 'set': tag, 'question': q['question'], 'category': q['category'], 'answer_sections': _sec(q.get('answer_sections', [])),
                        'section_mode': 'all', 'acceptable_sections': _sec(q.get('acceptable_also', [])),
                        'forbidden_sections': _sec(q.get('forbidden_sections', [])), 'required_chunks': q.get('required_chunks', []),
                        'forbidden_chunks': q.get('forbidden_chunks', []), 'required_references': q.get('required_references', []),
                        'required_states': q.get('required_states', {}), 'expected_values': q.get('expected_values', {}),
                        'evidence_regex': None, 'evidence_in': [], 'no_data': nd, 'hold': bool(q.get('interpretation_hold')),
                        'is_list': q['category'] == 'list', 'metric': None, 'expect_primary': []})
    for s in out:
        s['allowed_status'] = ['not_found'] if s['no_data'] else (['needs_confirmation'] if s['id'] in HOLD_ONLY_NEEDS else ['supported', 'needs_confirmation'])
        s['dev12'] = s['id'] in DEV12
    seen = {}
    for s in out:
        k = re.sub(r'\s+', '', s['question'])
        if k in seen:
            raise SystemExit(f"중복 질문: {s['id']} = {seen[k]}")
        seen[k] = s['id']
    return out


if __name__ == '__main__':
    sp = load_specs()
    import collections
    print(len(sp), collections.Counter(s['set'] for s in sp), 'dev12 in 60:', sum(s['dev12'] for s in sp))
