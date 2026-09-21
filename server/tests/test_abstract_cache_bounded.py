#!/usr/bin/env python3
"""摘要缓存必须有上限：_EUROPE_PMC_CACHE 从裸 dict 迁到 LRUCache。

背景：`server/pubmed.py` 的 `_EUROPE_PMC_CACHE` 是模块级裸 dict，写入点两处
（非 PubMed ID 的占位记录 :90、成功抓取的完整记录 :264），**没有任何上限**。
键是 PMID，值是一条 `dict` —— 其中 `methods` 字段上限 100000 字符（:219）。
于是进程内存随「历史请求过的 PMID 总数」单调增长，与当前负载无关：
一个服务跑得越久、被搜过的文献越多，常驻内存越高，且永不回落。

同一个仓库里已经有正确的工具：`server/caches.py` 的 `LRUCache`
（线程安全 + OrderedDict + max_size 淘汰），`search.py` / `scanner.py` /
`routes.py` / `analysis/expression.py` 都已用它。这条脚本锁两件事：

  1. 缓存条目数封顶，且淘汰的是**最久未使用**的那条（不是任意一条）；
  2. 迁移不能碰坏 B26/B35 的写入策略 —— 抓取不完整时**照旧不写缓存**。
     这一条比容量本身更容易被改坏，所以单独测。

运行：python3 server/tests/test_abstract_cache_bounded.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import contextlib
import io
import sys
import threading
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import pubmed

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def _reset() -> None:
    pubmed._EUROPE_PMC_CACHE.clear()


def _max_size() -> int:
    return getattr(pubmed, '_ABSTRACT_CACHE_MAX', None)


@contextlib.contextmanager
def _quiet():
    """吞掉被测路径自己往 stderr 写的诊断行。

    `_fetch_abstract` 在预算耗尽时会 print 一行 —— 那是**正确行为**（B35 要求
    失败留痕），但这条脚本会故意触发它几十次，日志会把断言结果淹掉。
    只在这里静音，不动被测代码。
    """
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        yield


# ── 1. 上限本身 ────────────────────────────────────────────────

def test_cache_has_bounded_max() -> None:
    """缓存必须是有上限的实现，而不是裸 dict。"""
    n = _max_size()
    check(isinstance(n, int) and n > 0, f'pubmed 声明了正整数上限 _ABSTRACT_CACHE_MAX (实际 {n!r})')
    check(hasattr(pubmed._EUROPE_PMC_CACHE, 'set') and hasattr(pubmed._EUROPE_PMC_CACHE, 'get'),
          '_EUROPE_PMC_CACHE 是 LRUCache 实例（有 get/set）')
    check(hasattr(pubmed._EUROPE_PMC_CACHE, '_max_size'),
          '_EUROPE_PMC_CACHE 带 _max_size（即真的会被淘汰，不是无界 dict 换了个壳）')


def test_entry_count_capped() -> None:
    """写入远超上限的条目后，条目数必须封顶。

    走非 PubMed ID 分支（pmid 非纯数字）：它在 :89-91 直接返回占位记录并写缓存，
    全程不发网络，因此可以廉价地灌入大量条目 —— 这正是现实中
    「一个又一个查不到的 PKU/BALF/brain-map ID」的写法。
    """
    _reset()
    n = _max_size() or 0
    if n <= 0:
        check(False, '没有上限可测（_ABSTRACT_CACHE_MAX 缺失）')
        return
    for i in range(n + 100):
        pubmed._fetch_abstract(f'NONPUB{i}', deadline_s=0)
    size = len(pubmed._EUROPE_PMC_CACHE)
    check(size <= n, f'灌入 {n + 100} 条后缓存条目数 {size} ≤ 上限 {n}')


def test_evicts_least_recently_used() -> None:
    """淘汰的必须是最久未使用的那条，而不是随便一条。"""
    _reset()
    n = _max_size() or 0
    if n <= 0:
        check(False, '没有上限可测（_ABSTRACT_CACHE_MAX 缺失）')
        return
    pubmed._fetch_abstract('OLDEST', deadline_s=0)      # 最早写入
    for i in range(n - 1):
        pubmed._fetch_abstract(f'FILL{i}', deadline_s=0)  # 恰好填满
    pubmed._EUROPE_PMC_CACHE.get('OLDEST')               # 读一次 → 变最新
    pubmed._fetch_abstract('NEWEST', deadline_s=0)       # 触发一次淘汰

    check(pubmed._EUROPE_PMC_CACHE.get('OLDEST') is not None,
          '被读过的 OLDEST 因 LRU 语义幸存（淘汰的是 FILL0 而非它）')
    check(pubmed._EUROPE_PMC_CACHE.get('NEWEST') is not None, '新写入的条目在缓存里')
    check(pubmed._EUROPE_PMC_CACHE.get('FILL0') is None,
          '真正的 LRU 条目 FILL0 被淘汰')


# ── 2. 读写语义 ────────────────────────────────────────────────

def test_miss_returns_none() -> None:
    """cached_abstract 未命中返回 None（/api/analysis-info 依赖这个契约）。"""
    _reset()
    check(pubmed.cached_abstract('NOT_IN_CACHE') is None, 'cached_abstract 未命中 → None')


def test_hit_returns_same_object() -> None:
    """命中时返回写入的那条记录本身。"""
    _reset()
    rec = {'title': 'T', 'abstract': 'A'}
    pubmed._EUROPE_PMC_CACHE.set('PMID1', rec)
    check(pubmed.cached_abstract('PMID1') is rec, 'cached_abstract 命中返回同一条记录')


def test_nonpubmed_id_is_cached() -> None:
    """非数字 ID 的占位记录仍要写缓存（否则每次都重算）。"""
    _reset()
    info = pubmed._fetch_abstract('BALF-xyz', deadline_s=0)
    check(pubmed.cached_abstract('BALF-xyz') is info,
          '非 PubMed ID 的占位记录写入缓存')


# ── 3. B26/B35 回归：不完整的结果绝不许进缓存 ───────────────────

def test_incomplete_result_not_cached() -> None:
    """预算耗尽 → 抓取不完整 → 不写缓存（B26：一次瞬时故障不得固化）。"""
    _reset()
    before = len(pubmed._EUROPE_PMC_CACHE)
    with _quiet():
        pubmed._fetch_abstract('90000099', deadline_s=-1)   # 预算一步都没给
    after = len(pubmed._EUROPE_PMC_CACHE)
    check(after == before, f'预算耗尽时不写缓存（条目 {before} → {after}）')
    check(pubmed.cached_abstract('90000099') is None, '未缓存的 PMID 查不到')


def test_repeated_failure_does_not_grow_cache() -> None:
    """反复失败不得让缓存增长 —— 这是裸 dict 时代最容易被忽略的一侧。"""
    _reset()
    with _quiet():
        for _ in range(50):
            pubmed._fetch_abstract('90000100', deadline_s=-1)
    check(len(pubmed._EUROPE_PMC_CACHE) == 0,
          f'50 次失败后缓存仍为空（实际 {len(pubmed._EUROPE_PMC_CACHE)}）')


# ── 4. 并发 ────────────────────────────────────────────────────

def test_concurrent_writes_stay_bounded() -> None:
    """多线程并发写入时上限依然成立（ThreadingHTTPServer 下每请求一线程）。"""
    _reset()
    n = _max_size() or 0
    if n <= 0:
        check(False, '没有上限可测（_ABSTRACT_CACHE_MAX 缺失）')
        return
    errors: list[BaseException] = []

    def worker(base: int) -> None:
        try:
            for i in range(50):
                pubmed._fetch_abstract(f'PUB{base}_{i}', deadline_s=0)
        except BaseException as e:  # 线程里抛异常不会传出来，必须自己收
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(b,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check(not errors, f'并发写入无异常（{errors[:1]}）')
    check(len(pubmed._EUROPE_PMC_CACHE) <= n,
          f'8 线程 × 50 次写入后仍 ≤ 上限（实际 {len(pubmed._EUROPE_PMC_CACHE)}）')


def main() -> int:
    print('摘要缓存上限回归：_EUROPE_PMC_CACHE 不得无界增长\n')
    for t in (test_cache_has_bounded_max, test_entry_count_capped,
              test_evicts_least_recently_used, test_miss_returns_none,
              test_hit_returns_same_object, test_nonpubmed_id_is_cached,
              test_incomplete_result_not_cached, test_repeated_failure_does_not_grow_cache,
              test_concurrent_writes_stay_bounded):
        print(f'[{t.__name__}]')
        try:
            t()
        except Exception:
            FAIL.append(f'{t.__name__} raised')
            print('  ✗ 异常:\n' + traceback.format_exc())
        print()
    _reset()

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL ABSTRACT CACHE CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
