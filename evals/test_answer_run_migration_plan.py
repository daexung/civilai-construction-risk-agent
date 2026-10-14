"""Planning a fresh database must include both migrations without modifying it."""
from unittest.mock import patch
import pytest
from deploy import apply_answer_runs as migration


def test_fresh_database_plans_both_in_order():
    with patch.object(migration, '_columns', return_value=set()):
        pending = [version for version, _ in migration.MIGRATIONS
                   if not migration._is_applied(None, version)]
    assert pending == ['20261014000100', '20261014000200']


def test_orphan_steps_are_rejected():
    with patch.object(migration, '_columns', side_effect=lambda _, name: {'id'} if name == 'answer_run_steps' else set()):
        with pytest.raises(RuntimeError, match='partial state'):
            migration._is_applied(None, '20261014000200')
