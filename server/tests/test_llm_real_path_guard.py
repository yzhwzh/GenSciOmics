#!/usr/bin/env python3
"""两个 LLM 端点必须校验 real_path。

自包含（不依赖 pytest），沿用 server/tests/test_drug_stages.py 的假 handler 骨架：
每条断言打一行 PASS/FAIL，末尾 sys.exit(1) 表明有失败。

运行：python3 server/tests/test_llm_real_path_guard.py

为什么要有这个文件：
`POST /api/llm/chat` 与 `/api/llm/chat/stream` 都**要求** `real_path` 必填
（`if not real_path: _send_error('real_path required')`），却**从不校验它**——
没有 `validate_real_path`。而 `real_path` 随后被原样交给
`process_chat` / `process_chat_streaming` → `agent._execute_tool` → 注入 skill 参数
→ `get_adata()` 与 ShellTool。

有意思的是第三个同类端点 `handle_llm_literature_stream` 明确注释了
「Does NOT require real_path」——说明「不校验」在它那里是刻意的。
前两个是**要求必填却忘了校验**，这个不对称本身说明是疏漏，不是设计。

与 test_unexecuted_guard.py 的分工：那里测的是 `process_chat` 内部的执行守卫
（绕过路由 handler 直接调函数）；这里测的是**路由层有没有把住入口**。

测法：不开真 socket。假 handler 只记录 `_send_error` / `_json`；
`routes.process_chat*` 与 `routes._stream_sse_response` 打桩，
于是「有没有走到底」可以从桩有没有被调用来判断 —— 而不是靠读源码。
本文件不发起任何真实网络请求，也不读任何 .h5ad 内容。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_fail = 0


def check(label: str, cond: bool, detail: str = '') -> None:
    global _fail
    if cond:
        print(f'  PASS  {label}')
    else:
        _fail += 1
        print(f'  FAIL  {label}' + (f'  — {detail}' if detail else ''))


import config                                      # noqa: E402
import routes                                      # noqa: E402

DATA = config.PROJECT_ROOT / 'Data'


class _FakeHandler:
    """只记录 _send_error / _json，不碰 socket。"""

    def __init__(self):
        self.errors: list[str] = []
        self.json: list = []

    def _send_error(self, message, status=400):
        self.errors.append(message)

    def _json(self, data, status=200):
        self.json.append(data)


# ── 打桩：把「走到底」变成一个可观测事件 ──────────────────────────────
_calls: list[tuple[str, str]] = []       # (端点名, 收到的 real_path)

_orig = (routes.process_chat, routes.process_chat_streaming, routes._stream_sse_response)

routes.process_chat = lambda messages, real_path, *a, **k: (
    _calls.append(('chat', real_path)) or {'content': 'stub'})
routes.process_chat_streaming = lambda messages, real_path, *a, **k: (
    _calls.append(('stream', real_path)) or iter([{'event': 'done'}]))
routes._stream_sse_response = lambda handler, events, **k: list(events)


def _run(fn, real_path: str):
    """跑一个 LLM handler，返回 (假 handler, 本轮 process_chat* 收到的路径列表)。"""
    _calls.clear()
    h = _FakeHandler()
    fn(h, {
        'messages': [{'role': 'user', 'content': 'hi'}],
        'real_path': real_path,
        'api_key': 'sk-test',
        'base_url': 'https://api.deepseek.com',
    })
    return h, [p for _, p in _calls]


# 两个待测端点。名字只用于报错信息。
ENDPOINTS = [
    ('POST /api/llm/chat', routes.handle_llm_chat),
    ('POST /api/llm/chat/stream', routes.handle_llm_chat_stream),
]


# ── 1. 穿越路径必须被拒，且不得走到 process_chat ───────────────────────
print('\n[1] Data/../… 必须被拒，且不能走到 process_chat（回归：改前直接放行）')

_ESCAPE = str(DATA / '..' / 'server' / 'config.py')
check('前置：逃逸目标确实存在', (config.PROJECT_ROOT / 'server' / 'config.py').is_file())

for _name, _fn in ENDPOINTS:
    _h, _seen = _run(_fn, _ESCAPE)
    check(f'{_name}：穿越路径报错', bool(_h.errors), '没有报错')
    check(f'{_name}：穿越路径未走到 process_chat', not _seen,
          f'放行到了 process_chat，收到 {_seen}')


# ── 2. 其它非法路径同样被拒 ────────────────────────────────────────────
print('\n[2] 白名单外、不存在、空串 —— 同样不得放行')

for _label, _bad in [
    ('白名单外的普通文件', str(config.PROJECT_ROOT / 'README.md')),
    ('不存在的文件',       str(DATA / 'NoSuchFile.h5ad')),
    ('空串',               ''),
]:
    for _name, _fn in ENDPOINTS:
        _h, _seen = _run(_fn, _bad)
        check(f'{_name}：{_label}被拒', bool(_h.errors) and not _seen,
              f'errors={_h.errors} 走到了={_seen}')


# ── 3. 合法路径必须照常放行（别修成一刀切）────────────────────────────
print('\n[3] Data/ 内的合法软链接必须照常走到 process_chat')

_link = next((p for p in DATA.rglob('*') if p.is_symlink() and p.is_file()), None)
if _link is None:
    check('前置：Data/ 下存在可用软链接', False, '找不到软链接，本组无法执行')
else:
    for _name, _fn in ENDPOINTS:
        _h, _seen = _run(_fn, str(_link))
        check(f'{_name}：合法路径放行', not _h.errors and len(_seen) == 1,
              f'errors={_h.errors} 走到了={_seen}')
        check(f'{_name}：交给 process_chat 的是校验通过的那个路径',
              _seen == [str(_link)], f'实际收到 {_seen}')


# ── 4. 校验用的是共用的那一个函数，不是各写一份 ────────────────────────
print('\n[4] 两个端点走的是 validate_real_path 本身（而非各写一份判断）')

_seen_args: list[str] = []
_orig_validate = routes.validate_real_path


def _spy(s):
    _seen_args.append(s)
    return _orig_validate(s)


routes.validate_real_path = _spy
try:
    for _name, _fn in ENDPOINTS:
        _run(_fn, _ESCAPE)
finally:
    routes.validate_real_path = _orig_validate

check('两个端点都调用了 validate_real_path',
      _seen_args.count(_ESCAPE) == 2,
      f'实际调用 {_seen_args.count(_ESCAPE)} 次（期望 2）')


# ── 收尾 ───────────────────────────────────────────────────────────────
(routes.process_chat, routes.process_chat_streaming, routes._stream_sse_response) = _orig

print()
if _fail:
    print(f'{_fail} 项失败')
    sys.exit(1)
print('ALL PASS')
