"""Offline checks for the IAM-protected Vercel proxy IP boundary."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException, Request
from backend.api.client_ip import client_ip


def request(headers):
    return Request({'type': 'http', 'client': ('127.0.0.1', 1234),
                    'headers': [(key.encode(), value.encode()) for key, value in headers.items()]})


class ClientIPChecks(unittest.TestCase):
    def test_local_ignores_spoofed_headers(self):
        with patch.dict(os.environ, {'CLIENT_IP_SOURCE': 'direct'}):
            self.assertEqual(client_ip(request({'x-poomsemi-client-ip': 'spoof'})), '127.0.0.1')

    def test_vercel_normalizes_ip_and_ignores_generic_forwarded_header(self):
        with patch.dict(os.environ, {'CLIENT_IP_SOURCE': 'vercel'}):
            self.assertEqual(client_ip(request({'x-poomsemi-client-ip': '::ffff:203.0.113.2',
                                               'x-forwarded-for': 'spoof'})), '203.0.113.2')

    def test_vercel_fails_closed_for_missing_or_invalid_ip(self):
        with patch.dict(os.environ, {'CLIENT_IP_SOURCE': 'vercel'}):
            for value in ['', 'spoof', '203.0.113.1, 203.0.113.2', 'fe80::1%eth0']:
                with self.assertRaises(HTTPException) as error:
                    client_ip(request({'x-poomsemi-client-ip': value}))
                self.assertEqual(error.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
