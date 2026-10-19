#!/usr/bin/env python3
"""启动前检查：本项目是否已有实例在跑、端口是否被占。

挂到 npm 生命周期钩子上（见 package.json）：

    npm run start    → prestart   → 检查 5180 / 5181 / 6001 + 扫本项目残留进程
    npm run dev      → predev     → 只检查 5180 / 5181
    npm run server   → preserver  → 只检查 6001

为什么需要：vite 在端口被占时会**静默顺延**到相邻端口。反复 `npm run dev` 就会攒出
多个"看起来启动成功"的僵尸实例 —— 2026-10-19 一次清出 3 个，分别在 5182/5183/5184，
既没有客户端连接，HMR 也抢不到写死的 5181。`vite.config.ts` 的 `strictPort` 是第一道
闸（单实例自己不会漂）；本脚本是第二道：不只问"端口通不通"，还问"这台机器上是不是
已经有一个本项目的实例在跑"。

退出码：0 = 干净，可以启动；1 = 端口被占或有残留，**不要**启动。

用法：
    python3 scripts/preflight.py                    # 三个端口 + 残留进程
    python3 scripts/preflight.py --ports frontend   # 只查 5180 / 5181
    python3 scripts/preflight.py --ports backend    # 只查 6001
    python3 scripts/preflight.py --ports 5180,5181  # 也可直接给端口号
    python3 scripts/preflight.py --kill             # 先结束**本项目**的残留，再复查

`--kill` 只结束 cwd 等于本仓库根目录、且命令行确实是本项目 vite / 后端的进程；
别的程序占着端口时只报告、绝不动手。
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 端口值的三处来源，改动时请同步：
#   前端 / HMR — vite.config.ts 的 server.port 与 hmr.port
#   后端       — server/config.py 的 API_PORT
# 环境变量可覆盖，方便临时换端口调试。
FRONTEND_PORT = int(os.environ.get('GENSCI_FRONTEND_PORT', 5180))
HMR_PORT = int(os.environ.get('GENSCI_HMR_PORT', 5181))
API_PORT = int(os.environ.get('GENSCI_API_PORT', 6001))

_PORT_SETS = {
    'all': (FRONTEND_PORT, HMR_PORT, API_PORT),
    'frontend': (FRONTEND_PORT, HMR_PORT),
    'backend': (API_PORT,),
}


# ── /proc helpers ─────────────────────────────────────────────

def _cmdline(pid: int) -> str:
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def _cwd(pid: int) -> Path | None:
    try:
        return Path(os.readlink(f'/proc/{pid}/cwd'))
    except OSError:
        return None


def _elapsed(pid: int) -> str:
    """该进程已运行的时长，形如 `3d00:03` / `02:41:09`；读不到就返回 `?`。"""
    try:
        with open(f'/proc/{pid}/stat', encoding='utf-8') as f:
            # comm 里可能有空格/括号，用最后一个 ')' 切，之后第 20 项是 starttime
            start_ticks = int(f.read().rsplit(')', 1)[1].split()[19])
        with open('/proc/uptime', encoding='utf-8') as f:
            uptime = float(f.read().split()[0])
        secs = max(0, int(uptime - start_ticks / os.sysconf('SC_CLK_TCK')))
    except (OSError, ValueError, IndexError):
        return '?'
    days, secs = divmod(secs, 86400)
    hours, secs = divmod(secs, 3600)
    minutes, secs = divmod(secs, 60)
    return f'{days}d{hours:02d}:{minutes:02d}' if days else f'{hours:02d}:{minutes:02d}:{secs:02d}'


def _is_vite(cmd: str) -> bool:
    """真正的 vite 进程 —— 不看 `sh -c vite` 这层壳。"""
    first = cmd.split(' ', 1)[0]
    return first.rsplit('/', 1)[-1] == 'node' and 'node_modules/.bin/vite' in cmd


def _is_backend(cmd: str) -> bool:
    """真正的后端进程 —— 不看 `sh -c python3 server/main.py & npm run dev` 这层壳。"""
    first = cmd.split(' ', 1)[0]
    return first.rsplit('/', 1)[-1].startswith('python') and 'server/main.py' in cmd


def _project_processes() -> list[tuple[int, str, str]]:
    """本仓库的 vite / 后端进程：[(pid, 类型, 命令行)]。"""
    me = os.getpid()
    found = []
    try:
        entries = list(Path('/proc').iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        cmd = _cmdline(pid)
        if not cmd:
            continue
        if _is_vite(cmd):
            label = 'vite dev server'
        elif _is_backend(cmd):
            label = '后端 server/main.py'
        else:
            continue
        if _cwd(pid) == PROJECT_ROOT:
            found.append((pid, label, cmd))
    return sorted(found)


def _listeners() -> dict[int, list[tuple[int | None, str]]]:
    """{端口: [(pid, 命令行)]}，来自 `ss -ltnp`。"""
    try:
        proc = subprocess.run(['ss', '-ltnp'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'  ! 无法运行 ss（{e}）—— 端口检查已跳过', file=sys.stderr)
        return {}
    listeners: dict[int, list[tuple[int | None, str]]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != 'LISTEN':
            continue
        try:
            port = int(parts[3].rsplit(':', 1)[1])
        except (IndexError, ValueError):
            continue
        m = re.search(r'pid=(\d+)', line)
        pid = int(m.group(1)) if m else None
        listeners.setdefault(port, []).append((pid, _cmdline(pid) if pid else ''))
    return listeners


# ── 检查 / 清理 ───────────────────────────────────────────────

def _resolve_ports(argv: list[str]) -> tuple[int, ...]:
    if '--ports' not in argv:
        return _PORT_SETS['all']
    i = argv.index('--ports')
    if i + 1 >= len(argv):
        raise SystemExit('--ports 需要一个值：all / frontend / backend / 5180,5181')
    spec = argv[i + 1]
    if spec in _PORT_SETS:
        return _PORT_SETS[spec]
    try:
        return tuple(int(p) for p in spec.split(','))
    except ValueError:
        raise SystemExit(f'无法解析 --ports {spec!r}：应为 all / frontend / backend / 端口号列表')


def _report(ports: tuple[int, ...], scan_processes: bool) -> bool:
    """打印现状；返回 True 表示干净可启动。"""
    ok = True

    listeners = _listeners()
    for port in ports:
        hits = listeners.get(port)
        if not hits:
            print(f'  ✓ 端口 {port} 空闲')
            continue
        ok = False
        for pid, cmd in hits:
            who = f'pid {pid}, {cmd[:70]}' if pid else '未知进程（非当前用户）'
            extra = f'，已运行 {_elapsed(pid)}' if pid else ''
            print(f'  ✗ 端口 {port} 被占用（{who}{extra}）')

    if scan_processes:
        procs = _project_processes()
        if procs:
            ok = False
            print('  ✗ 本仓库已有实例在跑：')
            for pid, label, cmd in procs:
                print(f'      pid {pid}  {label}  已运行 {_elapsed(pid)}')
                print(f'        {cmd[:110]}')
        else:
            print('  ✓ 未发现本项目的残留进程')

    return ok


def _kill_project_processes() -> None:
    procs = _project_processes()
    if not procs:
        print('  没有需要结束的本项目进程')
        return
    for pid, label, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f'  → SIGTERM pid {pid}（{label}）')
        except ProcessLookupError:
            print(f'  · pid {pid} 已自行退出')
        except PermissionError:
            print(f'  ! 无权限结束 pid {pid}（{label}）')

    deadline = time.time() + 5
    pids = [p for p, _, _ in procs]
    while time.time() < deadline:
        if not any(p in {x[0] for x in _project_processes()} for p in pids):
            break
        time.sleep(0.2)


def main(argv: list[str]) -> int:
    ports = _resolve_ports(argv)
    do_kill = '--kill' in argv
    # 只查部分端口时（predev / preserver），不做全仓进程扫描 —— 另一个组件正是
    # 刚被 npm start 起起来的，把它当"残留"会误杀自己。
    scan_processes = '--ports' not in argv

    print(f'GenSciOmics 启动前检查（端口 {", ".join(map(str, ports))}）')

    if do_kill:
        _kill_project_processes()
        print()

    clean = _report(ports, scan_processes)
    print()
    if clean:
        print('✓ 干净，可以启动')
        return 0

    print('✗ 检查未通过，已中止启动。')
    print('  如果上面是上一次没关掉的实例：')
    print('      python3 scripts/preflight.py --kill')
    print('  如果占端口的是别的程序：先确认它是什么，本脚本不会去动它。')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
