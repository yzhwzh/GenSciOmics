#!/usr/bin/env python3
"""LLM Proxy — thin wrapper around the Agent Engine.

Compatibility shim: maintains the same API contract as V3,
but delegates all logic to the agent pipeline.
Supports both OpenAI and Anthropic API formats (auto-detected).
"""
from __future__ import annotations
import json, re as _re
from urllib.request import Request as _Req, urlopen as _urlopen
from urllib.error import URLError as _URLErr
from agent import process_chat as _agent_process_chat

DEFAULT_BASE_URL = 'http://llm-gateway.ai.dgtmeta.com/v1'
DEFAULT_MODEL = 'Qwen3.5-397B-A17B-FP8-Thinking'
DEFAULT_TEMPERATURE = 0.7
MAX_TOOL_ITERATIONS = 50

# LITERATURE_SYSTEM_PROMPT removed — agent pipeline handles prompt generation via assemble_prompt()


# ── API format detection & helpers ─────────────────────────────

def _api_url(base_url: str) -> tuple[str, str]:
    if 'anthropic' in base_url.lower():
        return (base_url.rstrip('/'), 'anthropic')
    return (base_url.rstrip('/'), 'openai')


def _build_anthropic_request(messages, tools, model, api_key, base_url, temperature, stream=True):
    """Build Anthropic-format request. Returns (url, body, headers).

    Anthropic requires:
    - Messages: user, assistant (with tool_use), user (with tool_results), assistant...
    - All tool_results must be in a SINGLE user message following the assistant.
    """
    system_parts = []
    anth_msgs = []
    # Buffer for consecutive tool messages (must merge into one user message)
    tool_buf = []

    def _flush_tools():
        if not tool_buf:
            return
        content = []
        for tm in tool_buf:
            raw = tm.get('content', '')
            try:
                cdata = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                cdata = raw
            content.append({
                'type': 'tool_result',
                'tool_use_id': tm.get('tool_call_id', ''),
                'content': str(cdata)[:50000],
            })
        anth_msgs.append({'role': 'user', 'content': content})
        tool_buf.clear()

    for m in messages:
        role = m.get('role', '')
        if role == 'system':
            system_parts.append(m.get('content', ''))
        elif role == 'tool':
            tool_buf.append(m)
        elif role in ('user', 'assistant'):
            _flush_tools()
            content = []
            text = m.get('content', '')
            if text:
                content.append({'type': 'text', 'text': text})
            elif m.get('tool_calls'):
                content.append({'type': 'text', 'text': ' '})  # Anthropic requires non-empty content
            for tc in m.get('tool_calls', []):
                fn = tc.get('function', {})
                try:
                    inp = json.loads(fn.get('arguments', '{}'))
                except json.JSONDecodeError:
                    inp = {}
                content.append({'type': 'tool_use', 'id': tc.get('id', ''),
                                'name': fn.get('name', ''), 'input': inp})
            anth_msgs.append({'role': role, 'content': content})
    _flush_tools()
    body = {'model': model, 'max_tokens': 4096, 'stream': stream, 'messages': anth_msgs}
    if system_parts:
        body['system'] = '\n'.join(system_parts)
    if tools:
        at = []
        for t in tools:
            fn = t.get('function', {})
            at.append({'name': fn.get('name', ''), 'description': fn.get('description', ''),
                       'input_schema': fn.get('parameters', {})})
        body['tools'] = at
    url = f'{base_url}/v1/messages'
    headers = {'Content-Type': 'application/json', 'x-api-key': api_key,
               'anthropic-version': '2023-06-01'}
    return url, body, headers


def _stream_sse(messages, tools, api_key, model, base_url, temperature, api_type):
    """Unified SSE reader — yields OpenAI-style delta chunks.

    Retries on transient server errors (502/503/504) with exponential backoff.
    对齐 Claude Code: _call_llm() 已有相同重试逻辑，streaming 路径补上。
    """
    import time as _time
    max_retries = 2
    retry_delay = 1.0

    for attempt in range(max_retries + 1):
        if api_type == 'anthropic':
            url, body, headers = _build_anthropic_request(
                messages, tools, model, api_key, base_url, temperature, stream=True)
        else:
            url = f'{base_url}/chat/completions'
            body = {'model': model, 'messages': messages, 'temperature': temperature, 'stream': True}
            if tools:
                body['tools'] = tools
                body['tool_choice'] = 'auto'
            headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

        if 'localhost' in url or '127.0.0.1' in url:
            import urllib.request as _ur2
            _opener = _ur2.build_opener(_ur2.ProxyHandler({})).open
        else:
            _opener = _urlopen
        req = _Req(url, data=json.dumps(body).encode(), headers=headers, method='POST')
        try:
            with _opener(req, timeout=120) as resp:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    ld = line.decode('utf-8', errors='replace').rstrip('\r\n')
                    if not ld:
                        continue
                    if api_type == 'anthropic':
                        if not ld.startswith('data: '):
                            continue
                        try:
                            data = json.loads(ld[6:])
                        except json.JSONDecodeError:
                            continue
                        ev = data.get('type', '')
                        if ev == 'content_block_start':
                            block = data.get('content_block', {})
                            if block.get('type') == 'text':
                                yield {'choices': [{'delta': {'content': block.get('text', '')}}]}
                            elif block.get('type') == 'tool_use':
                                idx_val = data.get('index', 0)
                                yield {'choices': [{'delta': {'tool_calls': [{
                                    'index': idx_val,
                                    'id': block.get('id', ''),
                                    'type': 'function',
                                    'function': {'name': block.get('name', ''), 'arguments': ''},
                                }]}}]}
                        elif ev == 'content_block_delta':
                            delta = data.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                yield {'choices': [{'delta': {'content': delta.get('text', '')}}]}
                            elif delta.get('type') == 'input_json_delta':
                                yield {'choices': [{'delta': {'tool_calls': [{
                                    'index': data.get('index', 0),
                                    'function': {'arguments': delta.get('partial_json', '')},
                                }]}}]}
                    else:
                        if not ld.startswith('data: '):
                            continue
                        ds = ld[6:].strip()
                        if ds == '[DONE]':
                            break
                        try:
                            yield json.loads(ds)
                        except json.JSONDecodeError:
                            continue
            return  # Success — exit retry loop
        except _URLErr as e:
            code = getattr(e, 'code', 0)
            if code in (502, 503, 504) and attempt < max_retries:
                _time.sleep(retry_delay * (2 ** attempt))
                continue
            err = ''
            try:
                err = e.read().decode('utf-8', errors='replace') if hasattr(e, 'read') else str(e)
            except Exception:
                err = str(e)
            err = _re.sub(r'sk-[A-Za-z0-9]{10,}', 'sk-***', err)
            yield {'error': err[:300]}
            return
        except Exception as e:
            err_str = str(e)[:200]
            is_transient = any(x in err_str.lower() for x in ('timeout', 'connection reset', 'connection refused', 'eof'))
            if is_transient and attempt < max_retries:
                _time.sleep(retry_delay * (2 ** attempt))
                continue
            yield {'error': err_str[:300]}
            return
    # All retries exhausted
    yield {'error': 'LLM API unavailable after retries'}


# ── Public API ────────────────────────────────────────────────

def process_chat(messages, real_path, api_key, model=DEFAULT_MODEL,
                 base_url=DEFAULT_BASE_URL, temperature=DEFAULT_TEMPERATURE):
    """Process a chat request. Delegates to Agent Engine."""
    return _agent_process_chat(
        messages=messages, real_path=real_path, api_key=api_key,
        model=model, base_url=base_url, temperature=temperature,
        max_iterations=MAX_TOOL_ITERATIONS,
    )


def process_chat_streaming(messages, real_path, api_key, model=DEFAULT_MODEL,
                            base_url=DEFAULT_BASE_URL, temperature=DEFAULT_TEMPERATURE):
    """Streaming chat — delegates to agent.process_chat_streaming()."""
    from agent import process_chat_streaming as _stream
    # Cast to strings for json serialization
    for event in _stream(
        messages=messages, real_path=real_path, api_key=api_key,
        model=model, base_url=base_url, temperature=temperature,
        max_iterations=MAX_TOOL_ITERATIONS,
    ):
        yield {'event': event['event'], 'data': json.dumps(event['data'], ensure_ascii=False, default=str)}


def process_literature_chat_streaming(messages, api_key, context='',
                                       model=DEFAULT_MODEL,
                                       base_url=DEFAULT_BASE_URL,
                                       temperature=DEFAULT_TEMPERATURE):
    """Literature streaming — delegates to agent.process_chat_streaming() with tools_filter."""
    from agent import process_chat_streaming as _stream
    msgs = list(messages)
    if context:
        for i, m in enumerate(msgs):
            if m.get('role') == 'user':
                msgs[i] = dict(m, content="[Tissue Context: " + context + "]\n" + m["content"])
                break
    for event in _stream(
        messages=msgs, real_path='', api_key=api_key,
        model=model, base_url=base_url, temperature=temperature,
        max_iterations=MAX_TOOL_ITERATIONS,  # Align with Free Analysis
        tools_filter=None,
    ):
        yield {'event': event['event'], 'data': json.dumps(event['data'], ensure_ascii=False, default=str)}

