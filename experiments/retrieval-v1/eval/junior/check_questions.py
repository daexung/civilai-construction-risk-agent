"""주니어 시나리오 질문(Q1) 검사. 외부 호출 없음.

질문 파일의 정답 근거가 원문 조각과 맞는지 코드로 확인한다.
- 조각 ID가 실제로 있고, 그 과제에 준 조각인지
- 정답 숫자·구절(required_value_tokens)이 근거 조각 글에 글자 그대로 있는지
- 유형별 형식(T8 두 턴, T9·T10 근거 없음, T11 견적 안내 등)
- 글자 깨짐(??·�) 없음

사용(저장소 루트): .venv/Scripts/python.exe -B experiments/retrieval-v1/eval/junior/check_questions.py <questions.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]
CHUNKS = WORK / 'out/chunks/cs-37f81b5cfb1b-46f4f035c0fa/chunks.jsonl'
STATUS = {'supported', 'not_found', 'out_of_scope'}


def problems(case: dict, chunks: dict[str, str]) -> list[str]:
    out = []
    kind = case.get('type', '')
    blob = json.dumps(case, ensure_ascii=False)
    if '??' in blob or '�' in blob:
        out.append('글자 깨짐')
    turns = case.get('turns') or []
    if len(turns) != (2 if kind == 'T8_followup' else 1) or not all(t.strip() for t in turns):
        out.append(f'턴 수 {len(turns)}')
    if case.get('status_expected') not in STATUS:
        out.append(f'상태 {case.get("status_expected")}')
    want_status = {'T9_not_found': 'not_found', 'T10_out_of_scope': 'out_of_scope'}.get(kind, 'supported')
    if case.get('status_expected') != want_status:
        out.append(f'유형과 상태 불일치 {case.get("status_expected")}')
    want_action = 'offer_estimate' if kind == 'T11_quick_calc' else 'answer'
    if case.get('expected_action') != want_action:
        out.append(f'행동 {case.get("expected_action")}')
    req = case.get('required_chunks') or []
    tokens = case.get('required_value_tokens') or []
    if want_status != 'supported':
        if req or tokens:
            out.append('근거 없어야 함')
        return out
    if not req:
        out.append('근거 조각 없음')
    allowed = set(case.get('_given') or [])
    texts = []
    for item in req:
        cid = item.get('chunk_id')
        if cid not in chunks:
            out.append(f'없는 조각 {cid}')
        elif allowed and cid not in allowed:
            out.append(f'주지 않은 조각 {cid}')
        else:
            texts.append(chunks[cid])
    if kind == 'T7_compare' and len(req) < 2:
        out.append('비교인데 근거 1개')
    if not tokens:
        out.append('정답 토큰 없음')
    for token in tokens:
        if not any(token in text for text in texts):
            out.append(f'원문에 없는 토큰 {token!r}')
    return out


def _selftest() -> None:
    chunks = {'c1': '배관공 | 수량 0.569'}
    good = {'type': 'T1_value', 'turns': ['q'], 'status_expected': 'supported', 'expected_action': 'answer',
            'required_chunks': [{'chunk_id': 'c1'}], 'required_value_tokens': ['0.569']}
    assert problems(good, chunks) == []
    assert problems({**good, 'required_value_tokens': ['0.56 9']}, chunks)
    assert problems({**good, 'required_chunks': [{'chunk_id': 'c9'}]}, chunks)
    assert problems({**good, 'turns': ['q', 'q2']}, chunks)
    nf = {'type': 'T9_not_found', 'turns': ['q'], 'status_expected': 'not_found', 'expected_action': 'answer'}
    assert problems(nf, chunks) == [] and problems({**nf, 'required_value_tokens': ['1']}, chunks)
    assert problems({**good, 'type': 'T11_quick_calc'}, chunks) == ['행동 answer']


def main() -> int:
    _selftest()
    sys.stdout.reconfigure(encoding='utf-8')
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    chunks = {}
    for line in CHUNKS.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        chunks[row['chunk_id']] = row['text']
    bad = 0
    for case in data['questions']:
        found = problems(case, chunks)
        if found:
            bad += 1
            print(case['id'], '; '.join(found))
    ids = [c['id'] for c in data['questions']]
    assert len(ids) == len(set(ids)), '중복 ID'
    print(f'질문 {len(ids)}, 문제 있는 질문 {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
