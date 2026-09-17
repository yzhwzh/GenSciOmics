#!/usr/bin/env python3
"""LLM 调用失败时的两条韧性保证：瞬时超时能重试、失败要留痕。

自包含（不依赖 pytest），沿用 server/tests/test_supplementary_parse.py 的骨架：
每条断言打一行 PASS/FAIL，末尾 sys.exit(1) 表明有失败。

运行：python3 server/tests/test_pipeline_resilience.py

为什么要有这个文件：
2026-09-15 跑 EGFR 六阶段流水线，第 3 阶段（分子优化 / ADMET）撞上 LLM 网关的
120s socket 超时，之后第 4/5/6 阶段一个都没执行。事后排查时发现两条独立缺陷：

  1. llm_proxy._stream_sse 的 _URLErr 分支只认 502/503/504。连接/首字节超时被
     urllib 包成**没有 code** 的 URLError，于是最该重试的瞬时故障一次都不重试 ——
     而函数 docstring 写着 "Retries on transient server errors"。
  2. agent.process_chat_streaming 的两处失败 return 不写 monitor.db。本次能定位到
     「第 3 阶段挂了」，唯一依据是 monitor.db 里**没有**它的行 —— 现场全无，
     连错误文本都没留下。

**不测**「阶段出错后是否继续跑后面的阶段」—— 那是编排层的产品决策，由
test_drug_pipeline_events.py 的 [4]/[5] 锁住：明确报错跳过该阶段继续跑，
静默结束则中止。本文件只管 LLM 调用这一层。

注意：全程 monkeypatch，不发起任何真实网络请求，也不写 monitor.db。
"""
import io
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_fail = 0


def check(label: str, cond: bool, detail: str = '') -> None:
    global _fail
    if cond:
        print(f'  PASS  {label}')
    else:
        _fail += 1
        print(f'  FAIL  {label}' + (f'  — {detail}' if detail else ''))


import agent
import llm_proxy


# ── 1. LLM 连接/首字节超时必须重试 ──────────────────────────────────
print('\n[1] _stream_sse 对可重试故障发起重试（回归：改前连接超时 0 次重试）')

_orig_urlopen = llm_proxy._urlopen
_orig_sleep = time.sleep
_SSE_ARGS = ([{'role': 'user', 'content': 'hi'}], None, 'k', 'm',
             'http://llm.invalid/v1', 0.7, 'openai')


def _counting_raise(exc_factory):
    """返回一个计数的假 urlopen —— 一被调用就抛，模拟连接阶段就失败。"""
    calls = {'n': 0}

    def _fake(req, timeout=None, **kw):
        calls['n'] += 1
        raise exc_factory()
    return _fake, calls


def _run_sse(opener):
    llm_proxy._urlopen = opener
    try:
        return list(llm_proxy._stream_sse(*_SSE_ARGS))
    finally:
        llm_proxy._urlopen = _orig_urlopen


time.sleep = lambda _s: None   # 去掉 1s/2s 退避 —— 测试不该真等 3 秒
try:
    # 1a. 连接超时：URLError 包着 socket.timeout，没有 .code（这就是漏网的形态）
    _opener, _c = _counting_raise(lambda: URLError(socket.timeout('timed out')))
    _out = _run_sse(_opener)
    check('连接超时重试满 3 次（max_retries+1）', _c['n'] == 3, f'实际 {_c["n"]} 次')
    check('重试耗尽后 yield error', any('error' in c for c in _out), f'实际 {_out}')
    check('error 文本里保留原始超时信息',
          any('timed out' in str(c.get('error', '')) for c in _out), f'实际 {_out}')

    # 1b. 裸 TimeoutError（流中途卡住时是这个形态，走的是另一个分支）
    _opener, _c = _counting_raise(lambda: TimeoutError('timed out'))
    _out = _run_sse(_opener)
    check('裸 TimeoutError 也重试满 3 次', _c['n'] == 3, f'实际 {_c["n"]} 次')

    # 1c. 回归：502 原本就重试，别改坏
    def _http502():
        return HTTPError('http://llm.invalid/v1', 502, 'Bad Gateway', {},
                         io.BytesIO(b'bad gateway'))
    _opener, _c = _counting_raise(_http502)
    _out = _run_sse(_opener)
    check('502 仍然重试满 3 次（回归）', _c['n'] == 3, f'实际 {_c["n"]} 次')

    # 1d. 负例：非瞬时错误不该重试，否则 key 写错要白等 3 轮
    def _http401():
        return HTTPError('http://llm.invalid/v1', 401, 'Unauthorized', {},
                         io.BytesIO(b'bad key'))
    _opener, _c = _counting_raise(_http401)
    _out = _run_sse(_opener)
    check('401 不重试，只试 1 次', _c['n'] == 1, f'实际 {_c["n"]} 次')
    check('401 直接 yield error', any('error' in c for c in _out), f'实际 {_out}')
finally:
    time.sleep = _orig_sleep
    llm_proxy._urlopen = _orig_urlopen


# ── 2. 失败路径也要写 monitor.db ─────────────────────────────────────
print('\n[2] agent 失败路径留痕（回归：改前失败阶段在库里没有任何行）')

_orig_log = agent.log_request
_orig_init = agent._init_mcp_tools
_orig_stream = llm_proxy._stream_sse
_logged = []


def _err_chunk_stream(*a, **kw):
    """内层 LLM 流开局就报错 —— 对应 _stream_sse 的 {'error': ...} 分支。"""
    yield {'error': 'timed out'}


def _raise_stream(*a, **kw):
    """迭代时直接抛 —— 对应 agent:319 的 except 分支。"""
    raise ConnectionResetError('connection reset by peer')
    yield  # pragma: no cover — 让它成为生成器


def _drive(stream_impl):
    _logged.clear()
    agent.log_request = lambda *a, **kw: _logged.append((a, kw))
    agent._init_mcp_tools = lambda: None       # 别真去连 ToolUniverse
    llm_proxy._stream_sse = stream_impl
    try:
        return list(agent.process_chat_streaming(
            messages=[{'role': 'user', 'content': 'hi'}],
            real_path='', api_key='k', model='m',
            base_url='http://llm.invalid/v1',
        ))
    finally:
        agent.log_request = _orig_log
        agent._init_mcp_tools = _orig_init
        llm_proxy._stream_sse = _orig_stream


try:
    _evs = _drive(_err_chunk_stream)
    check('error chunk → error 事件已透传给上层',
          any(e['event'] == 'error' for e in _evs), f'实际 {[e["event"] for e in _evs]}')
    check('error chunk → 调用了 log_request',
          len(_logged) == 1, f'实际调用 {len(_logged)} 次')
    check('error chunk → status 标为 error',
          bool(_logged) and _logged[0][1].get('status') == 'error',
          f'实际 {_logged[0][1] if _logged else None}')
    check('error chunk → 带上了 session_id',
          bool(_logged) and bool(_logged[0][0] and _logged[0][0][0]),
          f'实际 {_logged[0][0] if _logged else None}')
    check('error chunk → 失败原因进了库（不是只写个 status）',
          bool(_logged) and 'timed out' in str(_logged[0][1]),
          f'实际 {_logged[0][1] if _logged else None}')

    _evs = _drive(_raise_stream)
    check('抛异常 → error 事件已透传给上层',
          any(e['event'] == 'error' for e in _evs), f'实际 {[e["event"] for e in _evs]}')
    check('抛异常 → 调用了 log_request', len(_logged) == 1, f'实际 {len(_logged)} 次')
    check('抛异常 → status 标为 error',
          bool(_logged) and _logged[0][1].get('status') == 'error',
          f'实际 {_logged[0][1] if _logged else None}')
    check('抛异常 → 失败原因进了库',
          bool(_logged) and 'connection reset' in str(_logged[0][1]),
          f'实际 {_logged[0][1] if _logged else None}')
finally:
    agent.log_request = _orig_log
    agent._init_mcp_tools = _orig_init
    llm_proxy._stream_sse = _orig_stream


print()
if _fail:
    print(f'{_fail} 项失败')
    sys.exit(1)
print('ALL PASS')
