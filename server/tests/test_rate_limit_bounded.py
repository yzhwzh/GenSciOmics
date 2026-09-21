#!/usr/bin/env python3
"""限流器不得泄漏内存，且必须在并发下守住上限。

背景：`server/handler.py:18` 的 `_rates` 是 `defaultdict(list)`，以客户端 IP 为键。
`_rate_allowed` 里的 `w = _rates[ip]` 是 **defaultdict 的下标访问** —— 它不是读取，
而是「取不到就插入一个空 list」。于是每个**曾经出现过一次**的 IP 都会永久留下
一个键，`while w and w[0] < ...: w.pop(0)` 只清时间戳、从不删键。

后果与请求量无关：进程内存随「历史上连过的不同 IP 数」单调增长。而这个服务
监听 :6001 且对公网可达（`main.py` 打印外部 IP），扫描器一天能贡献几千个源地址。

第二个问题在并发侧：`ThreadingHTTPServer` 每请求一线程，而 `_rate_allowed` 是
无锁的「读 len → 判断 → append」。两个线程可以同时读到 len(w) == _RATE_MAX - 1
然后双双放行，上限被击穿。

这条脚本同时锁住两件事：**表不涨** 与 **上限在并发下不被击穿**。
判定方式（项目约定）：自包含脚本，任一断言失败则退出码非 0。
"""
from __future__ import annotations

import sys
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import handler

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


class _Clock:
    """可控时钟 —— 限流是时间相关的，真等 60 秒没法测。"""

    def __init__(self, t: float = 1_700_000_000.0) -> None:
        self.t = t

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _Patched:
    """临时替换 handler 的时间源，并清空限流表；退出时精确还原。

    **清空而不替换容器**：`handler._rates` 在改造前是 `defaultdict(list)`，
    换成普通 dict 会让旧实现原地 KeyError（`w = _rates[ip]` 靠的是 defaultdict
    的自动插入），RED 阶段的表现就变成 32 条线程栈而不是一句断言失败。
    `.clear()` 对新旧两种容器都成立，于是这条脚本在改造前后测的是**同一件事**。
    """

    def __init__(self) -> None:
        self.clock = _Clock()
        self._orig_time = None
        self._orig_max = None
        self._orig_swept = None

    def __enter__(self) -> _Clock:
        self._orig_time = handler.time
        self._orig_max = handler._RATE_MAX
        self._orig_swept = getattr(handler, '_rates_swept_at', None)
        handler.time = self.clock
        handler._rates.clear()
        if hasattr(handler, '_rates_swept_at'):
            handler._rates_swept_at = 0.0
        return self.clock

    def __exit__(self, *exc) -> None:
        handler.time = self._orig_time
        handler._RATE_MAX = self._orig_max
        handler._rates.clear()
        if self._orig_swept is not None:
            handler._rates_swept_at = self._orig_swept


# ── 1. 内存：表不得随「历史见过的 IP 数」增长 ────────────────────

def test_stale_ips_are_reaped() -> None:
    """见过一次就再也不来的 IP，过了窗口必须被清掉。"""
    with _Patched() as clock:
        for i in range(300):
            clock.advance(0.01)
            handler._rate_allowed(f'10.0.{i // 256}.{i % 256}')
        peak = len(handler._rates)
        check(peak == 300, f'300 个不同 IP 在窗口内 → 表里有 300 条（实际 {peak}）')

        clock.advance(3600)              # 一小时后，这 300 个 IP 全部过期
        handler._rate_allowed('192.0.2.1')  # 一个新 IP 触发清理

        size = len(handler._rates)
        check(size <= 2,
              f'一小时后旧 IP 被清掉（实际 {size} 条；裸 defaultdict 会是 301）')
        check('10.0.0.0' not in handler._rates, '过期 IP 的键已删除')
        check('192.0.2.1' in handler._rates, '正在使用的 IP 保留')


def test_rejected_ip_does_not_leave_a_key() -> None:
    """被拒的 IP 不该白占一个条目（键存在 ⟺ 窗口内被放行过）。"""
    with _Patched():
        handler._RATE_MAX = 0
        ok = handler._rate_allowed('203.0.113.9')
        check(ok is False, '上限为 0 时一律拒绝')
        check('203.0.113.9' not in handler._rates, '被拒的 IP 不留键')


def test_long_run_stays_flat() -> None:
    """长期运行：表的大小只取决于窗口内的活跃 IP 数，与累计请求量无关。

    上界取 2×窗口而不是恰好一个窗口：清理是每 60 秒一次的全表扫描，两次扫描
    之间新到的 IP 会先积着，稳态大小比窗口略大。那个常数是实现细节，
    **真正要断言的是它不随累计请求量增长** —— 所以跑两轮、每轮 2000 个
    一次性 IP：若表是随累计量涨的，第二轮就该是第一轮的两倍。
    """
    bound = 2 * handler._RATE_WINDOW

    def burst(clock, base: int) -> None:
        """每秒一个全新 IP，共 2000 秒 —— 都是不会回头的源地址。"""
        for i in range(2000):
            clock.advance(1.0)
            handler._rate_allowed(f'198.51.{base + i // 254}.{i % 254}')

    with _Patched() as clock:
        burst(clock, 0)
        s1 = len(handler._rates)
        check(s1 <= bound, f'第 1 轮 2000 个一次性 IP 后表 {s1} ≤ {bound}')

        burst(clock, 8)
        s2 = len(handler._rates)
        check(s2 <= bound, f'第 2 轮又 2000 个一次性 IP 后表 {s2} ≤ {bound}')
        check(s2 <= s1 + handler._RATE_WINDOW,
              f'表未随累计请求量增长（4000 个一次性 IP：第 1 轮 {s1} → 第 2 轮 {s2}）')


# ── 2. 上限：功能本身不能被改坏 ────────────────────────────────

def test_limit_still_enforced() -> None:
    """同一 IP 在窗口内最多放行 _RATE_MAX 次，第 _RATE_MAX+1 次被拒。"""
    with _Patched():
        allowed = sum(1 for _ in range(handler._RATE_MAX + 10)
                      if handler._rate_allowed('10.1.1.1'))
        check(allowed == handler._RATE_MAX,
              f'窗口内放行次数恰好 _RATE_MAX={handler._RATE_MAX}（实际 {allowed}）')
        check(handler._rate_allowed('10.1.1.1') is False, '超限后继续拒绝')
        check(handler._rate_allowed('10.1.1.2') is True, '限流只针对单个 IP，不误伤他人')


def test_window_slides() -> None:
    """窗口滑过之后，同一 IP 重新可用。"""
    with _Patched() as clock:
        for _ in range(handler._RATE_MAX):
            handler._rate_allowed('10.2.2.2')
        check(handler._rate_allowed('10.2.2.2') is False, '窗口内已满')
        clock.advance(handler._RATE_WINDOW + 1)
        check(handler._rate_allowed('10.2.2.2') is True, '窗口滑过后重新放行')


# ── 3. 并发：读-改-写必须原子 ──────────────────────────────────

class _Probe(defaultdict):
    """带上「进入/离开」时间戳的限流表。

    继承 `defaultdict(list)` 而非普通 dict：改造前 `_rate_allowed` 走的是
    `_rates[ip]`，依赖 defaultdict 自动建键。夹具如果换成普通 dict，旧实现会
    先抛 KeyError —— 那测到的是夹具失真，不是锁的缺失，两条缺陷会缠在一起。

    为什么要这么绕：直接开 32 个线程 barrier 对齐去抢配额，**测不出没加锁** ——
    实测未加锁的旧实现照样只放行 1 个。原因是 GIL：`len(w) >= _RATE_MAX` 与
    `w.append(now)` 之间只有几个字节码，切换间隔落不进去，于是「读-改-写不原子」
    这个真实缺陷在小规模下不可观测。一个改前改后都过的测试不是回归测试，
    是安慰剂。

    所以在临界区里塞进一段真实的耗时（sleep），把窗口放大到必然重叠：
      · 有锁 → 线程被串行化，同一时刻最多 1 个线程在临界区 → 重叠度恒为 1；
      · 无锁 → 32 个线程同时 sleep，重叠度接近 32。
    事件用 list.append 记录（原子操作），时间戳事后在单线程里算，
    测量本身不引入新的竞态。
    """

    def __init__(self, delay: float = 0.02) -> None:
        super().__init__(list)
        self.events: list[tuple[str, float]] = []
        self.delay = delay

    def _touch(self) -> None:
        self.events.append(('enter', time.monotonic()))
        time.sleep(self.delay)
        self.events.append(('exit', time.monotonic()))

    def get(self, *a, **kw):
        self._touch()
        return super().get(*a, **kw)

    def __getitem__(self, k):          # 旧实现走的是这个
        self._touch()
        return super().__getitem__(k)

    def __setitem__(self, k, v):
        self._touch()
        return super().__setitem__(k, v)


def _max_overlap(events: list[tuple[str, float]]) -> int:
    """由进入/离开时间戳算临界区内的最大并发数。"""
    points: list[tuple[float, int]] = [
        (ts, 1 if kind == 'enter' else -1) for kind, ts in events
    ]
    points.sort()                      # 同一时刻先算离开（保守，不会虚增重叠）
    cur = peak = 0
    for _, delta in points:
        cur += delta
        peak = max(peak, cur)
    return peak


def test_critical_section_is_mutually_exclusive() -> None:
    """`_rate_allowed` 的读-改-写必须互斥：临界区内同时只能有一个线程。"""
    probe = _Probe(delay=0.02)
    n = 32
    with _Patched() as clock:
        saved = handler._rates
        handler._rates = probe
        try:
            barrier = threading.Barrier(n)
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    barrier.wait()
                    handler._rate_allowed(f'10.3.{i // 256}.{i % 256}')
                except BaseException as e:
                    errors.append(e)

            ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            handler._rates = saved

        overlap = _max_overlap(probe.events)
        check(not errors, f'并发调用无异常（{errors[:1]}）')
        check(len(probe.events) >= n,
              f'探针被真正走到（{len(probe.events)} 次 enter/exit，≥ {n}）')
        check(overlap == 1,
              f'临界区最大重叠度 = 1（实际 {overlap}）—— 大于 1 即读-改-写未加锁')


def test_concurrent_high_volume_never_exceeds_max() -> None:
    """高压并发下放行次数不得超过上限。

    **这条不是竞态的守卫，别当它是。** 实测它在未加锁的旧实现上也通过 ——
    16 个线程各自跑 60 次调用，GIL 的切换间隔落不进「读 len → append」
    那几个字节码之间，竞态窗口压根没被碰到。它真正覆盖的是负载下的
    不崩不脏（旧实现曾在此路径上因 defaultdict 语义变化抛 KeyError）。
    互斥本身由 test_critical_section_is_mutually_exclusive 负责。
    """
    with _Patched():
        n_threads, per_thread = 16, 60
        lock = threading.Lock()
        allowed = 0
        errors: list[BaseException] = []
        barrier = threading.Barrier(n_threads)

        def worker() -> None:
            nonlocal allowed
            try:
                barrier.wait()
                hit = sum(1 for _ in range(per_thread)
                          if handler._rate_allowed('10.4.4.4'))
            except BaseException as e:
                errors.append(e)
                return
            with lock:
                allowed += hit

        ts = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        check(not errors, f'高压并发无异常（{errors[:1]}）')
        check(allowed <= handler._RATE_MAX,
              f'16×60 并发请求放行 {allowed} ≤ 上限 {handler._RATE_MAX}')


def main() -> int:
    print('限流器回归：_rates 不得泄漏 + 并发下不得击穿上限\n')
    for t in (test_stale_ips_are_reaped, test_rejected_ip_does_not_leave_a_key,
              test_long_run_stays_flat, test_limit_still_enforced, test_window_slides,
              test_critical_section_is_mutually_exclusive,
              test_concurrent_high_volume_never_exceeds_max):
        print(f'[{t.__name__}]')
        try:
            t()
        except Exception:
            FAIL.append(f'{t.__name__} raised')
            print('  ✗ 异常:\n' + traceback.format_exc())
        print()

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL RATE LIMIT CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
