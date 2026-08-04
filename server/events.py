#!/usr/bin/env python3
"""Event logging and milestone management."""

import json
import time
import threading

from config import LOG_FILE, MILESTONE_FILE, EVENT_LOG_MAX


# ─── Event log ────────────────────────────────────────────────
event_log: list[dict] = []
event_log_lock = threading.Lock()


def log_event(event_type: str, message: str, detail: str = '', ui_message: str | None = None):
    """
    Record an event.
    - `message`: full detail written to GenSci.log
    - `ui_message`: short version shown in the UI Update Log (falls back to message)
    - `detail`: extra context for the UI tooltip
    """
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    entry = {
        'time': ts,
        'type': event_type,
        'message': ui_message or message,
        'detail': detail,
    }
    # UI in-memory log (concise)
    with event_log_lock:
        event_log.insert(0, entry)
        if len(event_log) > EVENT_LOG_MAX:
            event_log.pop()
    # File log (full detail, JSONL)
    file_entry = {
        'time': ts,
        'type': event_type,
        'message': message,
        'detail': detail,
    }
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(file_entry) + '\n')
    except Exception:
        pass


# ─── Development Milestones ───────────────────────────────────
MILESTONES: list[dict] = []
milestones_lock = threading.Lock()

_INITIAL_MILESTONES = [
    ('Update Log shows development milestones', 'Changelog-style records replace missing version control'),
    ('Blood & Intestine dataset cards merged', '11 core datasets in 4x3 grid'),
    ('Added missing organs: Eye, Thyroid, Heart, Pancreas, Bladder, Reproductive', 'Matched GEPIA reference organ coverage'),
    ('Only real filesystem data shown (no hardcoded fallbacks)', 'Tooltip displays only backend-scanned dataset counts'),
    ('Liver / Stomach left-right positions corrected', 'Liver on viewer-left (person-right), Stomach on viewer-right (person-left)'),
    ('Breast position corrected', 'Moved from upper chest to anatomically correct position'),
    ('SVG precise organ outlines replace rectangles', 'Anatomical Bezier curve paths on body diagram'),
    ('Dynamic cellxgene VIP analysis launcher', 'One-click launch with lifecycle management'),
    ('Real-time filesystem dataset scanner', 'Auto-detects .h5ad files in data directories'),
    ('Project initialized - GenSci single-cell analysis platform', 'React 19 + Vite 8 + Python API'),
]


def _seed_milestones():
    """Load milestones from disk, or seed initial milestones."""
    if MILESTONE_FILE.exists():
        try:
            with open(MILESTONE_FILE) as f:
                existing = json.load(f)
            if existing:
                MILESTONES.extend(existing)
                return
        except Exception:
            pass
    # Otherwise seed the initial milestones
    now = time.time()
    for i, (msg, detail) in enumerate(_INITIAL_MILESTONES):
        t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now - i))
        MILESTONES.append({
            'time': t,
            'type': 'milestone',
            'message': msg,
            'detail': detail,
        })
    try:
        MILESTONE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MILESTONE_FILE, 'w') as f:
            json.dump(MILESTONES, f, indent=2)
    except Exception:
        pass


_seed_milestones()
