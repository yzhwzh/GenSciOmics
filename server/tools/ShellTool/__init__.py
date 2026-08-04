"""ShellTool — 对标 Claude Code 的 BashTool。
智能超时：有输出就不算超时，三级超时策略。"""
from __future__ import annotations
import os
import select
import signal
import subprocess
import time
from skills import register_skill, ParamDef

# ── 三级超时常量 ──────────────────────────────────────────
INITIAL_GRACE = 120   # 首次输出等待（h5ad 加载可能 30-60s 无输出）
IDLE_TIMEOUT = 60     # 空闲超时（有过输出后，沉默超过此时间杀）
ABSOLUTE_CEILING = 600  # 绝对上限（无论有无输出，10 分钟后强杀）


def _kill_process(proc):
    """Kill a process and its whole process group."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _read_line_nonblocking(pipe, timeout=1.0) -> bytes | None:
    """Read one line from a pipe with timeout. Returns None if no data."""
    ready, _, _ = select.select([pipe], [], [], timeout)
    if ready:
        return pipe.readline()
    return None


def shell(command: str, timeout: int = 60) -> dict:
    """Execute a shell command with smart idle timeout.

    三级超时策略（由架构评估确定）：
    1. 首次输出等待：120s — 给加载大文件留出时间
    2. 空闲超时：60s（可配，通过 timeout 参数）— 有过输出后沉默超时
    3. 绝对上限：600s — 安全网

    Args:
        command: shell 命令
        timeout: 空闲超时秒数（默认 60s，上限 300s）
    """
    idle_timeout = min(timeout, 300)

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并 stderr，避免管道死锁
            env=env,
            preexec_fn=os.setsid,  # 进程组，便于 kill 子进程
            text=False,  # 自己控制 decode
        )
    except Exception as e:
        return {'error': f'Failed to start process: {e}', '_command': command}

    accumulated: list[str] = []
    last_output = time.time()
    t0 = time.time()
    has_output = False

    try:
        while proc.poll() is None:
            elapsed = time.time() - t0

            # 三级检查：绝对上限
            if elapsed > ABSOLUTE_CEILING:
                _kill_process(proc)
                return {
                    'error': f'Absolute timeout ({ABSOLUTE_CEILING}s) — process killed',
                    '_command': command,
                    'stdout': ''.join(accumulated)[-5000:],
                }

            # 三级检查：空闲超时（首次等待用 INITIAL_GRACE，之后用 idle_timeout）
            idle = time.time() - last_output
            grace = INITIAL_GRACE if not has_output else idle_timeout
            if idle > grace:
                _kill_process(proc)
                return {
                    'error': f'Idle timeout ({grace}s without output) — process killed',
                    '_command': command,
                    'stdout': ''.join(accumulated)[-5000:],
                }

            # 非阻塞读取一行
            line = _read_line_nonblocking(proc.stdout, timeout=1.0)
            if line is not None:
                if len(line) > 100_000:
                    line = line[:100_000] + b'\n[line truncated]\n'
                text = line.decode('utf-8', errors='replace')
                accumulated.append(text)
                last_output = time.time()
                has_output = True

        # 进程已结束，读取剩余输出
        try:
            remaining = proc.stdout.read()
            if remaining:
                accumulated.append(remaining.decode('utf-8', errors='replace'))
        except Exception:
            pass

    except Exception as e:
        _kill_process(proc)
        return {'error': str(e), '_command': command}

    finally:
        if proc.poll() is None:
            _kill_process(proc)

    full = ''.join(accumulated)
    return {
        'stdout': full[-5000:],
        'stderr': '',  # 已合并到 stdout
        'returncode': proc.returncode,
        '_command': command,
    }


SHELL_DESCRIPTION = (
    "Execute shell commands. Use this to run Python/R scripts, install packages, manipulate files, "
    "or call any command-line tool.\n\n"
    "### Constraints\n"
    "- stdout: truncated to last 5,000 characters\n"
    "- stderr: merged into stdout\n"
    "- Timeout: smart idle timeout — 120s initial grace + 60s idle + 600s absolute ceiling\n"
    "  (pass `timeout=N` to set idle timeout in seconds, capped at 300s)\n"
    "  Scripts that produce output keep running; silent scripts get killed.\n"
    "- For long Python scripts, use `print(..., flush=True)` to reset the idle timer\n"
    "- No binary data in return value (text only)\n\n"
    "### Image Protocol\n"
    "When generating plots via Python:\n"
    "1. Save PNG to `/tmp/gensci_results/{uuid}.png`\n"
    "2. Print `![description](/api/results?file={filename}.png)` to stdout\n"
    "3. The LLM MUST echo this markdown tag in its response\n\n"
    "### Error Recovery\n"
    "- Module not found → install with pip first\n"
    "- File not found → verify path with ls\n"
    "- If output is truncated → write to file and cat it in a second command"
)

register_skill(name='shell', description=SHELL_DESCRIPTION,
               params=[ParamDef(name='command', type='string', description='命令'),
                       ParamDef(name='timeout', type='integer', description='超时秒数', required=False)])(shell)
