#!/usr/bin/env python3
"""HTTP request handler for the GenSci API."""

import json, sys, time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
import mimetypes, os
from pathlib import Path
import numpy as np
from routes import ROUTES

DATA_DIRS = None

# ─── Rate limiting ──────────────────────────────────────────
_RATE_WINDOW = 60
_RATE_MAX = 100
_rates: dict[str, list[float]] = defaultdict(list)

def _rate_allowed(ip: str) -> bool:
    now = time.time()
    w = _rates[ip]
    while w and w[0] < now - _RATE_WINDOW:
        w.pop(0)
    if len(w) >= _RATE_MAX:
        return False
    w.append(now)
    return True


class _NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles numpy types (bool_, int_, float_)."""
    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class APIHandler(BaseHTTPRequestHandler):

    def _cors(self):
        origin = self.headers.get('Origin', '')
        allowed = getattr(self, '_allowed_origins', [])
        if origin in allowed:
            self.send_header('Access-Control-Allow-Origin', origin)
        else:
            self.send_header('Access-Control-Allow-Origin', '')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, status=200):
        body = json.dumps(data, cls=_NumpyEncoder).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message, status=400):
        self._json({'error': message}, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _serve_static(self, path: str):
        """Serve static files from the dist/ directory."""
        if path == '/':
            path = '/index.html'
        static_dir = Path(__file__).resolve().parent.parent / 'dist'
        file_path = static_dir / path.lstrip('/')
        if not file_path.exists() or not file_path.is_file():
            # SPA fallback: serve index.html for any unmatched route
            file_path = static_dir / 'index.html'
        if not file_path.exists():
            self._json({'error': 'Not found'}, 404)
            return
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = 'application/octet-stream'
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, mime: str = 'application/octet-stream'):
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def _log_request(self, status: int):
        ip = self.client_address[0]
        path = self.path
        print(f'[GenSci] {ip} {self.command} {path} -> {status}', file=sys.stderr)

    def do_GET(self):
        client_ip = self.client_address[0]
        if not _rate_allowed(client_ip):
            self._json({'error': 'Rate limit exceeded'}, 429)
            self._log_request(429)
            return
        parsed = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        handler = ROUTES.get(('GET', parsed.path))
        if handler:
            self._log_request(200)
            return handler(self, q)
        self._serve_static(parsed.path)

    def do_POST(self):
        client_ip = self.client_address[0]
        if not _rate_allowed(client_ip):
            self._json({'error': 'Rate limit exceeded'}, 429)
            self._log_request(429)
            return
        parsed = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._log_request(400)
            return self._json({'error': 'Invalid JSON'}, 400)

        handler = ROUTES.get(('POST', parsed.path))
        if handler:
            is_json_body = parsed.path.startswith('/api/llm/') or parsed.path in ('/api/milestone', '/api/heartbeat', '/api/raw-expression')
            self._log_request(200)
            return handler(self, data if is_json_body else q)
        self._log_request(404)
        self._json({'error': 'Not found'}, 404)
