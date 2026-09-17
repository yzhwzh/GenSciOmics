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

# Skill filter per omics type (used by Free Analysis tab)
OMICS_SKILL_FILTERS = {
    'BulkRNA': ['bulk-*', 'statistical-analysis'],
    'Protein': ['proteomics-*', 'protein-*', 'statistical-analysis'],
    'Drug': ['drug-*'],
}
DEFAULT_SKILL_FILTER = ['single-*', 'statistical-analysis']

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


# ── 重试判定 ────────────────────────────────────────────────────
# 2026-09-15：EGFR 流水线第 3 阶段撞上 LLM 网关的 120s 首字节超时，**一次都没重试**
# 就报了错、并因此终止了整条流水线（后续 3 个阶段一个没跑）。
#
# 两个分支漏的是同一个故障：
#   - `_URLErr` 分支原先只认 `code in (502, 503, 504)`，而连接/首字节超时被 urllib
#     包成**没有 code** 的 URLError（str = `<urlopen error timed out>`）；
#   - 下面 `except Exception` 分支的字符串匹配写的是 'timeout'，但真实文本是
#     **'timed out'**（带空格）—— 前者不是后者的子串。
#
# 于是把判定收成两个函数，两处共用，避免再各写一套。
_RETRYABLE_STATUS = frozenset({408, 425, 429})   # 4xx 里仅这三个是瞬时的
_TRANSIENT_HINTS = (
    'timed out', 'timeout', 'connection reset', 'connection refused',
    'connection aborted', 'remote end closed', 'temporarily unavailable', 'eof',
)


def _is_retryable(code: int) -> bool:
    """这次失败值不值得重试。

    - 有 HTTP code：5xx 与 408/425/429 才重试。其余 4xx 是客户端问题
      （key 写错、模型名不对），重试只会白等几秒再报同一个错。
    - 没有 HTTP code：说明请求根本没走到服务端（超时 / DNS / 连接被拒 / TLS），
      一律按瞬时故障处理 —— 这正是 2026-09-15 那次的形态。
    """
    if code:
        return code >= 500 or code in _RETRYABLE_STATUS
    return True


def _is_transient_text(err_str: str) -> bool:
    """非 HTTP 异常（socket / SSL / 解码层）的瞬时判定。"""
    low = (err_str or '').lower()
    return any(h in low for h in _TRANSIENT_HINTS)


def _stream_sse(messages, tools, api_key, model, base_url, temperature, api_type):
    """Unified SSE reader — yields OpenAI-style delta chunks.

    Retries on transient transport failures (connect/read timeout, connection
    reset, 5xx, 408/425/429) with exponential backoff.
    对齐 Claude Code: _call_llm() 已有相同重试逻辑，streaming 路径补上。
    """
    import time as _time
    max_retries = 2
    retry_delay = 1.0

    # 是否已经向调用方吐过内容。只在**首字节之前**失败才允许重试：调用方是
    # `collected_content += delta` 累加（agent/__init__.py:307），流中途重试会把
    # 整段回复从头再接一遍，用户看到重复正文。放宽重试判定后这条更容易踩到，
    # 所以在这里挡住。
    emitted = False

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
                                emitted = True
                                yield {'choices': [{'delta': {'content': block.get('text', '')}}]}
                            elif block.get('type') == 'tool_use':
                                idx_val = data.get('index', 0)
                                emitted = True
                                yield {'choices': [{'delta': {'tool_calls': [{
                                    'index': idx_val,
                                    'id': block.get('id', ''),
                                    'type': 'function',
                                    'function': {'name': block.get('name', ''), 'arguments': ''},
                                }]}}]}
                        elif ev == 'content_block_delta':
                            delta = data.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                emitted = True
                                yield {'choices': [{'delta': {'content': delta.get('text', '')}}]}
                            elif delta.get('type') == 'input_json_delta':
                                emitted = True
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
                            emitted = True
                            yield json.loads(ds)
                        except json.JSONDecodeError:
                            continue
            return  # Success — exit retry loop
        except _URLErr as e:
            code = getattr(e, 'code', 0) or 0
            if not emitted and _is_retryable(code) and attempt < max_retries:
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
            if not emitted and _is_transient_text(err_str) and attempt < max_retries:
                _time.sleep(retry_delay * (2 ** attempt))
                continue
            yield {'error': err_str[:300]}
            return
    # All retries exhausted
    yield {'error': 'LLM API unavailable after retries'}


# ── Public API ────────────────────────────────────────────────

def process_chat(messages, real_path, api_key, model=DEFAULT_MODEL,
                 base_url=DEFAULT_BASE_URL, temperature=DEFAULT_TEMPERATURE,
                 user_id=''):
    """Process a chat request. Delegates to Agent Engine."""
    return _agent_process_chat(
        messages=messages, real_path=real_path, api_key=api_key,
        model=model, base_url=base_url, temperature=temperature,
        user_id=user_id,
        max_iterations=MAX_TOOL_ITERATIONS,
    )


def process_chat_streaming(messages, real_path, api_key, model=DEFAULT_MODEL,
                            base_url=DEFAULT_BASE_URL, temperature=DEFAULT_TEMPERATURE,
                            omics_type='', user_id=''):
    """Streaming chat — delegates to agent.process_chat_streaming()."""
    from agent import process_chat_streaming as _stream
    skills_filter = OMICS_SKILL_FILTERS.get(omics_type, DEFAULT_SKILL_FILTER)
    # Cast to strings for json serialization
    for event in _stream(
        messages=messages, real_path=real_path, api_key=api_key,
        model=model, base_url=base_url, temperature=temperature,
        user_id=user_id,
        max_iterations=MAX_TOOL_ITERATIONS,
        skills_filter=skills_filter,
    ):
        yield {'event': event['event'], 'data': json.dumps(event['data'], ensure_ascii=False, default=str)}


def _sse(event: str, data) -> dict:
    """统一出口 —— 与 process_chat_streaming 一致，data 序列化成 JSON 字符串。"""
    return {'event': event, 'data': json.dumps(data, ensure_ascii=False, default=str)}


# 失败阶段进入下游 prompt 时占的那一格。**必须显式**：只是「不出现」的话，下游
# 分不清「上一环挂了」和「用户没勾这一段」，会照常交出一份读起来很完整的报告 ——
# 缺的是数据，不是措辞。drug_stages.py 的 _COMMON_RULES 第 3 条已经要求模型对本阶段
# 做不到的事直说，这里是同一件事的上游版本。
_FAILED_STAGE_NOTE = (
    '【本阶段未完成：{reason}】该阶段没有产出任何结论。'
    '下游分析不得假设本阶段已执行或已有结果；'
    '若需要覆盖这一环节，请明确注明「该环节缺失」，不要用其他阶段的结论替代。'
)


def process_drug_pipeline_streaming(query, stage_ids, api_key,
                                    model=DEFAULT_MODEL,
                                    base_url=DEFAULT_BASE_URL,
                                    temperature=DEFAULT_TEMPERATURE,
                                    real_path='',
                                    user_id=''):
    """药物发现流水线 —— 按 order 逐阶段串行，每阶段一次完整 ReAct 循环。

    为什么复用 agent.process_chat_streaming 而不另写循环：
      它已经是被真实 LLM 验证过的那一个，而 `_init_mcp_tools()` 每次调用都会跑、
      `add_tool()` 按 name **替换**而非追加（core/tool.py:21-24），所以按阶段重复
      调用是幂等的，不会堆出重复的工具 schema。本函数只做它不做的三件事：

      1. 每阶段换一份 skills_filter（阶段锁定）。
      2. 把上一阶段的**最终回复**（不是原始工具输出）截断后带进下一阶段。
      3. 给每个 SSE 事件打 stage_id，并用 stage_start / stage_done 标记推进。

    阶段锁定的强度要说清楚：skills_filter 只过滤**系统提示词里列出的 skill**，
    `get_openai_tools()` 仍返回全量工具（agent/__init__.py:256-258）。
    所以它是引导而非沙箱 —— LLM 仍可能调用本阶段外的工具，但主路径被引导到本阶段。

    real_path 可以为空：药物页默认不挂数据集，prompt.py:270 有 `if real_path:` 守卫。
    """
    import time as _time
    from agent import process_chat_streaming as _stream
    from drug_stages import resolve_stages, skills_filter_for, build_stage_message

    stages, unknown = resolve_stages(stage_ids)
    if unknown:
        yield _sse('error', {'error': f'未知阶段 id: {", ".join(unknown)}'})
        return
    if not stages:
        yield _sse('error', {'error': '至少需要选择一个阶段'})
        return
    if not (query or '').strip():
        yield _sse('error', {'error': 'query 不能为空'})
        return

    # [(阶段 label, 该阶段最终回复文本)] —— 只带结论，不带过程。
    # 失败的阶段也会往里放一条**显式的未完成标记**（见下方 _FAILED_STAGE_NOTE）：
    # 不放的话，下游 prompt 与「用户压根没勾这一段」完全无法区分。
    prior_summaries: list[tuple[str, str]] = []
    total = len(stages)
    aborted = False
    ran_stages: list[str] = []       # 正常结束的阶段
    failed_stages: list[str] = []    # 报错或静默中断的阶段

    for idx, stage in enumerate(stages, start=1):
        yield _sse('stage_start', {
            'stage_id': stage['id'], 'order': stage['order'],
            'label': stage['label'], 'index': idx, 'total': total,
        })

        message = build_stage_message(stage, query, prior_summaries)
        final_text = ''
        saw_done = False
        error_msg = ''
        _t0 = _time.time()

        for event in _stream(
            messages=[{'role': 'user', 'content': message}],
            real_path=real_path, api_key=api_key,
            model=model, base_url=base_url, temperature=temperature,
            user_id=user_id,
            max_iterations=MAX_TOOL_ITERATIONS,
            skills_filter=skills_filter_for(stage),
        ):
            ev, data = event['event'], event['data']

            # 内层的 done 是「这一阶段结束了」，不是「整条流水线结束了」——不外发。
            if ev == 'done':
                saw_done = True
                continue

            if ev == 'error':
                error_msg = (data or {}).get('error', '未知错误')

            # turn_complete 带着该轮的完整文本；循环正常结束时最后一条就是报告。
            # 覆盖而非拼接：中间轮的叙述不该进摘要，只要最终那份。
            if ev == 'turn_complete' and (data or {}).get('content'):
                final_text = data['content'].strip()

            payload = dict(data) if isinstance(data, dict) else {'raw': data}
            payload['stage_id'] = stage['id']
            yield _sse(ev, payload)

            if error_msg:
                break

        elapsed_ms = int((_time.time() - _t0) * 1000)

        # 两种失败分开处置。它们看着像，其实不一样：
        #
        #   明确报错 —— 内层干净地说了「我失败了」。这一阶段没有产出，也不会往
        #     prior_summaries 里放半截叙事，所以**跳过它继续跑是安全的**。后面几段
        #     各自吃的是靶点（阶段 1）和候选分子（阶段 2），并不依赖本段的结论 ——
        #     比如 ADMET 挂掉完全不使「机制深化」失效。继续跑能保住用户已等了几十分钟的
        #     工作；一旦中止，剩下几段一次都跑不到。
        #
        #   静默结束 —— 内层没发 done 就断了，不知道它停在哪。此时 final_text 可能只是
        #     半截叙事，当成结论往下传会把垃圾一路带下去，所以**必须中止**。
        #
        # 早期这两种都中止，理由是「不把垃圾摘要传给下一阶段」。那个理由对第二种成立，
        # 对第一种不成立 —— 见上方注释与 test_drug_pipeline_events.py 的 [4]/[5]。
        if error_msg:
            failed_stages.append(stage['id'])
            prior_summaries.append((
                stage['label'],
                _FAILED_STAGE_NOTE.format(reason=error_msg[:200]),
            ))
            yield _sse('stage_done', {
                'stage_id': stage['id'], 'status': 'error',
                'elapsed_ms': elapsed_ms, 'error': error_msg,
            })
            continue

        if not saw_done:
            failed_stages.append(stage['id'])
            aborted = True
            yield _sse('stage_done', {
                'stage_id': stage['id'], 'status': 'error',
                'elapsed_ms': elapsed_ms,
                'error': '阶段未正常结束（内层没有发出 done）',
            })
            break

        yield _sse('stage_done', {
            'stage_id': stage['id'], 'status': 'ok',
            'elapsed_ms': elapsed_ms, 'summary_chars': len(final_text),
        })

        ran_stages.append(stage['id'])
        if final_text:
            prior_summaries.append((stage['label'], final_text))

    # aborted 专指「没跑到最后就被打断」（只有静默失败会这样）。跳过某个失败阶段但
    # 跑完了其余部分，不算中止 —— 那种情况由 failed 字段如实记录。
    yield _sse('done', {
        'final': True,
        'stages_run': len(ran_stages),
        'stages_selected': total,
        'failed': failed_stages,
        'aborted': aborted,
    })


def process_literature_chat_streaming(messages, api_key, context='',
                                       model=DEFAULT_MODEL,
                                       base_url=DEFAULT_BASE_URL,
                                       temperature=DEFAULT_TEMPERATURE,
                                       user_id=''):
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
        user_id=user_id,
        max_iterations=MAX_TOOL_ITERATIONS,
        skills_filter=['light-*'],
    ):
        yield {'event': event['event'], 'data': json.dumps(event['data'], ensure_ascii=False, default=str)}

