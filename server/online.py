"""Online user tracking via heartbeat.

Thread-safe dict of {session_id: last_heartbeat_timestamp}.
Stale entries (>30s) are cleaned on each count_online() call.
"""
from __future__ import annotations
import time
import threading

_online: dict[str, float] = {}
_lock = threading.Lock()
_TIMEOUT = 30  # seconds — session considered offline after this


def heartbeat(session_id: str) -> None:
    """Record a heartbeat for the given session."""
    with _lock:
        _online[session_id] = time.time()


def count_online() -> int:
    """Return number of active sessions (cleans stale entries)."""
    now = time.time()
    cutoff = now - _TIMEOUT
    with _lock:
        stale = [sid for sid, ts in _online.items() if ts < cutoff]
        for sid in stale:
            del _online[sid]
        return len(_online)
