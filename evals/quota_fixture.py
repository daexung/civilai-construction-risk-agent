"""Isolate transcript/checkpoint tests from the separate durable quota suite."""
from contextlib import contextmanager, nullcontext
from unittest.mock import patch


@contextmanager
def unrestricted_quota():
    # Only tests use this dependency fixture. Production has no disable switch.
    with patch('backend.api.usage_limits.processing', return_value=nullcontext((None, 'fixture', False))), \
            patch('backend.api.usage_limits.consume', return_value={}), \
            patch('backend.api.usage_limits.status', return_value={}):
        yield
