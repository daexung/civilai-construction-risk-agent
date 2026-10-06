"""Question resend/edit must start a new run even while the graph awaits conditions."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ['AGENT_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langgraph.types import Command
from fastapi.testclient import TestClient
from backend.api import main as api


class QuestionRestartTests(unittest.TestCase):
    def graph(self):
        graph = Mock()
        graph.get_state.return_value = SimpleNamespace(next=('ask',), values={
            'route': 'estimate', 'inputs': {'volume': '260'}, 'statement': {}, 'spec_id': ''})
        return graph

    @patch.object(api, '_build_response', side_effect=lambda thread, state: {'thread_id': thread})
    def test_restart_keeps_thread_and_starts_new_query_with_empty_conditions(self, _response):
        graph = self.graph()
        response = api._chat_response(api.ChatRequest(thread_id='same-thread', message='자동문 3개소', restart=True), graph)
        initial = graph.invoke.call_args.args[0]
        self.assertIsInstance(initial, dict)
        self.assertEqual(initial['query'], '자동문 3개소')
        self.assertEqual(initial['inputs'], {})
        self.assertEqual(response['thread_id'], 'same-thread')

    @patch.object(api, '_build_response')
    def test_normal_condition_answer_still_resumes(self, _response):
        graph = self.graph()
        api._chat_response(api.ChatRequest(thread_id='same-thread', message='32m'), graph)
        self.assertIsInstance(graph.invoke.call_args.args[0], Command)

    def test_restart_requires_message_and_rejects_mixed_condition_requests(self):
        with patch.object(api.chat_storage, 'identity', return_value=None):
            client = TestClient(api.app)
            for payload in [{'restart': True, 'answers': {'pump_size': '32m'}},
                            {'restart': True, 'message': '질문', 'conditions': {}},
                            {'restart': True, 'message': '질문', 'answers': {}}]:
                self.assertEqual(client.post('/api/chat', json=payload).status_code, 422)


if __name__ == '__main__':
    unittest.main()
