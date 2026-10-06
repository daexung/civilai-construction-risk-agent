"""Production startup must finish preparation before serving any request."""
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['AGENT_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import backend.api.main as api


class ProductionStartupChecks(unittest.TestCase):
    def test_server_does_not_open_until_preparation_finishes(self):
        started, release, opened = threading.Event(), threading.Event(), threading.Event()
        result = []
        def prepare():
            started.set()
            if not release.wait(5):
                raise TimeoutError('test preparation gate')
        def serve():
            try:
                with TestClient(api.app) as client:
                    opened.set()
                    result.append(client.get('/api/ready').json())
            except Exception as error:
                result.append(error)
        with patch.object(api.runtime, 'validate_production'), patch.object(api.runtime, 'production', return_value=True), \
                patch.object(api.chat_storage, 'setup'), patch.object(api, 'prepare_citations', side_effect=prepare), \
                patch.object(api, 'get_search'), patch.object(api, 'load_specs'), patch.object(api.accounts, 'recover'), \
                patch.dict(os.environ, {'AGENT_LLM': 'off'}):
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                self.assertFalse(opened.wait(0.1))
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [{'status': 'ok'}])
            self.assertFalse(api._LIFESPAN_ACTIVE)

    def test_failed_preparation_aborts_production_startup(self):
        with patch.object(api.runtime, 'validate_production'), patch.object(api.runtime, 'production', return_value=True), \
                patch.object(api.chat_storage, 'setup'), \
                patch.object(api, 'prepare_citations', side_effect=FileNotFoundError('test missing PDF')), \
                patch.dict(os.environ, {'AGENT_LLM': 'off'}):
            with self.assertRaisesRegex(RuntimeError, 'Service preparation failed during startup'):
                with TestClient(api.app):
                    self.fail('Failed production startup must not accept requests')
        self.assertFalse(api._LIFESPAN_ACTIVE)


if __name__ == '__main__':
    unittest.main()
