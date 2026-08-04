#!/usr/bin/env python3
"""Evaluator — quality assessment for tool results + Monitor logging.

Evaluator: After each tool result, assesses if the information is sufficient.
Monitor:   Logs latency, token count, tool calls to SQLite.
"""
from __future__ import annotations
import json, sqlite3, threading, time
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── Evaluator ──────────────────────────────────────────────────

EVAL_SYSTEM_PROMPT = """You are a quality evaluator for a research agent.
Given the user's original question and the search results obtained so far,
decide if the information is sufficient to answer the question.

Output ONLY valid JSON:
- If sufficient: {"sufficient": true, "reason": "why"}
- If NOT sufficient: {"sufficient": false, "reason": "what's missing", "next_query": "suggested next search"}
"""


def evaluate(user_query: str, tool_results: list[dict],
             context: str = '',
             api_key: str = '', base_url: str = '', model: str = '') -> dict:
    """Evaluate if tool results are sufficient to answer the query.

    Uses heuristic (count results) by default. Falls back to LLM if api_key provided.
    Returns: {'sufficient': bool, 'reason': str, 'next_query': str|None}
    """
    if not tool_results:
        return {'sufficient': False, 'reason': 'No results yet',
                'next_query': user_query[:200]}

    # Heuristic: count total result items
    total_items = 0
    for tr in tool_results:
        result = tr.get('result', {})
        if isinstance(result, dict):
            total_items += len(result.get('results', []))
    if total_items >= 5:
        return {'sufficient': True, 'reason': f'Collected {total_items} results across {len(tool_results)} searches'}

    # LLM evaluation if api_key provided
    if api_key and base_url:
        summary_parts = []
        for tr in tool_results[-3:]:
            name = tr.get('name', 'unknown')
            result = tr.get('result', {})
            if isinstance(result, dict):
                flat = {k: (str(v)[:100] if isinstance(v, str) else v)
                        for k, v in result.items()}
                summary_parts.append(f'{name}: {json.dumps(flat, ensure_ascii=False)[:500]}')
            elif isinstance(result, str):
                summary_parts.append(f'{name}: {result[:300]}')

        if summary_parts:
            prompt_text = f'User question: {user_query}\n\nResults obtained:\n' + '\n'.join(summary_parts)
            if context:
                prompt_text = f'Context: {context}\n\n' + prompt_text
            messages = [
                {'role': 'system', 'content': EVAL_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt_text},
            ]
            result = _call_eval_llm(messages, api_key, base_url, model)
            if result:
                try:
                    return _parse_eval_json(result)
                except (json.JSONDecodeError, ValueError):
                    pass

    return {'sufficient': total_items >= 3, 'reason': f'Heuristic: {total_items} items from {len(tool_results)} searches'}


def _call_eval_llm(messages: list[dict],
                   api_key: str = '', base_url: str = '', model: str = '') -> str:
    if not api_key or not base_url:
        return ''
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps({
        'model': model or 'deepseek-chat', 'messages': messages,
        'temperature': 0.2, 'max_tokens': 256,
    }).encode()
    try:
        req = Request(url, data=body, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        })
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get('choices', [{}])[0].get('message', {}).get('content', '')
    except (URLError, json.JSONDecodeError) as e:
        print(f'[evaluator] Error: {e}')
        return ''


def _parse_eval_json(text: str) -> dict:
    text = text.strip()
    if text.startswith('```'):
        start = text.find('{')
        text = text[start:] if start >= 0 else text
        end = text.rfind('}')
        text = text[:end + 1] if end >= 0 else text
    text = text.removeprefix('```json').removesuffix('```').strip()
    return json.loads(text)


# ── Monitor ────────────────────────────────────────────────────

class Monitor:
    """Lightweight metrics logger — records latency, tokens, tool calls to SQLite."""

    def __init__(self, db_path: str = '/tmp/gensci_monitor.db'):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute('PRAGMA journal_mode=WAL')
        return self._local.conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            query TEXT,
            intent TEXT,
            tool_calls INTEGER DEFAULT 0,
            iterations INTEGER DEFAULT 0,
            total_latency_ms REAL DEFAULT 0,
            plan_used INTEGER DEFAULT 0,
            evaluator_used INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ok')''')
        conn.commit()
        conn.close()

    def log_session(self, session_id: str, query: str = '', intent: str = '',
                    tool_calls: int = 0, iterations: int = 0,
                    latency_ms: float = 0.0, plan_used: bool = False,
                    evaluator_used: bool = False, status: str = 'ok') -> None:
        self._conn.execute(
            '''INSERT INTO sessions
               (session_id, timestamp, query, intent, tool_calls, iterations,
                total_latency_ms, plan_used, evaluator_used, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (session_id, datetime.now().isoformat(), query[:200] if query else '',
             intent or '', tool_calls, iterations, round(latency_ms, 1),
             1 if plan_used else 0, 1 if evaluator_used else 0, status))
        self._conn.commit()


# Global monitor instance
_monitor: Monitor | None = None


def get_monitor() -> Monitor:
    global _monitor
    if _monitor is None:
        _monitor = Monitor()
    return _monitor


def log_request(session_id: str, query: str = '', intent: str = '',
                tool_calls: int = 0, iterations: int = 0,
                latency_ms: float = 0.0, plan_used: bool = False,
                status: str = 'ok') -> None:
    """Shorthand for logging a request."""
    try:
        m = get_monitor()
        m.log_session(session_id, query=query, intent=intent,
                      tool_calls=tool_calls, iterations=iterations,
                      latency_ms=latency_ms, plan_used=plan_used,
                      status=status)
    except Exception as e:
        print(f'[monitor] Log error: {e}')
