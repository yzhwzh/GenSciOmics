"""Hooks system — PreToolUse, PostToolUse, Stop hooks.
对标 Claude Code 的 hook 体系，用于自动注入指令。
"""
from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import Any, Callable

from config import RESULTS_DIR

# skill 树是只读的指令文档；产出必须落在 RESULTS_DIR（后者在 config.py 定义一次）。
# 本文件位于 server/engine/，故向上一级即 server/。
_SKILLS_DIR = Path(__file__).resolve().parent.parent / 'skills'

_pre_tool_hooks: list[Callable] = []
_post_tool_hooks: list[Callable] = []
_session_stop_hooks: list[Callable] = []

def register_pre_tool(fn: Callable):
    _pre_tool_hooks.append(fn); return fn

def register_post_tool(fn: Callable):
    _post_tool_hooks.append(fn); return fn

def register_session_stop(fn: Callable):
    _session_stop_hooks.append(fn); return fn

def run_pre_tool(name: str, args: dict) -> str | None:
    for hook in _pre_tool_hooks:
        r = hook(name, args)
        if r: return r
    return None

def run_post_tool(name: str, args: dict, result: dict) -> str | None:
    msgs = []
    for hook in _post_tool_hooks:
        m = hook(name, args, result)
        if m: msgs.append(m)
    return '\n'.join(msgs) if msgs else None

def run_session_stop():
    for hook in _session_stop_hooks: hook()


# ── Built-in hooks ─────────────────────────────────────

def _hook_image_return(name: str, args: dict, result: dict) -> str | None:
    """If tool returned stdout that looks like it generated a plot/image,
    remind the LLM about the image display protocol."""
    res = result.get('result', {}) if isinstance(result, dict) else {}
    stdout = ''
    if isinstance(res, dict):
        stdout = res.get('stdout', '') or ''
        stderr_val = res.get('stderr', '')
    elif isinstance(res, str):
        stdout = res
    
    # Check for image-related keywords in stdout
    triggers = ('plt.savefig', 'plt.show', 'savefig', '\.png', '\.jpg', '\.svg', 'matplotlib', 'seaborn', 'plot')
    if any(t in stdout for t in triggers):
        # Check if the output already includes /api/results markdown tag
        if '/api/results?file=' not in stdout:
            return (
                "【图片协议提醒】检测到可能生成了图片。请确保：\n"
                f"1. 将图片保存到产出目录 {RESULTS_DIR}/（即 $GENSCI_RESULTS_DIR）\n"
                "2. 在 stdout 打印 markdown 图片标签：![描述](/api/results?file=xxx.png)\n"
                "3. 在回复中**必须包含**该 markdown 标签才能在前端显示\n"
                "4. 不要用 HTML <img> 标签，ReactMarkdown 不支持"
            )
    return None


def _scan_skills(root: Path | None = None) -> dict[str, tuple[float, int]]:
    """Index every file under the skill tree as {abspath: (mtime, size)}.

    Metadata only — never reads file contents (~5 ms for the current ~570 files).
    ``__pycache__``/``*.pyc`` are skipped: running a skill script creates them, and
    they are build artifacts rather than model output.
    """
    idx: dict[str, tuple[float, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root or _SKILLS_DIR):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if fn.endswith('.pyc'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue  # vanished between walk and stat; not a write we caused
            idx[p] = (st.st_mtime, st.st_size)
    return idx


_skill_index: dict[str, tuple[float, int]] | None = None
_skill_index_lock = threading.Lock()


def _hook_skill_dir_guard(name: str, args: dict, result: dict) -> str | None:
    """Fail loudly when a shell command wrote into server/skills/.

    The skill tree holds instruction documents, not a working directory. Prompt
    text and script defaults both steer output to RESULTS_DIR, but neither stops
    a model that decides to write next to the script anyway — this does.

    The first call only establishes a baseline, so pre-existing files are never
    reported; from then on, every new or changed file is.
    """
    if name != 'shell':
        return None

    global _skill_index
    with _skill_index_lock:
        current = _scan_skills()
        if _skill_index is None:
            _skill_index = current
            return None
        modified = [p for p, sig in current.items() if _skill_index.get(p) != sig]
        _skill_index = current

    if not modified:
        return None

    shown = modified[:10]
    listing = '\n'.join(f'  - {os.path.relpath(p, _SKILLS_DIR)}' for p in shown)
    if len(modified) > len(shown):
        listing += f'\n  … 另有 {len(modified) - len(shown)} 个'
    return (
        f'【产出落点违规】检测到 {len(modified)} 个文件被写进了 skill 目录'
        '（那是指令文档，不是工作目录）：\n'
        f'{listing}\n'
        f'请立即处理：需要的产出移到 {RESULTS_DIR}/（即 $GENSCI_RESULTS_DIR），'
        '并 `rm` 掉误写进 skill 目录的文件。之后所有产出都写到 $GENSCI_RESULTS_DIR。'
    )


def _hook_error_recovery(name: str, args: dict, result: dict) -> str | None:
    """If a tool returned an error, inject recovery guidance."""
    if isinstance(result, dict) and result.get('error'):
        err = result['error']
        if 'ModuleNotFoundError' in err or 'ImportError' in err:
            return f"【错误恢复】模块缺失，尝试 `pip install <module>` 安装后重试。"
        if 'FileNotFoundError' in err or 'No such file' in err:
            return f"【错误恢复】文件未找到，用 `find` 或 `ls` 确认路径后再重试。"
        if 'Timeout' in err or 'timeout' in err:
            return f"【错误恢复】工具超时，可以增大 timeout 参数或减小数据量后重试。"
        return f"【错误恢复】工具执行出错：{err[:200]}\n检查参数是否正确，必要时尝试其他方法。"
    return None


# Register built-in hooks
register_post_tool(_hook_image_return)
register_post_tool(_hook_skill_dir_guard)
register_post_tool(_hook_error_recovery)
