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
os.environ.setdefault('OLLAMA_MODELS', '/home/mengguofeng/.ollama/models')

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
    # Synchronous initial scan — blocks HTTP server until datasets are ready
    print(f'[GenSci] Scanning datasets...')
    t0 = _time.time()
    scan_datasets()
    elapsed = _time.time() - t0
    print(f'[GenSci] Initial scan complete ({elapsed:.1f}s, {len(datasets)} datasets)')

    # Start background scanner loop (periodic refresh every {SCAN_INTERVAL}s)
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
