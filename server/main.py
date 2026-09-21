#!/usr/bin/env python3
"""
GenSci v2 API Server
- Serves single-cell dataset API on :6000
- Also serves built frontend from dist/ (same port)
- Multi-threaded for concurrent requests
- Auto-scans Data/ for .h5ad files

Run: python3 server/main.py [--port 6000]
"""

import os
os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'
# 这里曾有一行 `os.environ.setdefault('OLLAMA_MODELS', '/home/mengguofeng/.ollama/models')`，
# 已删除，原因有三，任一都足够：
#   1. 它指向别人的家目录，且是 CLAUDE.md 点名的「依赖特定机器的路径」。
#   2. 全仓库搜索 `OLLAMA_MODELS` 只有这一处 —— 没有任何代码读它。
#   3. 该变量是 ollama **守护进程**的启动参数，由 systemd 那侧设置才有效；
#      本进程 setdefault 只写进自己的 environ，对已在运行的 ollama 服务毫无影响，
#      本进程也没有 spawn 过 `ollama serve`。也就是说这行从来没有任何效果。
# 如果将来确实要让 GenSci 自带一份模型目录，正确的做法是启动 ollama 时用环境变量，
# 而不是在 API 进程里设置。

import sys
import time as _time
from http.server import ThreadingHTTPServer
from threading import Thread

from config import HOST, API_PORT, DATA_DIRS, SCAN_INTERVAL, ALLOWED_ORIGINS
from scanner import scan_datasets, scanner_loop, datasets
from handler import APIHandler


def get_host_ip() -> str:
    """Get the server's external IP for display."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.243.163.51', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def main():
    # Start initial scan in background — HTTP server starts immediately
    print(f'[GenSci] Starting background scan...')
    def _initial_scan():
        t0 = _time.time()
        scan_datasets()
        elapsed = _time.time() - t0
        print(f'[GenSci] Initial scan complete ({elapsed:.1f}s, {len(datasets)} datasets)')
    Thread(target=_initial_scan, daemon=True).start()

    # Start periodic scanner loop
    Thread(target=scanner_loop, daemon=True).start()

    # Inject CORS allowed origins into handler
    APIHandler._allowed_origins = ALLOWED_ORIGINS

    # Start HTTP server (serves both API and frontend)
    server = ThreadingHTTPServer((HOST, API_PORT), APIHandler)
    ip = get_host_ip()
    print(f'[GenSci] Server running at:')
    print(f'  http://{ip}:{API_PORT}          (API)')
    print(f'  http://{ip}:{API_PORT}/         (Frontend)')
    print(f'  Watching {len(DATA_DIRS)} dir(s), refresh every {SCAN_INTERVAL}s')
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[GenSci] Shutting down...')
        server.shutdown()


if __name__ == '__main__':
    main()
