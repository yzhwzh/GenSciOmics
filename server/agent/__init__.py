"""GenSci Agent Engine — ReAct Loop

LLM 根据 skill/tool description 自己路由（ReAct 风格）。
复杂任务由 LLM 自己拆解，Evaluator 评估是否充分。

支持 Native Tool + MCP Tool 统一路由。
"""
from __future__ import annotations
import json
import time
import traceback

from .prompt import assemble_prompt
from .evaluator import evaluate, log_request
from skills import get_skill, get_openai_tools
from skills._loader import scan_skills
from core import ALL_TOOLS, get_mcp_manager as _get_mcp_manager
from engine.hooks import run_post_tool


def _init_mcp_tools():
    """Initialize MCP manager and register tools into ALL_TOOLS."""
    from core import Tool, add_tool
    mgr = _get_mcp_manager()
    if mgr is None:
        return
    mcp_tools = mgr.discover_all()
    for proxy in mcp_tools:
        add_tool(Tool(
            name=proxy.name,
            description=proxy.description,
            input_schema=proxy.input_schema,
            is_mcp=True,
            server_name=proxy.server_name,
            mcp_tool_name=proxy.mcp_tool_name,
            is_deferred=False,
        ))


def process_chat(
    messages: list[dict],
    real_path: str,
    api_key: str,
    model: str = 'deepseek-chat',
    base_url: str = 'https://api.deepseek.com',
    temperature: float = 0.7,
    max_iterations: int = 100,
) -> dict:
    """Process a chat request with the full agent pipeline + memory."""
    # 0. Get the user's latest message (for memory recall query)
    user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            user_msg = msg.get('content', '')
            break

    # 1. Build system prompt — 注入日期 + 记忆指令 + skill 列表
    session_id = real_path if real_path else 'default'
    md_skills = scan_skills()
    system_prompt = assemble_prompt(user_msg, intent='unknown', skills=md_skills, real_path=real_path)
    all_openai_tools = get_openai_tools()
    tools = all_openai_tools  # 不限制 skill

    # 4. Prepare working messages
    working_messages = list(messages)
    if not working_messages or working_messages[0].get('role') != 'system':
        working_messages.insert(0, {'role': 'system', 'content': system_prompt})
    else:
        working_messages[0] = {'role': 'system', 'content': system_prompt}

    # Inject skill-first reminder (compensates for lack of Anthropic system-reminder)
    working_messages.append({
        'role': 'user',
        'content': '<system-reminder>【技能提醒】当前有可用技能。如果用户请求匹配某个技能，必须先调 skill("技能名") 获取指令，不要自己写代码。\n⚠️ 图片协议提醒：如果用 Python 生成图片（matplotlib/seaborn），必须保存到 /tmp/gensci_results/，在 stdout 打印 ![描述](/api/results?file=xxx.png)，并在回复中包含该 markdown 标签。</system-reminder>',
    })

    # 8. Tool-calling loop
    all_tool_results = []
    _start_time = time.time()
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        response = _call_llm(base_url, model, api_key, working_messages, tools, temperature)

        if 'error' in response:
            log_request(session_id, query=user_msg, intent="unknown",
                        tool_calls=len(all_tool_results), iterations=iteration,
                        latency_ms=(time.time() - _start_time) * 1000,
                        plan_used=False, status='error')
            return {'error': response['error'], 'tool_results': all_tool_results}

        choices = response.get('choices', [])
        if not choices:
            continue

        choice = choices[0]
        msg = choice.get('message', {})
        content = msg.get('content', '')
        tool_calls = msg.get('tool_calls', [])

        assistant_msg = {'role': 'assistant', 'content': content}
        if tool_calls:
            assistant_msg['tool_calls'] = [
                {
                    'id': tc.get('id', f'call_{i}'),
                    'type': 'function',
                    'function': {
                        'name': tc['function']['name'],
                        'arguments': tc['function']['arguments'],
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]
        working_messages.append(assistant_msg)

        if not tool_calls:
            log_request(session_id, query=user_msg, intent="unknown",
                        tool_calls=len(all_tool_results), iterations=iteration,
                        latency_ms=(time.time() - _start_time) * 1000,
                        plan_used=False)
            return {
                'content': content or '',
                'tool_results': all_tool_results,
                'iterations': iteration,
                'intent': 'unknown',
            }

        # Execute each tool call
        for tc in tool_calls:
            name = tc.get('function', {}).get('name', '')
            tool_result = _execute_tool(tc, real_path)
            all_tool_results.append(tool_result)
            tc_id = tc.get('id', f'call_{len(all_tool_results)-1}')
            # Tool result format: wrap in user message (Anthropic-style, works better with DeepSeek)
            res = tool_result.get('result', {}) or {}
            if tool_result.get('error'):
                result_content = f'Error: {tool_result["error"]}'
            elif isinstance(res, dict) and 'stdout' in res:
                result_content = res.get('stdout', '') or ''
            else:
                result_content = json.dumps(res, ensure_ascii=False, default=str)[:50000]
            working_messages.append({'role': 'tool', 'tool_call_id': tc_id, 'content': result_content[:50000]})

            # Post-tool hooks
            if iteration < max_iterations - 1:
                hook_msg = run_post_tool(name, tc.get('function', {}), tool_result.get('result', {}))
                if hook_msg:
                    working_messages.append({'role': 'user', 'content': hook_msg})

            # Evaluator: check if search results are sufficient
            if name == 'gene_info' or 'search' in name or 'web_search' in name:
                try:
                    ev = evaluate(user_msg, all_tool_results, context=real_path or '')
                    if not ev.get('sufficient') and iteration < max_iterations - 1:
                        nq = ev.get('next_query', '')
                        if nq:
                            working_messages.append({
                                'role': 'user',
                                'content': f'Need more: {nq}',
                            })
                            break
                except Exception:
                    pass  # evaluator failure is non-critical

    log_request(session_id, query=user_msg, intent="unknown",
                tool_calls=len(all_tool_results), iterations=iteration,
                latency_ms=(time.time() - _start_time) * 1000,
                plan_used=False, status='max_iterations')
    return {
        'content': 'Analysis reached maximum iteration limit.',
        'tool_results': all_tool_results,
        'iterations': iteration,
        'intent': 'unknown',
    }


def process_chat_streaming(
    messages: list[dict],
    real_path: str,
    api_key: str,
    model: str = 'deepseek-chat',
    base_url: str = 'https://api.deepseek.com',
    temperature: float = 0.7,
    max_iterations: int = 100,
    skills_filter: list[str] | None = None,
) -> dict:
    """Streaming agent pipeline — yields SSE event dicts.

    Same components as process_chat() but streams events in real-time.
    skills_filter: optional list of tool names to restrict (e.g. ['mcp__exa__web_search_exa']).
    """
    from llm_proxy import _stream_sse, _api_url as _api_url_proxy
    from concurrent.futures import ThreadPoolExecutor, as_completed as _ac, TimeoutError as _Timeout
    from skills import SKILL_REGISTRY as _SK_REG, get_skill as _get_skill, get_openai_tools as _get_tools

    # Initialize MCP and register tools into ALL_TOOLS
    _init_mcp_tools()

    user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            user_msg = msg.get('content', ''); break

    session_id = real_path if real_path else ('stream-' + (user_msg.replace(' ', '_')[:32] if user_msg else 'default'))

    # Build supervisor prompt — 列出所有可用 skill，LLM 自己路由
    md_skills = scan_skills()
    def _match_filter(name, filters):
        for f in filters:
            if f.endswith('*') and name.startswith(f[:-1]):
                return True
            if name == f:
                return True
        return False

    # Filter which skills appear in the prompt (LLM sees these as primary options)
    if skills_filter:
        md_skills = [s for s in md_skills if _match_filter(s["name"], skills_filter) or _match_filter(s["folder"], skills_filter)]
    system_prompt = assemble_prompt(user_msg, intent='unknown', skills=md_skills, real_path=real_path)
    # All tools remain available for function calling (shell, skill, MCP, memory, etc.)
    all_openai_tools = _get_tools()
    tools = all_openai_tools

    working_messages = list(messages)
    if not working_messages or working_messages[0].get('role') != 'system':
        working_messages.insert(0, {'role': 'system', 'content': system_prompt})
    else:
        working_messages[0] = {'role': 'system', 'content': system_prompt}

    # ── Memory prefetch (对齐 Claude Code startRelevantMemoryPrefetch) ─────
    # 非阻塞注入：在首轮请求前搜索相关记忆，无需 LLM 主动调用 memory_read
    try:
        from tools.MemoryReadTool import memory_read as _prefetch_memory
        mem = _prefetch_memory(query=user_msg)
        if mem and mem.get('n_results', 0) > 0:
            preview = '\n'.join(
                f"📝 {r['name']} ({r.get('type', '')}): {r.get('description', '')}"
                for r in mem['results'][:3]
            )
            working_messages.append({
                'role': 'system',
                'content': f'<memory-prefetch>找到 {mem["n_results"]} 条相关记忆，可随时用 memory_read 读取详情：\n{preview}</memory-prefetch>',
            })
    except Exception:
        pass  # Memory unavailable — non-critical

    _, api_type = _api_url_proxy(base_url)
    all_tool_results = []
    _start_time = time.time()

    for iteration in range(max_iterations):
        yield {'event': 'status', 'data': {'stage': 'thinking', 'message': '思考中...'}}
        collected_content = ''
        collected_tc: dict[int, dict] = {}

        iter_tools = tools  # always provide tools (don't disable them)

        try:
            for chunk in _stream_sse(working_messages, iter_tools, api_key, model, base_url, temperature, api_type):
                if 'error' in chunk:
                    yield {'event': 'error', 'data': {'error': chunk['error']}}; return
                choices = chunk.get('choices')
                if not choices:
                    continue
                delta = choices[0].get('delta', {})
                if delta.get('content'):
                    collected_content += delta['content']
                    yield {'event': 'message', 'data': {'content': delta['content']}}
                if delta.get('tool_calls'):
                    for td in delta['tool_calls']:
                        idx = td.get('index', 0)
                        if idx not in collected_tc:
                            collected_tc[idx] = {'id': '', 'function': {'name': '', 'arguments': ''}}
                        e = collected_tc[idx]
                        if td.get('id'): e['id'] = td['id']
                        if td.get('function', {}).get('name'): e['function']['name'] += td['function']['name']
                        if td.get('function', {}).get('arguments'): e['function']['arguments'] += td['function']['arguments']
        except Exception as e:
            yield {'event': 'error', 'data': {'error': f'API error: {str(e)[:200]}'}}; return

        yield {'event': 'turn_complete', 'data': {'content': collected_content}}
        tcl = list(collected_tc.values())

        if not tcl:
            log_request(session_id, query=user_msg, intent="unknown",
                        tool_calls=len(all_tool_results), iterations=iteration,
                        latency_ms=(time.time() - _start_time) * 1000)
            yield {'event': 'done', 'data': {'final': True}}; return

        working_messages.append({
            'role': 'assistant', 'content': collected_content,
            'tool_calls': [{'id': t.get('id', f'c_{i}'), 'type': 'function',
                'function': {'name': t['function'].get('name', ''), 'arguments': t['function'].get('arguments', '{}')}}
                for i, t in enumerate(tcl)]})

        for i, t in enumerate(tcl):
            yield {'event': 'tool_call', 'data': {
                'name': t.get('function', {}).get('name', ''),
                'args': t.get('function', {}).get('arguments', '{}')}}

        _tool_results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            def _run_one(i, t):
                fn_name = t.get('function', {}).get('name', '')
                args = json.loads(t.get('function', {}).get('arguments', '{}') or '{}')
                try:
                    # Check ALL_TOOLS first (supports Native + MCP)
                    tool = next((t for t in ALL_TOOLS if t.name == fn_name), None)
                    if tool is not None:
                        if tool.is_mcp:
                            mcp = _get_mcp_manager()
                            result = mcp.call_tool(tool.server_name, tool.mcp_tool_name, args) if mcp else None
                        elif tool.fn is not None:
                            result = tool.fn(**args)
                        else:
                            result = None
                    else:
                        skill = _get_skill(fn_name)
                        if skill and any(p.name == 'real_path' for p in skill.params):
                            args['real_path'] = real_path
                        result = skill.func(**args) if skill else None
                    return i, {'name': fn_name, 'result': result, 'error': None}
                except Exception as e:
                    return i, {'name': fn_name, 'result': None, 'error': str(e)}
            futures = {pool.submit(_run_one, i, t): i for i, t in enumerate(tcl)}
            for future in _ac(futures):
                try:
                    i, tr = future.result(timeout=120)
                except _Timeout:
                    i = futures.get(future, -1)
                    if i >= 0:
                        tr = {'name': tcl[i].get('function', {}).get('name', ''),
                              'result': None, 'error': 'tool timeout (120s)'}
                    else:
                        continue
                _tool_results[i] = tr
                yield {'event': 'tool_result', 'data': tr}

        for i in sorted(_tool_results.keys()):
            tr = _tool_results[i]
            t = tcl[i]
            fn = tr['name']
            args = json.loads(t.get('function', {}).get('arguments', '{}') or '{}')
            res = tr.get('result', {}) or {}
            if tr['error']:
                rc = f'Error: {tr["error"]}'
            elif isinstance(res, dict) and 'stdout' in res:
                rc = res.get('stdout', '') or ''
                stderr = res.get('stderr', '')
                if stderr: rc += f'\n[stderr]\n{stderr}'
            else:
                rc = json.dumps(res, ensure_ascii=False, default=str)
            working_messages.append({'role': 'tool', 'tool_call_id': t.get('id', f'c_{i}'), 'content': rc[:50000]})
            all_tool_results.append(tr)
            # Post-tool hooks for auto-continue
            if iteration < max_iterations - 1:
                hook_msg = run_post_tool(fn, t.get('function', {}), res)
                if hook_msg:
                    working_messages.append({'role': 'user', 'content': hook_msg})

        yield {'event': 'status', 'data': {'stage': 'analyzing', 'message': '正在分析搜索结果...'}}
        # Near-limit nudge: when approaching max_iterations, tell LLM to conclude
        if iteration >= max_iterations - 3 and iteration < max_iterations - 1:
            working_messages.append({
                'role': 'user',
                'content': '已到对话轮次上限边缘，请根据已获取的信息立即生成最终总结，不要再调工具。',
            })

    log_request(session_id, query=user_msg, intent="unknown",
                tool_calls=len(all_tool_results), iterations=max_iterations,
                latency_ms=(time.time() - _start_time) * 1000, status='max_iterations')
    yield {'event': 'done', 'data': {'final': True, 'warning': 'Max iterations reached'}}


def _execute_tool(tool_call: dict, real_path: str) -> dict:
    """Execute a tool call — supports NativeTool + MCPToolProxy."""
    func_info = tool_call.get('function', {})
    name = func_info.get('name', '')
    try:
        args = json.loads(func_info.get('arguments', '{}'))
    except json.JSONDecodeError:
        args = {}

    # 1. Try ALL_TOOLS (unified registry) first
    tool = next((t for t in ALL_TOOLS if t.name == name), None)
    if tool is not None:
        try:
            if tool.is_mcp:
                mcp = _get_mcp_manager()
                if mcp is None:
                    return {'name': name, 'error': 'MCP manager not initialized', 'result': None}
                result = mcp.call_tool(tool.server_name, tool.mcp_tool_name, args)
                return {'name': name, 'args': args, 'result': result, 'error': None}
            elif tool.fn is not None:
                result = tool.fn(**args)
                return {'name': name, 'args': args, 'result': result, 'error': None}
        except Exception as e:
            traceback.print_exc()
            return {'name': name, 'args': args, 'result': None, 'error': str(e)}

    # 2. Fallback to SKILL_REGISTRY for backward compatibility
    skill = get_skill(name)
    if not skill:
        return {'name': name, 'error': f'Unknown skill: {name}', 'result': None}

    if 'real_path' in {p.name for p in skill.params}:
        args['real_path'] = real_path

    try:
        result = skill.func(**args)
        return {'name': name, 'args': args, 'result': result, 'error': None}
    except Exception as e:
        traceback.print_exc()
        return {'name': name, 'args': args, 'result': None, 'error': str(e)}


def _api_url(base_url: str) -> tuple[str, str]:
    """Detect API type from base_url. Returns (base_url, api_type)."""
    bu = base_url.lower()
    if 'anthropic' in bu:
        return (base_url.rstrip('/'), 'anthropic')
    return (base_url.rstrip('/'), 'openai')


def _call_llm(
    base_url: str, model: str, api_key: str,
    messages: list[dict], tools: list[dict], temperature: float,
) -> dict:
    """Call chat API with exponential backoff retry (对标 Claude Code error recovery)."""
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    import time as _time

    base, api_type = _api_url(base_url)
    max_retries = 2
    retry_delay = 1.0

    if api_type == 'anthropic':
        # ── Anthropic format ──
        # Convert OpenAI-style messages to Anthropic format
        system_msg = ''
        anthropic_msgs = []
        for m in messages:
            if m.get('role') == 'system':
                system_msg += m.get('content', '') + '\n'
            elif m.get('role') in ('user', 'assistant'):
                content = []
                text = m.get('content', '')
                if text:
                    content.append({'type': 'text', 'text': text})
                # Handle tool_use and tool_result blocks
                for tc in m.get('tool_calls', []):
                    fn = tc.get('function', {})
                    content.append({
                        'type': 'tool_use',
                        'id': tc.get('id', ''),
                        'name': fn.get('name', ''),
                        'input': json.loads(fn.get('arguments', '{}')),
                    })
                anthropic_msgs.append({'role': m['role'], 'content': content})
            elif m.get('role') == 'tool':
                # Find the last assistant message to add tool_result
                tc_id = m.get('tool_call_id', '')
                content_str = m.get('content', '')
                try:
                    content_data = json.loads(content_str) if isinstance(content_str, str) else content_str
                except json.JSONDecodeError:
                    content_data = content_str
                anthropic_msgs.append({
                    'role': 'user',
                    'content': [{
                        'type': 'tool_result',
                        'tool_use_id': tc_id,
                        'content': str(content_data)[:50000],
                    }],
                })

        body = {
            'model': model,
            'max_tokens': 4096,
            'messages': anthropic_msgs,
        }
        if system_msg.strip():
            body['system'] = system_msg.strip()
        # Anthropic doesn't support tool_choice='auto' in the same way
        # Tools are sent as a separate parameter
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get('function', {})
                anthropic_tools.append({
                    'name': fn.get('name', ''),
                    'description': fn.get('description', ''),
                    'input_schema': fn.get('parameters', {}),
                })
            body['tools'] = anthropic_tools

        url = f'{base}/v1/messages'
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
    else:
        # ── OpenAI format ──
        url = f'{base}/chat/completions'
        body = {'model': model, 'messages': messages, 'temperature': temperature}
        if tools:
            body['tools'] = tools
            body['tool_choice'] = 'auto'
        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            req = Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
            with urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                if api_type == 'anthropic':
                    content = ''
                    tc_list = []
                    for block in data.get('content', []):
                        if block.get('type') == 'text':
                            content += block.get('text', '')
                        elif block.get('type') == 'tool_use':
                            tc_list.append({
                                'id': block.get('id', ''),
                                'type': 'function',
                                'function': {
                                    'name': block.get('name', ''),
                                    'arguments': json.dumps(block.get('input', {})),
                                },
                            })
                    msg = {'role': 'assistant', 'content': content}
                    if tc_list:
                        msg['tool_calls'] = tc_list
                    return {'choices': [{'message': msg}]}
                return data
        except URLError as e:
            last_error = e
            code = getattr(e, 'code', 0)
            # Retry on 429 (rate limit), 502/503/504 (server errors)
            if code in (429, 502, 503, 504) and attempt < max_retries:
                _time.sleep(retry_delay * (2 ** attempt))
                continue
            try:
                raw = e.read() if hasattr(e, 'read') else str(e).encode()
                error_body = raw.decode('utf-8', errors='replace')
            except Exception:
                error_body = str(e)
            import re as _re
            error_body = _re.sub(r'sk-[A-Za-z0-9]{10,}', 'sk-***', error_body)
            short = error_body[:200]
            return {'error': f'LLM API error ({code})' if code else f'LLM API error: {short}'}
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                _time.sleep(retry_delay * (2 ** attempt))
                continue
            return {'error': f'Request failed: {str(e)[:200]}'}
    return {'error': f'LLM API failed after retries: {str(last_error)[:200]}'}
