#!/usr/bin/env python3
"""HTTP request handler for the GenSci API."""

import json, sys, threading, time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import mimetypes, os
from pathlib import Path
import numpy as np
from routes import ROUTES

DATA_DIRS = None

# ─── Rate limiting ──────────────────────────────────────────
_RATE_WINDOW = 60
_RATE_MAX = 100
# 普通 dict，**不是** defaultdict。原先 `w = _rates[ip]` 是 defaultdict 的下标
# 访问 —— 取不到就插入一个空 list。于是每个「历史上出现过一次」的 IP 都永久
# 留下一个键：清理循环只 pop 时间戳，从不删键。内存因而随「累计见过多少不同
# 的源地址」单调增长，与当前请求量无关（服务监听 :6001 且对公网可达）。
_rates: dict[str, list[float]] = {}
# ThreadingHTTPServer 每请求一线程，而 _rate_allowed 是「读 len → 判断 → append」
# 的读-改-写：不加锁时多个线程能同时读到 len(w) == _RATE_MAX - 1 而各 append
# 一次，上限被击穿。（实测 32 线程并发下临界区重叠度可达 32。）
_rates_lock = threading.Lock()
_rates_swept_at = 0.0   # 上次全表清理的时刻


def _sweep_stale_ips(cutoff: float, now: float) -> None:
    """删掉窗口外、且已不再使用的 IP。调用方必须已持有 _rates_lock。

    只在距上次清理 ≥ _RATE_WINDOW 时真的遍历，于是 O(活跃 IP 数) 的扫描被摊到
    每分钟一次，而不是每请求一次。

    只删 `v[-1] < cutoff`（该 IP 最后一条记录已在窗口外）的键 —— 窗口内还在
    访问的 IP 一个都不能动：删掉它等于把计数清零，反而是放宽限流。
    """
    global _rates_swept_at
    if now - _rates_swept_at < _RATE_WINDOW:
        return
    _rates_swept_at = now
    for k in [k for k, v in _rates.items() if not v or v[-1] < cutoff]:
        del _rates[k]


def _rate_allowed(ip: str) -> bool:
    now = time.time()
    cutoff = now - _RATE_WINDOW
    with _rates_lock:
        _sweep_stale_ips(cutoff, now)
        w = _rates.get(ip) or []
        while w and w[0] < cutoff:
            w.pop(0)
        if len(w) >= _RATE_MAX:
            return False
        w.append(now)
        # 只在放行时落键：于是「键存在」⟺「该 IP 在窗口内至少被放行过一次」，
        # 被拒的 IP 不会白占一个条目。
        _rates[ip] = w
        return True


def post_route_delivers_json_body(path: str) -> bool:
    """POST 路由拿到的是解析好的 JSON body，还是 query string 字典？

    抽成模块级函数（而不是内联在 do_POST 里）是为了能被测试**导入并直接调用**。
    测试里再抄一份的话，两份会各自漂移 —— 抄写的那份永远陪着自己写的规则，
    测不到 handler 真正在跑的规则。`test_handler_post_routes.py` 就是靠调用
    这个函数，才能发现「新加了 POST 路由但这里没登记」。

    `/api/drug/pipeline/stream` 曾因漏登记而拿到空 dict，端点与校验都在、
    却永远报「query required」—— 那种失败很难从错误信息反推回这里。
    """
    return (
        path.startswith('/api/llm/')
        or path.startswith('/api/drug/')
        or path in ('/api/milestone', '/api/heartbeat', '/api/raw-expression')
    )


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
            # 规则见 post_route_delivers_json_body() —— 抽出去是为了让测试
            # 能直接调用同一份实现，而不是抄一份跟着漂移。
            self._log_request(200)
            return handler(self, data if post_route_delivers_json_body(parsed.path) else q)
        self._log_request(404)
        self._json({'error': 'Not found'}, 404)
