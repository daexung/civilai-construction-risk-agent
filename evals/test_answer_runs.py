"""Model-free checks for trace isolation, privacy limits and response separation."""
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.shared import answer_trace
from backend.api import answer_runs
from backend.agent.tools.llm import client


def test_actual_call_metadata_excludes_prompt_and_output():
    with answer_trace.capture(), patch.dict(os.environ, {'AGENT_LLM': 'on', 'LLM_PROVIDER': 'studio',
                                                          'GEMINI_API_KEY': 'fixture-secret'}):
        result = client.generate('private question', 'fixed system', model='fixture-model',
                                 request_fn=lambda *args: 'private reply')
        steps = answer_trace.current()['steps']
    assert result.text == 'private reply'
    assert len(steps) == 1
    assert steps[0]['step_kind'] == 'model' and steps[0]['status'] == 'completed'
    assert steps[0]['metadata']['model'] == 'fixture-model' and steps[0]['metadata']['attempts'] == 1
    assert 'fixed system' not in str(steps) and 'private question' not in str(steps) and 'private reply' not in str(steps)
    assert answer_trace.current() is None


def test_nested_capture_and_model_failure_are_isolated():
    with answer_trace.capture():
        with answer_trace.step('turn', 'node') as parent:
            try:
                with patch.dict(os.environ, {'AGENT_LLM': 'off'}):
                    client.generate('private', 'fixed', model='fixture-model')
            except client.LLMUnavailable:
                pass
        steps = answer_trace.current()['steps']
    assert [step['step_kind'] for step in steps] == ['node', 'model']
    assert steps[1]['parent_step_id'] == parent['id']
    assert steps[1]['status'] == 'failed' and steps[1]['metadata']['attempts'] == 0
    assert 'private' not in str(steps)


def test_parallel_requests_have_independent_step_collections():
    def collect(name):
        with answer_trace.capture():
            with answer_trace.step(name, 'tool'):
                pass
            return [step['name'] for step in answer_trace.current()['steps']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(collect, ('tool-a', 'tool-b')))
    assert results == [['tool-a'], ['tool-b']]


def test_final_summary_has_only_allowlisted_facts_and_no_trace_response_field():
    response = {'answer_id': 'id', 'answer': 'private answer', 'message': 'private question',
                'guest_session': 'session-secret', 'evidence': [{'chunk_id': 'c5', 'row': 'r3', 'column': 'worker',
                                                                  'value': '3', 'quote': 'private quote'}],
                'inputs': [{'name': 'volume', 'value': 10, 'unit': 'm3'}, {'name': 'memo', 'value': 'private site'}],
                'result': {'lines': [{'name': 'worker', 'value': '3', 'unit': 'person', 'source': 'p185-t0'}]},
                'search': {'method': 'bm25', 'fallback_reason': None, 'query': 'private question'}}
    summary = answer_runs._final_summary(response)
    assert summary['evidence'][0]['row'] == 'r3'
    assert summary['numeric_inputs'][0]['value'] == 10
    assert 'private' not in str(summary) and 'session-secret' not in str(summary)
    assert 'answer' not in summary and 'execution' not in summary


def test_historical_answer_does_not_get_synthetic_steps():
    old = {'answer_id': 'historic-id', 'status': 'ANSWERED'}
    assert answer_runs._final_summary(old)['evidence'] == []
