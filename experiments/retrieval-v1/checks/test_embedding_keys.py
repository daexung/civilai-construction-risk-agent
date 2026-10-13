"""Offline checks for key routing. No real credentials or API requests."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.shared import embedding as em


class QuotaError(Exception):
    code = 429


class KeyRoutingTests(unittest.TestCase):
    def test_both_environment_and_file_credentials(self):
        config = em.EmbeddingSettings('studio', 'test', 3)
        fake_env = 'GEMINI_API_KEY=file-primary\nGEMINI_API_KEY_SEC=file-second\n'
        with patch.object(Path, 'exists', return_value=True), patch.object(Path, 'read_text', return_value=fake_env):
            with patch.dict(em.os.environ, {'GEMINI_API_KEY': 'env-primary'}, clear=True):
                self.assertEqual(em.api_keys(config), ['env-primary', 'file-second'])
            with patch.dict(em.os.environ, {'GEMINI_API_KEY_SEC': 'file-primary'}, clear=True):
                self.assertEqual(em.api_keys(config), ['file-primary'])

    def pool(self, first, second):
        return em._StudioEmbeddingClient([SimpleNamespace(models=first), SimpleNamespace(models=second)])

    def test_alternates_without_duplicate_requests(self):
        first, second = Mock(), Mock()
        first.embed_content.return_value = 'first'
        second.embed_content.return_value = 'second'
        pool = self.pool(first, second)
        self.assertEqual([pool.embed_content(contents='input') for _ in range(3)], ['first', 'second', 'first'])
        self.assertEqual(first.embed_content.call_count, 2)
        self.assertEqual(second.embed_content.call_count, 1)

    def test_quota_falls_back_with_unchanged_input(self):
        first, second = Mock(), Mock()
        first.embed_content.side_effect = QuotaError()
        second.embed_content.return_value = 'ok'
        self.assertEqual(self.pool(first, second).embed_content(contents=['one'], model='test'), 'ok')
        self.assertEqual(first.embed_content.call_args, second.embed_content.call_args)

    def test_two_quota_failures_stop(self):
        first, second = Mock(), Mock()
        first.embed_content.side_effect = QuotaError()
        second.embed_content.side_effect = QuotaError()
        with self.assertRaises(QuotaError):
            self.pool(first, second).embed_content(contents='input')
        self.assertEqual(first.embed_content.call_count, 1)
        self.assertEqual(second.embed_content.call_count, 1)

    def test_other_errors_do_not_repeat_input(self):
        first, second = Mock(), Mock()
        first.embed_content.side_effect = ValueError('invalid input')
        with self.assertRaises(ValueError):
            self.pool(first, second).embed_content(contents='input')
        second.embed_content.assert_not_called()

    def test_single_key_is_supported(self):
        model = Mock()
        model.embed_content.return_value = 'ok'
        pool = em._StudioEmbeddingClient([SimpleNamespace(models=model)])
        self.assertEqual(pool.embed_content(contents='one'), 'ok')
        self.assertEqual(pool.embed_content(contents='two'), 'ok')


if __name__ == '__main__':
    unittest.main()
