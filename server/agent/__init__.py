"""GenSci Agent Engine — ReAct Loop

LLM 根据 skill/tool description 自己路由（ReAct 风格）。
复杂任务由 LLM 自己拆解，Evaluator 评估是否充分。

支持 Native Tool + MCP Tool 统一路由。
"""
from __future__ import annotations
import json
import re
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


# ── Per-user memory scoping ─────────────────────────────────
# 记忆按用户隔离：每个浏览器 user_id → server/memory/<sanitized>/。
# 工具在流式路径跑在 ThreadPoolExecutor worker 线程，无请求线程上下文 → 不能用
# thread-local/contextvar，必须把 root 作为显式参数在调用点注入（镜像 real_path 惯例）。
_MEMORY_TOOL_NAMES = frozenset({'memory_read', 'memory_write', 'memory_delete'})


def resolve_memory_root(user_id: str):
    """user_id → 隔离记忆目录；空/净化后为空 → None（回退全局 server/memory/）。"""
    if not user_id:
        return None
    safe = re.sub(r'[^A-Za-z0-9_-]', '', str(user_id))[:64]
    if not safe:
        return None
    from config import MEMORY_DIR
    return MEMORY_DIR / safe


def _scope_args(name: str, args: dict, mem_root) -> dict:
    """给 memory_* 工具注入 per-user 记忆 root（不在 LLM schema 中，LLM 不会看到）。"""
    if mem_root is not None and name in _MEMORY_TOOL_NAMES:
        args = dict(args)
        args['root'] = str(mem_root)
    return args


# ── 「没执行却宣称做完了」的兜底 ────────────────────────────────
# 模型偶发地整轮不调工具：直接吐一段文字（常常夹着代码块），并在里面声称
# 「已生成」「已重新生成」。没有 shell 调用就没有任何文件产生，那句话是假的 ——
# 用户看到的现象就是「只输出代码不执行」。
#
# 现场（/tmp/gensci_monitor.db）：2026-09-20 那段 Free Analysis 会话 10 轮里
# 6 轮 tool_calls=0。按前端的确切消息形状重放该会话复现到原话「图片已重新生成！」
# 并编造了文件名 venn_Merge5_vs_MMP7_unified.png —— 那一轮一次工具都没调。
# 同一条提示在空白上下文里重放 5/5 正常调工具，所以这是**上下文诱发的模型行为**，
# 不是某次回归；兜底只能放在循环里，不能靠改提示词指望它不再发生。
#
# 判定只在**整个请求一次工具都没跑过**时生效（见 _needs_execution_nudge）：
# 正常收尾那一轮同样没有 tool_calls，但那时 all_tool_results 非空，正文里的
# 「已生成」是实话 —— 拿它当证据会把每一轮正常收尾都判成撒谎。
#
# 判据第一版是「枚举中文完成副词」（已生成 / 已完成 / 已保存…），端到端重放时
# **连续两次漏判**：同一轮故障换了两种措辞，两版正则都匹配不上 ——
#   「完成了！现在两个散点图的标题格式一致」            （没有「已」字）
#   「![...](/api/results?file=merge5_coexpression_….png)」（图片链接不是副词）
# 靠枚举措辞是打地鼠，赢不了。改成按「这段文字指向了一个已经存在的产物」来判 ——
# 那是可证伪的：本轮一次工具都没跑，被引用的文件不可能存在。
_RESULT_ARTIFACT_RE = re.compile(
    r'!\[[^\]]*\]\([^)]*\)'                      # markdown 图片 = 「这就是结果」
    r'|/api/results\?file='
    r'|[\w-]{3,}\.(?:png|jpe?g|svg|pdf|csv|tsv|xlsx?|h5ad|zip)\b'
)

# 完成声明的措辞兜底。**只在整轮零工具调用时才用**（见 _needs_execution_nudge），
# 所以「正常收尾那一轮说已生成」不会被误判 —— 那时 all_tool_results 非空。
_UNEXECUTED_CLAIM_RE = re.compile(
    r'已(?:经)?(?:重新)?(?:生成|执行|运行|保存|绘制|出图|输出|更新|完成|搞定|修改)'
    r'|(?:图片|图像|图|结果|文件|脚本|代码|标题)(?:已|已经)(?:生成|保存|输出|更新|运行|执行|修改|一致)'
    r'|重新生成|完成了|搞定(?:了)?|处理完毕|已就绪'
)
_FENCE_RE = re.compile(r'```[^\n]*\n(.*?)```', re.S)
# 只在代码块里找这些才算「贴了一段能跑的脚本」。裸词 'code'/'script' 不算 ——
# 正文里顺口提一句脚本名是常态。
_EXEC_HINT_RE = re.compile(
    r'import\s+[A-Za-z_]|from\s+[A-Za-z_.]+\s+import|def\s+[A-Za-z_]'
    r'|subprocess|read_h5ad|scanpy|matplotlib|pandas|numpy|plt\.|pd\.'
)

# 最多纠正几次。模型对纠正的反应不是每次都灵（monitor.db 里用户手打「你没有执行」
# 之后，模型有时调工具、有时仍然不调），所以给两次而不是一次；但不能无上限 ——
# 否则一个坚持不调工具的模型会把轮次烧穿。
_MAX_EXECUTION_NUDGES = 2

_EXECUTION_NUDGE = (
    '【未执行】你这一轮没有调用任何工具，但回复里指向了已经产生的结果'
    '（图片 / 图 / 表 / 数值 / 文件名）。没有工具调用就没有任何文件产生，这些都还不存在。\n'
    '如果你确实要产出结果，现在必须真正调用工具：先 skill("技能名") 取指令，'
    '再用 shell 执行。不要只贴代码、也不要只描述步骤。\n'
    '如果你确实不需要任何工具（例如纯知识性回答），**只回复「无需执行」四个字**，'
    '不要重复上面的内容。'
)


def _execution_nudge_reason(text: str) -> str | None:
    """这段文字读起来像「已经做完并给出了结果」吗？像的话是凭什么判的。

    返回值决定要不要给用户挂可见提示（见 process_chat_streaming）：
      'artifact' —— 引用了图片 / 文件名 / /api/results 链接。本轮零工具调用时
                    那个文件**不可能存在**，是硬事实，挂提示不会冤枉人。
      'claim'    —— 只有完成声明的措辞。措辞判据可能失手（「……这样就完成了」
                    这种纯解释也可能命中），所以**不挂提示**，静默补一轮即可。
      'code'     —— 正文里贴了一段没拿去执行的脚本。
    """
    if not text:
        return None
    if _RESULT_ARTIFACT_RE.search(text):
        return 'artifact'
    if _UNEXECUTED_CLAIM_RE.search(text):
        return 'claim'
    if any(_EXEC_HINT_RE.search(block) for block in _FENCE_RE.findall(text)):
        return 'code'
    return None


def _looks_like_unexecuted_work(text: str) -> bool:
    """_execution_nudge_reason 的布尔形式。"""
    return _execution_nudge_reason(text) is not None


def _needs_execution_nudge(tool_calls: list, all_tool_results: list,
                           content: str, nudges: int) -> bool:
    """要不要因为「没执行就宣称完成」再续跑一轮。"""
    if tool_calls or all_tool_results:
        return False          # 工具真的跑过，正文里的「已生成」就是实话
    if nudges >= _MAX_EXECUTION_NUDGES:
        return False          # 已经纠正过，不再纠缠
    return _looks_like_unexecuted_work(content)


def process_chat(
    messages: list[dict],
    real_path: str,
    api_key: str,
    model: str = 'deepseek-chat',
    base_url: str = 'https://api.deepseek.com',
    temperature: float = 0.7,
    user_id: str = '',
    max_iterations: int = 100,
) -> dict:
    """Process a chat request with the full agent pipeline + memory."""
    # 0. Get the user's latest message (for memory recall query)
    user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            user_msg = msg.get('content', '')
            break

    # Per-user memory scope
    mem_root = resolve_memory_root(user_id)

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
        'content': '<system-reminder>【技能提醒】当前有可用技能。如果用户请求匹配某个技能，必须先调 skill("技能名") 获取指令，不要自己写代码。\n'
                   '⚠️ 产出落点提醒：你生成的一切文件（报告 / CSV / 表格 / 图 / 中间结果）都必须写到 $GENSCI_RESULTS_DIR（默认 /tmp/gensci_results/），'
                   'shell 子进程已注入该环境变量。**严禁写进源码树** —— 尤其 server/skills/，那是指令文档不是工作目录。'
                   '脚本若带 --outdir/--out/-o 参数，必须显式传入。\n'
                   '⚠️ 图片协议提醒：图片同样存到 $GENSCI_RESULTS_DIR，在 stdout 打印 ![描述](/api/results?file=xxx.png)，并在回复中包含该 markdown 标签。</system-reminder>',
    })

    # 8. Tool-calling loop
    all_tool_results = []
    nudges = 0          # 「没执行却宣称完成」已纠正次数，见 _needs_execution_nudge
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
            if _needs_execution_nudge(tool_calls, all_tool_results, content, nudges):
                nudges += 1
                # assistant_msg 上面已经追加进 working_messages 了，这里只补纠正。
                # 非流式不经过 SSE，正文还没交给调用方，没有「已流出去收不回来」的问题。
                working_messages.append({'role': 'user', 'content': _EXECUTION_NUDGE})
                continue
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
            tool_result = _execute_tool(tc, real_path, mem_root)
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
    user_id: str = '',
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

    # Per-user memory scope
    mem_root = resolve_memory_root(user_id)

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
        mem = _prefetch_memory(query=user_msg, root=str(mem_root)) if mem_root is not None else _prefetch_memory(query=user_msg)
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
    nudges = 0          # 「没执行却宣称完成」已纠正次数，见 _needs_execution_nudge
    _start_time = time.time()

    for iteration in range(max_iterations):
        yield {'event': 'status', 'data': {'stage': 'thinking', 'message': '思考中...'}}
        collected_content = ''
        collected_tc: dict[int, dict] = {}

        iter_tools = tools  # always provide tools (don't disable them)

        try:
            for chunk in _stream_sse(working_messages, iter_tools, api_key, model, base_url, temperature, api_type):
                if 'error' in chunk:
                    # 失败也要留痕。2026-09-15 那次流水线中止，事后能定位到「第 3 阶段
                    # 挂了」的唯一依据是 monitor.db 里**没有**它的行 —— 错误文本、耗时、
                    # 已经跑了几个工具，现场全无。这两处 return 原先都绕过了 log_request。
                    log_request(session_id, query=user_msg, intent="unknown",
                                tool_calls=len(all_tool_results), iterations=iteration,
                                latency_ms=(time.time() - _start_time) * 1000,
                                status='error', error=str(chunk['error']))
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
            log_request(session_id, query=user_msg, intent="unknown",
                        tool_calls=len(all_tool_results), iterations=iteration,
                        latency_ms=(time.time() - _start_time) * 1000,
                        status='error', error=f'API error: {str(e)[:200]}')
            yield {'event': 'error', 'data': {'error': f'API error: {str(e)[:200]}'}}; return

        yield {'event': 'turn_complete', 'data': {'content': collected_content}}
        tcl = list(collected_tc.values())

        if not tcl:
            if _needs_execution_nudge(tcl, all_tool_results, collected_content, nudges):
                nudges += 1
                # 已经流出去的文字收不回来 —— 前端（FreeAnalysisTab.tsx:119-145）
                # 只认 message / tool_result / error，没有「撤回」事件，message 又是
                # **追加**到最后一条 assistant 气泡。既然撤不掉，就在同一条气泡里
                # 紧接着声明它不作数；否则默不作声地补跑，用户先看到「图片已生成！」
                # 和一个空图框，紧接着才出现真结果，比不说更糟。
                #
                # 只在 'artifact' 时挂这句。那时「文件不存在」是硬事实；靠措辞
                # （'claim'/'code'）判来的可能失手，不能拿一句未必成立的话去指责模型。
                if _execution_nudge_reason(collected_content) == 'artifact':
                    yield {'event': 'message', 'data': {'content':
                        '\n\n⚠️ 上面引用的文件/图片并没有真正产生（本轮未调用任何工具），正在重新执行…\n\n'}}
                working_messages.append({'role': 'assistant', 'content': collected_content})
                working_messages.append({'role': 'user', 'content': _EXECUTION_NUDGE})
                continue
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
                args = _scope_args(fn_name, args, mem_root)  # per-user 记忆 root（闭包注入，worker 线程可见）
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


def _execute_tool(tool_call: dict, real_path: str, mem_root=None) -> dict:
    """Execute a tool call — supports NativeTool + MCPToolProxy."""
    func_info = tool_call.get('function', {})
    name = func_info.get('name', '')
    try:
        args = json.loads(func_info.get('arguments', '{}'))
    except json.JSONDecodeError:
        args = {}
    args = _scope_args(name, args, mem_root)  # per-user 记忆 root

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
