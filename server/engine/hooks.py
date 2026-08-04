"""Hooks system — PreToolUse, PostToolUse, Stop hooks.
对标 Claude Code 的 hook 体系，用于自动注入指令。
"""
from __future__ import annotations
from typing import Any, Callable

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
                "1. 将图片保存到 /tmp/gensci_results/ 目录\n"
                "2. 在 stdout 打印 markdown 图片标签：![描述](/api/results?file=xxx.png)\n"
                "3. 在回复中**必须包含**该 markdown 标签才能在前端显示\n"
                "4. 不要用 HTML <img> 标签，ReactMarkdown 不支持"
            )
    return None


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
register_post_tool(_hook_error_recovery)
