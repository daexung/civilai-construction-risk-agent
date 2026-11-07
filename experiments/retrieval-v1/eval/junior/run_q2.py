"""Q2: 주니어 시나리오 50문을 운영 대화 경로(dialogue.run_turn)로 돌려 채점한다.

운영과 같은 설정(KNOWLEDGE_RETRIEVAL=v1, AGENT_LLM=on)으로 .env의 DB(읽기 전용)와 모델을 쓴다. 유료 호출이 있다.
결과: experiments/retrieval-v1/out/verification_runs/junior_q2/<시각>.json (Git 제외)

판정(질문마다 하나):
- ok              : 기대대로 처리
- wrong_route     : 지식 답변 경로를 타지 않음(견적 경로 등) — supported 질문
- refused         : 정답이 있는데 not_found
- wrong_source    : 답은 했으나 정답 절을 근거로 쓰지 않음
- withheld        : 정답 절은 맞으나 '확인 필요'·'원문만'으로 보류해 숫자를 말하지 않음
- missing_value   : 정답 절은 맞고 확정 답인데 정답 숫자·구절이 답에 없음
- answered_absent : 없다고 해야 하는데 근거를 들어 답함(T9)
- not_rejected    : 범위 밖인데 거절하지 않음(T10)
- no_offer        : 간단 계산에서 견적 안내 없음(T11, 현재 기능 없음)
- error           : 실행 오류

사용(저장소 루트): .venv/Scripts/python.exe -B experiments/retrieval-v1/eval/junior/run_q2.py [--quick] [ID ...]
  --quick: 빠른 질문 탭(mode=quick)으로 보낸다
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / 'experiments/retrieval-v1'
QUESTIONS = WORK / 'eval/junior/questions_2026-11-07.json'
CHUNKS = WORK / 'out/chunks/cs-37f81b5cfb1b-46f4f035c0fa/chunks.jsonl'
OUT = WORK / 'out/verification_runs/junior_q2'


def norm_div(text: str | None) -> str:
    return (text or '').removesuffix('부문').strip()


def required_sections(case: dict, chunks: dict) -> set[tuple[str, str]]:
    out = set()
    for item in case.get('required_chunks') or []:
        ch = chunks[item['chunk_id']]
        out.add((norm_div(ch['division']), ch['section_id'].rsplit(':', 1)[1]))
    return out


def observe(state: dict) -> dict:
    turn = state.get('turn') or {}
    k = turn.get('knowledge') or {}
    cited = {(norm_div(s.get('division')), s.get('section_no'))
             for key in ('sources', 'related') for s in k.get(key) or [] if s}
    return {'answer_source': turn.get('answer_source'), 'tools': turn.get('tools'), 'answer': turn.get('answer') or '',
            'knowledge_status': k.get('answer_status') or k.get('status') if k else None,
            'cited': sorted([list(c) for c in cited]), 'route': state.get('route'),
            'query': next((t['args'].get('query') for t in turn.get('trace') or [] if t.get('tool') == 'search_standard' and t.get('args')), None)}


def judge(case: dict, obs: dict, need: set) -> str:
    kind, status = case['type'], case['status_expected']
    text = obs['answer']
    cited = {tuple(c) for c in obs['cited']}
    used_knowledge = obs['answer_source'] == 'knowledge-v1'
    if status == 'out_of_scope':
        return 'ok' if not used_knowledge and not obs['tools'] else 'not_rejected'
    if status == 'not_found':
        if obs['knowledge_status'] == 'not_found' or re.search(r'없(어요|습니다|다)|수록되어 있지 않', text):
            return 'ok'
        return 'answered_absent' if cited else 'wrong_route'
    if not used_knowledge:
        return 'wrong_route'
    if obs['knowledge_status'] == 'not_found':
        return 'refused'
    if not need <= cited:
        return 'wrong_source'
    # 구절(포함·정의 답)은 말 바꿈이 자연스러워 숫자가 든 토큰만 글자 그대로 본다.
    tokens = [t for t in case['required_value_tokens'] if re.search(r'\d', t) and not re.search(r'[가-힣]{3}', t)]
    if obs['knowledge_status'] in ('needs_confirmation', 'source_check_needed', 'condition_unconfirmed'):
        return 'withheld'
    if not all(t in text for t in tokens):
        return 'missing_value'
    if kind == 'T11_quick_calc' and '견적' not in text:
        return 'no_offer'
    return 'ok'


def _selftest() -> None:
    case = {'type': 'T1_value', 'status_expected': 'supported', 'required_value_tokens': ['0.5']}
    base = {'answer_source': 'knowledge-v1', 'tools': ['search_standard'], 'answer': '0.5인', 'knowledge_status': 'supported',
            'cited': [['공통', '1-1']]}
    need = {('공통', '1-1')}
    assert judge(case, base, need) == 'ok'
    assert judge(case, {**base, 'answer': '0.6'}, need) == 'missing_value'
    assert judge(case, {**base, 'cited': [['공통', '1-2']]}, need) == 'wrong_source'
    assert judge(case, {**base, 'answer_source': 'llm'}, need) == 'wrong_route'
    assert judge({**case, 'status_expected': 'not_found'}, {**base, 'knowledge_status': 'not_found'}, set()) == 'ok'
    scope_card = {**base, 'answer_source': 'template', 'tools': [], 'knowledge_status': None, 'cited': [], 'answer': '범위를 확인해 주세요'}
    assert judge({**case, 'status_expected': 'not_found'}, scope_card, set()) == 'wrong_route'
    assert judge({**case, 'required_value_tokens': ['별도 계상한다']}, {**base, 'answer': '따로 잡아요'}, need) == 'ok'
    assert judge({**case, 'required_value_tokens': ['별도 계상한다']}, {**base, 'knowledge_status': 'needs_confirmation'}, need) == 'withheld'
    assert judge(case, {**base, 'answer': '확인', 'knowledge_status': 'needs_confirmation'}, need) == 'withheld'
    assert judge({**case, 'type': 'T11_quick_calc'}, base, need) == 'no_offer'


def load_env() -> None:
    for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    os.environ.update({'KNOWLEDGE_RETRIEVAL': 'v1', 'AGENT_LLM': 'on', 'AGENT_MODE': 'tools',
                       'LLM_PROVIDER': os.environ.get('LLM_PROVIDER', 'studio')})


def main() -> int:
    _selftest()
    sys.stdout.reconfigure(encoding='utf-8')
    load_env()
    sys.path.insert(0, str(ROOT))
    from backend.agent.estimate import dialogue  # noqa: E402 - 환경 설정 뒤에 불러온다

    chunks = {}
    for line in CHUNKS.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        chunks[row['chunk_id']] = row
    cases = json.loads(QUESTIONS.read_text(encoding='utf-8'))['questions']
    if sys.argv[1:2] == ['--rejudge']:
        rows = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
        by_id = {c['id']: c for c in cases}
        for r in rows:
            if r['verdict'] != 'error':
                v = judge(by_id[r['id']], r['observed'][-1], {tuple(n) for n in r['need']})
                r['verdict'] = ('followup_' + v) if r['type'] == 'T8_followup' and v != 'ok' else v
        Path(sys.argv[2]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        from collections import Counter
        print(dict(Counter(r['verdict'] for r in rows)))
        return 0
    args = sys.argv[1:]
    mode = 'quick' if '--quick' in args else None  # 빠른 질문 탭 요청으로 보낸다
    only = {a for a in args if not a.startswith('--')}
    rows = []
    for case in cases:
        if only and case['id'] not in only:
            continue
        need = required_sections(case, chunks)
        started = time.monotonic()
        try:
            state = dialogue.new_dialogue()
            turns = []
            for message in case['turns']:
                state = dialogue.run_turn(state, {'message': message, 'mode': mode})
                turns.append(observe(state))
            verdict = judge(case, turns[-1], need)
            if case['type'] == 'T8_followup' and verdict != 'ok':
                verdict = 'followup_' + verdict
        except Exception:  # noqa: BLE001 - 한 질문 실패가 전체 채점을 멈추지 않게
            turns, verdict = [{'error': traceback.format_exc(limit=3)}], 'error'
        rows.append({'id': case['id'], 'type': case['type'], 'turns': case['turns'], 'verdict': verdict,
                     'need': sorted([list(n) for n in need]), 'expected_tokens': case['required_value_tokens'],
                     'observed': turns, 'sec': round(time.monotonic() - started, 1)})
        print(case['id'], case['type'], verdict, rows[-1]['sec'], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'{datetime.now():%Y%m%d-%H%M%S}{"-quick" if mode else ""}.json'
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    from collections import Counter
    print(dict(Counter(r['verdict'] for r in rows)), '->', path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
