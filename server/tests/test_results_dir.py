#!/usr/bin/env python3
"""Agent 产出目录：常量来源、路径穿越守卫、skill 目录兜底钩子。

自包含（不依赖 pytest），沿用 server/tests/test_supplementary_parse.py 的骨架：
每条断言打一行 PASS/FAIL，末尾 sys.exit(1) 表明有失败。

运行：python3 server/tests/test_results_dir.py

为什么要有这个文件：
`GET /api/results?file=...` 曾把查询参数原样拼进 `RESULTS_DIR / fn`，
`RESULTS_DIR / '../../../etc/passwd'` 实测 exists=True —— 可读任意可读文件。
CLAUDE.md 的设计决策 #3 声称 real_path 有白名单校验，但这个端点从来没有。
第 2 组断言就是那条回归：改前必须 FAIL。
"""
import os
import sys
import tempfile
import time
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


# ── 1. RESULTS_DIR 单一真相源 ────────────────────────────────────────
print('\n[1] RESULTS_DIR 随 GENSCI_RESULTS_DIR 变化')

import importlib
import config

check('默认值是 /tmp/gensci_results',
      str(config.RESULTS_DIR) == '/tmp/gensci_results',
      f'实际 {config.RESULTS_DIR}')

os.environ['GENSCI_RESULTS_DIR'] = '/tmp/gensci_probe_cfg'
importlib.reload(config)
check('环境变量可覆盖', str(config.RESULTS_DIR) == '/tmp/gensci_probe_cfg',
      f'实际 {config.RESULTS_DIR}')

del os.environ['GENSCI_RESULTS_DIR']
importlib.reload(config)
check('去掉环境变量后回到默认值', str(config.RESULTS_DIR) == '/tmp/gensci_results',
      f'实际 {config.RESULTS_DIR}')

# routes 必须复用同一个绑定，不能自己再写一份字面量
import routes as R
check('routes 与 config 是同一个对象', R.RESULTS_DIR is config.RESULTS_DIR)

# ── 2. 路径穿越守卫（回归：改前 FAIL）────────────────────────────────
print('\n[2] _safe_results_path 只放行产出目录内、合法后缀的文件')

guard = getattr(R, '_safe_results_path', None)
check('_safe_results_path 存在', guard is not None)
if guard is None:
    print('\n守卫函数还没写 —— 后两组断言无法执行，视为失败')
    sys.exit(1)

with tempfile.TemporaryDirectory(prefix='gensci_results_test_') as tmp:
    root = Path(tmp)
    (root / 'plot.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    (root / 'sub').mkdir()
    (root / 'sub' / 'nested.csv').write_text('a,b\n1,2\n')
    outside = root.parent / f'{root.name}_outside.txt'
    outside.write_text('secret')

    orig_root = R.RESULTS_DIR
    R.RESULTS_DIR = root
    try:
        ok = guard('plot.png')
        check('放行普通文件 plot.png', ok == root / 'plot.png', f'实际 {ok}')

        ok = guard('sub/nested.csv')
        check('放行子目录内的文件 sub/nested.csv', ok == root / 'sub' / 'nested.csv',
              f'实际 {ok}')

        for bad, label in [
            ('../../../etc/passwd', '拒绝 ../../../etc/passwd'),
            (f'../{outside.name}', '拒绝 上一级文件 ../x'),
            ('/etc/passwd', '拒绝 绝对路径 /etc/passwd'),
            (str(outside), '拒绝 产出目录之外的绝对路径'),
            ('', '拒绝 空串'),
            (None, '拒绝 None'),
            ('sub', '拒绝 目录'),
            ('plot.exe', '拒绝 非白名单后缀 .exe'),
            ('..', '拒绝 ..'),
        ]:
            got = guard(bad)
            check(label, got is None, f'实际返回 {got}')

        # 符号链接逃逸：产出目录里一个指向外部的软链
        link = root / 'escape.png'
        try:
            link.symlink_to(outside)
        except OSError:
            print('  SKIP  符号链接逃逸（本环境不允许建软链）')
        else:
            got = guard('escape.png')
            check('拒绝 指向产出目录外的符号链接', got is None, f'实际返回 {got}')

        # 回归前提：naive 拼接确实会越界 —— 说明上面测的不是空气
        naive = root / '../../../etc/passwd'
        check('回归前提：裸拼接会越界',
              naive.exists() and not naive.resolve().is_relative_to(root.resolve()),
              f'{naive} -> {naive.resolve()}')
    finally:
        R.RESULTS_DIR = orig_root

# ── 3. skill 目录兜底钩子 ────────────────────────────────────────────
print('\n[3] _hook_skill_dir_guard 把误写进 skill 目录的文件报回对话')

import engine.hooks as H

with tempfile.TemporaryDirectory(prefix='gensci_skills_test_') as tmp:
    fake = Path(tmp)
    (fake / 'a').mkdir()
    (fake / 'a' / 'SKILL.md').write_text('doc')

    orig_skills, orig_index = H._SKILLS_DIR, H._skill_index
    H._SKILLS_DIR, H._skill_index = fake, None
    try:
        check('首次调用只建基线，不报警',
              H._hook_skill_dir_guard('shell', {}, {}) is None)
        check('无变化时不报警',
              H._hook_skill_dir_guard('shell', {}, {}) is None)

        time.sleep(0.01)
        (fake / 'a' / 'leaked_report.md').write_text('model output')
        msg = H._hook_skill_dir_guard('shell', {}, {})
        check('新增文件会报警', msg is not None)
        check('报警消息含相对路径 a/leaked_report.md',
              bool(msg) and 'a/leaked_report.md' in msg, repr(msg)[:120])
        check('报警消息指向 $GENSCI_RESULTS_DIR',
              bool(msg) and 'GENSCI_RESULTS_DIR' in msg)

        check('报警后索引已刷新，不重复报',
              H._hook_skill_dir_guard('shell', {}, {}) is None)

        time.sleep(0.01)
        (fake / 'a' / 'SKILL.md').write_text('doc, edited')
        msg = H._hook_skill_dir_guard('shell', {}, {})
        check('已存在文件被改动也会报警',
              bool(msg) and 'SKILL.md' in msg, repr(msg)[:120])
        H._hook_skill_dir_guard('shell', {}, {})

        (fake / 'a' / 'other.md').write_text('x')
        check('非 shell 工具不触发',
              H._hook_skill_dir_guard('skill', {}, {}) is None)

        (fake / '__pycache__').mkdir()
        (fake / '__pycache__' / 'mod.pyc').write_bytes(b'\x00')
        H._hook_skill_dir_guard('shell', {}, {})   # 吸收 other.md
        check('__pycache__/*.pyc 被忽略',
              H._hook_skill_dir_guard('shell', {}, {}) is None)
    finally:
        H._SKILLS_DIR, H._skill_index = orig_skills, orig_index

check('钩子已注册进 post-tool 链', H._hook_skill_dir_guard in H._post_tool_hooks)

# ── 4. ShellTool 把产出目录传给子进程 ───────────────────────────────
print('\n[4] ShellTool 注入 GENSCI_RESULTS_DIR')
import tools.ShellTool as ST

os.environ['GENSCI_RESULTS_DIR'] = '/tmp/gensci_probe_shell'
importlib.reload(config)
importlib.reload(ST)
r = ST.shell('printf %s "$GENSCI_RESULTS_DIR"')
check('子进程能看到 GENSCI_RESULTS_DIR',
      r.get('stdout', '').strip() == '/tmp/gensci_probe_shell',
      repr(r.get('stdout')))

del os.environ['GENSCI_RESULTS_DIR']
importlib.reload(config)
importlib.reload(ST)
check('未设置时回落到 /tmp/gensci_results',
      ST.shell('printf %s "$GENSCI_RESULTS_DIR"').get('stdout', '').strip()
      == '/tmp/gensci_results')

print()
if _fail:
    print(f'{_fail} 项失败')
    sys.exit(1)
print('ALL PASS')
