"""Start one API worker on the port supplied by the hosting platform."""
import os
import sys

port = int(os.environ.get('PORT', '8080'))
if not 1 <= port <= 65535:
    raise SystemExit('PORT must be between 1 and 65535')
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'backend.api.main:app',
                         '--host', '0.0.0.0', '--port', str(port), '--workers', '1',
                         '--no-proxy-headers'])
