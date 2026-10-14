"""No-DB, no-provider exercise of graph and tool traces and public response shape."""
from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_OFFLINE='1', AGENT_LLM='off', INDEX_CONFIG=str(ROOT / 'evals/index_configs/6chapter_studio.json'))

from langgraph.checkpoint.memory import MemorySaver
from backend.agent.graph import build_graph
from backend.agent.state import new_state
from backend.agent.estimate.dialogue import build_dialogue_graph
from backend.api import answer_runs, main
from backend.shared import answer_trace


def _size(steps):
    return len(json.dumps(steps, ensure_ascii=False, default=str, separators=(',', ':')).encode('utf-8'))


def main_check():
    query = '철근콘크리트 벽체 100㎥ 펌프차 타설 품셈 기준'
    graph = build_graph(MemorySaver())

    def run_graph(thread_id, traced):
        started = perf_counter()
        if traced:
            with answer_trace.capture(request_id=thread_id, thread_id=thread_id) as trace:
                state = graph.invoke(new_state(query), {'configurable': {'thread_id': thread_id}})
                response = main._build_response(thread_id, state)
        else:
            state = graph.invoke(new_state(query), {'configurable': {'thread_id': thread_id}})
            response = main._build_response(thread_id, state)
            trace = None
        return response, trace, round((perf_counter() - started) * 1000, 2)

    run_graph('offline-warmup', False)
    baseline_runs = [run_graph(f'offline-baseline-{n}', False) for n in range(7)]
    traced_runs = [run_graph(f'offline-traced-{n}', True) for n in range(7)]
    baseline_response, _, _ = baseline_runs[-1]
    response, graph_trace, _ = traced_runs[-1]
    baseline_ms = round(median(row[2] for row in baseline_runs), 2)
    traced_ms = round(median(row[2] for row in traced_runs), 2)
    trace_overhead_ms = round(traced_ms - baseline_ms, 2)
    assert response.get('answer_id') and 'execution' not in response
    assert response.get('status') == baseline_response.get('status')
    assert response.get('result') == baseline_response.get('result')
    assert any(step['name'] == 'retrieve' for step in graph_trace['steps'])
    assert any(step['name'] == 'search' for step in graph_trace['steps'])
    assert all('private' not in str(step) for step in graph_trace['steps'])
    assert answer_runs._final_summary(response) is not None

    with answer_trace.capture(request_id='offline-tool-check', thread_id='offline-tool-check') as tool_trace:
        dialogue = build_dialogue_graph(MemorySaver())
        dialogue.invoke({'request': {'message': '철근콘크리트 100㎥ 32m 펌프차 타설 비용 계산해줘'}},
                        {'configurable': {'thread_id': 'offline-tool-check'}})
    tool_kinds = {step['step_kind'] for step in tool_trace['steps']}
    assert 'node' in tool_kinds and 'tool' in tool_kinds
    assert any(step['name'] == 'turn' for step in tool_trace['steps'])
    assert any(step['name'] == 'search' for step in tool_trace['steps'])
    assert any(step['name'] in {'find_work', 'compute_labor', 'estimate_cost', 'search_standard', 'set_conditions'}
               for step in tool_trace['steps'])
    assert len({step['id'] for step in tool_trace['steps']}) == len(tool_trace['steps'])
    sequences = [step['sequence'] for step in tool_trace['steps']]
    assert len(sequences) == len(set(sequences))
    print(json.dumps({'status': 'passed', 'graph_step_count': len(graph_trace['steps']),
                      'tool_step_count': len(tool_trace['steps']), 'graph_trace_json_bytes': _size(graph_trace['steps']),
                      'tool_trace_json_bytes': _size(tool_trace['steps']), 'graph_baseline_ms': baseline_ms,
                      'graph_traced_without_db_ms': traced_ms, 'trace_overhead_estimate_ms': trace_overhead_ms,
                      'tool_steps': [step['name'] for step in tool_trace['steps']],
                      'response_has_answer_id': bool(response.get('answer_id')),
                      'response_exposes_execution': 'execution' in response}, ensure_ascii=False))


if __name__ == '__main__':
    main_check()
