#!/usr/bin/env python3
"""B42 回归测试：.h5ad 被就地改写后，后端必须自愈 —— 不得要求重启进程。

现场（2026-10-16，数据集 40425564.STGD.h5ad，3.0 GB）：
用户在后台就地修改标签、重新保存了 .h5ad。此后

    /api/analysis-info → {"stats": {..., "error": "'Unable to synchronously
                          open object (bad object header version number)'"}}
    /api/umap-data     → 同一个错误

而**任何一个新进程**都能正常打开该文件（42317 obs × 31606 vars）。
kill 掉后端重启，立刻恢复。

结论：文件是好的，坏的是**进程内缓存下来的那个句柄**。

成因是两处，各自都能把一次瞬时故障固化下来：

  1. `core.adata_cache` 按 `path:mtime` 缓存 backed 句柄，而此前只有 LRU 满 8 条
     时才关掉一条 —— 没有任何路径会因为「读不出来」而驱逐它。而 HDF5 的句柄
     **记着打开那一刻的文件元数据**：本文件用真文件（不是 mock）实测过，
     外部进程就地重写之后，本进程**连新开的句柄都读不出来**
     （`OSError: Can't synchronously read data (address of object past end of
     allocation)`），而把老句柄关掉再开就好了 —— 这正是「重启进程就好了」
     的机理：只有不再持有那个陈旧句柄，HDF5 才读得对。
  2. `routes.handle_analysis_info` / `handle_umap_data` 把**失败结果**也写进
     `_analysis_info_cache` / `_umap_cache`，而这两个缓存键里都**没有文件身份** →
     改写窗口内缓存下来的那条错误被一直复用，文件早就好了，接口还在吐旧错。

所以本测试要证明的是一句话：**不重启进程，改写后的第一次调用就能读到正确数据。**

（早先的版本写的是「第二次」—— 那时 `get_adata` 只在打开**失败**时才驱逐，而实测
打开是成功的、报错发生在之后读对象时，于是第一次请求仍会吐一次 Read failed。现在
驱逐提到了打开**之前**，第一次就过。这条断言是本次修复的验收标准本身，别放宽它。）
而且这条是用**真实文件**跑出来的，不是 mock —— 早先的版本用假对象模拟「坏句柄」，
其实那两种形状 anndata 根本产生不出来（打开时它就把 obs/var/obsm 读进内存了，
要么 open 直接抛，要么交回来的句柄元数据是齐的），于是验证的是两个同样不存在
的探针。现在全部改成真改写 + 真 HDF5 报错。

运行：python3 server/tests/test_stale_handle_selfheal.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata

import scanner
import config
import routes
import core.adata_cache as adata_cache

BAD_HEADER = 'Unable to synchronously open object (bad object header version number)'

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


class StubHandler:
    """routes 只需要 _json / _send_error 两个出口。"""

    def __init__(self) -> None:
        self.result = None
        self.error = None

    def _json(self, obj) -> None:
        self.result = obj

    def _send_error(self, msg, code=400) -> None:
        self.error = msg


@contextmanager
def poisoned_reader(err: str = BAD_HEADER):
    """让 `anndata.read_h5ad` 抛异常 —— 现场就是这么坏的。

    刻意**不**做成「返回一个读不出东西的假对象」：anndata 在打开时就把
    obs / var / obsm 读进内存，要么 open 当场地抛（现场正是
    `KeyError: 'bad object header version number'`，栈在
    `anndata/_io/h5ad.py:162 in <dictcomp>`），要么交回来的句柄元数据是齐的。
    早先版本的 mock 正是照那个不存在的形状写的，连带验证的探针也不存在，两者
    都已删除。
    """
    def _boom(*a, **k):
        raise KeyError(err)

    orig = anndata.read_h5ad
    anndata.read_h5ad = _boom
    try:
        yield
    finally:
        anndata.read_h5ad = orig


def write_h5ad_at(path: Path, n: int) -> None:
    """把一份 n 行、schema 固定的 .h5ad 写到 path。

    schema 只在这里定义一次；`external_rewrite` 的另一个进程也是 import 本函数
    来写，免得两处 schema 走偏。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    obs = pd.DataFrame({
        'Patient': ['P1', 'P2'] * (n // 2),
        'Sample': ['S1', 'S2', 'S3'] * (n // 3),
        'Group': ['G1', 'G2'] * (n // 2),
        'CellType': ['T', 'B', 'M'] * (n // 3),
        'Tissue': ['Tissue'] * n,
    }, index=[f'c{i}' for i in range(n)])
    obsm = {'X_umap': np.random.RandomState(0).rand(n, 2).astype(np.float32)}
    anndata.AnnData(X=np.zeros((n, 3), dtype=np.float32), obs=obs, obsm=obsm).write_h5ad(path)


def make_fixture(root: Path, n: int = 60) -> Path:
    """Data/<Species>/<Tissue>/<Disease>/scRNA/<pmid>.<disease>.h5ad"""
    fp = root / 'Monkey' / 'TestOrgan' / 'TestDisease' / 'scRNA' / '99999999.TestDisease.h5ad'
    write_h5ad_at(fp, n)
    return fp


# 在**另一个进程**里写文件，等价于「用户在后台重存了这份数据」。
# 必须另起进程：本进程只要还开着这个文件的句柄，h5py 就拒绝 truncate
# （实测 `OSError: unable to truncate a file which is already open`），
# 而且 HDF5 会在同一进程内复用陈旧的元数据 —— 后者正是现场那个错。
_WRITER = (
    'import sys, importlib.util\n'
    'spec = importlib.util.spec_from_file_location("_b42_writer", sys.argv[1])\n'
    'm = importlib.util.module_from_spec(spec)\n'
    'spec.loader.exec_module(m)\n'
    'm.write_h5ad_at(__import__("pathlib").Path(sys.argv[2]), int(sys.argv[3]))\n'
)


def external_rewrite(dst: Path, n: int, in_place: bool = True) -> None:
    """在另一个进程里把 dst 换成 n 行的新文件。

    in_place=True  → 直接覆盖同一个 inode（用户那件事的形态）
    in_place=False → 先写临时文件、再 os.replace 过去（换 inode；很多工具有的写法）
    """
    target = dst if in_place else dst.with_suffix('.tmp.h5ad')
    env = {**os.environ, 'HDF5_USE_FILE_LOCKING': 'FALSE'}
    subprocess.run(
        [sys.executable, '-c', _WRITER, str(Path(__file__).resolve()), str(target), str(n)],
        check=True, env=env,
    )
    if not in_place:
        os.replace(target, dst)


def _reset(root: Path) -> None:
    """Reset scan root + all three layers of cache."""
    scanner.DATA_DIRS = [root]
    scanner._obs_cache.clear()
    routes._analysis_info_cache.clear()
    routes._umap_cache.clear()
    for a in list(adata_cache._cache.values()):
        try:
            a.file.close()
        except Exception:
            pass
    adata_cache._cache.clear()


def _is_closed(adata) -> bool:
    try:
        return not adata.file.id.valid
    except Exception:
        return True


# ── 第 1 层：core.adata_cache 的句柄缓存 ──────────────────────────────

def test_invalidate_evicts_every_handle_for_path(root: Path) -> None:
    """invalidate(path) 必须把该 path 的句柄全部摘掉并关闭。"""
    _reset(root)
    fp = make_fixture(root)

    a = adata_cache.get_adata(str(fp))
    check(len(adata_cache._cache) == 1, '正常读取后句柄入缓存')

    adata_cache.invalidate(str(fp))
    check(len(adata_cache._cache) == 0, 'invalidate 摘掉该 path 的缓存条目')
    check(_is_closed(a), 'invalidate 同时关闭了句柄（不泄漏 HDF5 文件描述符）')

    b = adata_cache.get_adata(str(fp))
    check(b is not a, 'invalidate 之后重新打开，而不是复用旧对象')


def test_failure_inside_lock_evicts_handle(root: Path) -> None:
    """with 体内抛异常（句柄用着用着才坏）→ 该句柄必须被驱逐。"""
    _reset(root)
    fp = make_fixture(root)

    with adata_cache.locked_backed_adata(str(fp)) as adata:
        _ = adata.obs
    check(len(adata_cache._cache) == 1, '正常退出 → 句柄留在缓存里（不无谓重开）')

    try:
        with adata_cache.locked_backed_adata(str(fp)) as adata:
            _ = adata.obs
            raise RuntimeError('simulated stale handle')
    except RuntimeError:
        pass
    check(len(adata_cache._cache) == 0,
          'with 体内抛异常 → 坏句柄被驱逐，下次调用重新打开')


def test_rewritten_file_gets_fresh_handle(root: Path) -> None:
    """文件换了（os.replace 换 inode）→ 缓存的句柄必须让位。

    这条是**静默**的那一半：实测老句柄此后会继续回答旧数据（行数还是老的）
    而**不报任何错**。静默的错比报错更难发现 —— 用户看到的是「我明明改了，
    点进去还是老的」。缓存键里的 inode 让这种替换必然 miss。
    """
    _reset(root)
    fp = make_fixture(root, 60)

    before = adata_cache.get_adata(str(fp))
    check(before.n_obs == 60, f'替换前读到 60 行 (实际 {before.n_obs})')
    check(len(adata_cache._cache) == 1, '句柄已入缓存')

    external_rewrite(fp, 90, in_place=False)

    after = adata_cache.get_adata(str(fp))
    check(after is not before, '文件身份变了 → 重新打开，而不是复用旧句柄')
    check(after.n_obs == 90,
          f'必须读到新文件的 90 行，而不是旧字节上的 60 行 (实际 {after.n_obs})')


# ── 第 2 层：scanner 必须能自愈（用户真正看到的那个徽标） ──────────────

def test_scanner_recovers_without_restart(root: Path) -> None:
    """同一进程、不做任何手工清理，第二次读就得成功。"""
    _reset(root)
    fp = make_fixture(root)
    mtime = fp.stat().st_mtime

    with poisoned_reader():
        first = scanner._read_obs_stats(fp, mtime)
    check(first.get('_read_failed') is True,
          '读失败 → 本次判失败（B30 已知行为，不落盘）')

    second = scanner._read_obs_stats(fp, mtime)
    check(not second.get('_read_failed'),
          '第二次读必须成功 —— 不重启进程、不清缓存（B42：自愈）')
    check(second.get('n_obs') == 60,
          f"第二次读拿到真实数据 (n_obs={second.get('n_obs')}，期望 60)")
    check(bool(second.get('obs_columns')),
          '第二次读带回 obs 列，而不是全 0 占位')


# ── 第 3 层：API 响应缓存不得固化失败 ──────────────────────────────

@contextmanager
def _patched_route_deps(root: Path):
    """把路径白名单与 scanner 缓存文件指到临时目录，避免碰真实数据。"""
    orig_validate = routes.validate_real_path
    orig_cache_file = config.SCANNER_CACHE_FILE
    routes.validate_real_path = lambda p: Path(p)
    config.SCANNER_CACHE_FILE = root / 'no_such_scanner_cache.json'
    try:
        yield
    finally:
        routes.validate_real_path = orig_validate
        config.SCANNER_CACHE_FILE = orig_cache_file


def test_analysis_info_error_not_cached(root: Path) -> None:
    """/api/analysis-info 第一次报错之后，第二次不得继续吐那个旧错误。"""
    _reset(root)
    fp = make_fixture(root)

    with _patched_route_deps(root):
        h1 = StubHandler()
        with poisoned_reader():
            routes.handle_analysis_info(h1, {'pmid': '99999999', 'real_path': str(fp)})
        check(bool(h1.result and h1.result['stats'].get('error')),
              '读失败 → 本次 API 如情报错（瞬时状态，可接受）')

        h2 = StubHandler()
        routes.handle_analysis_info(h2, {'pmid': '99999999', 'real_path': str(fp)})
        got = h2.result['stats'] if h2.result else {}
        check(not got.get('error'),
              f"第二次请求不得复用上次的错误结果 (error={got.get('error')!r})")
        check(got.get('cells') == 60,
              f"第二次请求拿到真实数据 (cells={got.get('cells')}，期望 60)")


def test_umap_error_not_cached(root: Path) -> None:
    """/api/umap-data 同上 —— 它的缓存键里同样没有文件身份。"""
    _reset(root)
    fp = make_fixture(root)

    with _patched_route_deps(root):
        h1 = StubHandler()
        with poisoned_reader():
            routes.handle_umap_data(h1, {'real_path': str(fp), 'color_by': 'CellType'})
        check(bool(h1.result and h1.result.get('error')),
              '读失败 → 本次 UMAP 请求如情报错')

        h2 = StubHandler()
        routes.handle_umap_data(h2, {'real_path': str(fp), 'color_by': 'CellType'})
        got = h2.result or {}
        check(not got.get('error'),
              f"第二次请求不得复用上次的错误结果 (error={got.get('error')!r})")
        check(len(got.get('points') or []) == 60,
              f"第二次请求拿到真实坐标 (points={len(got.get('points') or [])}，期望 60)")
        check('read_failed' not in got,
              'read_failed 是内部信号，必须在返回给前端前剥掉')


# ── 端到端：真文件、真 HDF5 报错、不重启进程 ──────────────────────────

def test_selfheals_after_external_inplace_rewrite(root: Path) -> None:
    """用户的原始场景，端到端，用真文件跑。

    这里没有任何 mock：先让接口正常服务一次（句柄进缓存），再让**另一个进程**
    就地重写这个 .h5ad，然后继续用同一个进程打接口。实测的真相是 ——

      * 本进程**连新开的句柄都读不出来**（`address of object past end of
        allocation`），因为 HDF5 记着打开那一刻的元数据。这正是「重启才好」的
        机理，也是为什么必须**驱逐**（关掉句柄），光「换个键重开」不够；
      * 驱逐之后下一次调用就恢复正常，并且读到的是**改写后的**数据。

    所以关键断言只有一个：不重启进程，后续请求必须拿到新数据。
    """
    _reset(root)
    fp = make_fixture(root, 60)

    with _patched_route_deps(root):
        h0 = StubHandler()
        routes.handle_umap_data(h0, {'real_path': str(fp), 'color_by': 'CellType'})
        check(len((h0.result or {}).get('points') or []) == 60,
              f"改写前正常服务 60 个点 (实际 {len((h0.result or {}).get('points') or [])})")
        check(len(adata_cache._cache) == 1, '句柄已进缓存')

        external_rewrite(fp, 90, in_place=True)   # ← 用户在另一个进程里重存

        got: dict = {}
        attempts = 0
        for attempts in range(1, 4):
            h = StubHandler()
            routes.handle_umap_data(h, {'real_path': str(fp), 'color_by': 'CellType'})
            got = h.result or {}
            if not got.get('error'):
                break

        check(not got.get('error'),
              f"改写后必须自愈，不得要求重启进程（第 {attempts} 次尝试仍报 "
              f"error={got.get('error')!r}）")
        # 第 1 次就得成功。早先的版本只要求「不重启也能恢复」，那实际上允许
        # 用户先看到一次 Read failed、刷新一下才好 —— 而这正是用户在问的事。
        # 之所以能第 1 次就过，是 get_adata 在**打开之前**先驱逐了身份对不上的
        # 旧句柄（旧句柄会污染整个进程对该文件的 HDF5 视图，新句柄也读不对）。
        check(attempts == 1,
              f"改写后的第一次请求就必须成功（实际第 {attempts} 次才成功）")
        check(len(got.get('points') or []) == 90,
              f"自愈后必须读到改写后的 90 个点，而不是缓存里的 60 "
              f"(实际 {len(got.get('points') or [])})")


def test_umap_cache_does_not_outlive_the_file(root: Path) -> None:
    """响应缓存里那份结果，不得活得比它依据的字节更久（B42 的根因）。

    以前 umap / analysis-info 的缓存键里只有 path + 查询参数，**没有文件身份**：
    改写窗口里第一次请求存下来的东西（哪怕是个错误）此后就被一直复用，键再也没
    变过 —— 这是「改完数据必须重启后端」最直接的那一环。
    """
    _reset(root)
    fp = make_fixture(root, 60)

    with _patched_route_deps(root):
        h1 = StubHandler()
        routes.handle_umap_data(h1, {'real_path': str(fp), 'color_by': 'CellType'})
        check(len((h1.result or {}).get('points') or []) == 60,
              f"改写前 60 个点 (实际 {len((h1.result or {}).get('points') or [])})")

        external_rewrite(fp, 120, in_place=False)

        h2 = StubHandler()
        routes.handle_umap_data(h2, {'real_path': str(fp), 'color_by': 'CellType'})
        got = h2.result or {}
        check(not got.get('error'), f"改写后不得报错 (error={got.get('error')!r})")
        check(len(got.get('points') or []) == 120,
              f"改写后必须重新读，不得服务缓存里的 60 个点 "
              f"(实际 {len(got.get('points') or [])}，期望 120)")


def main() -> int:
    print('B42 regression: 就地改写 .h5ad 之后必须自愈\n')
    root = Path(tempfile.mkdtemp(prefix='b42_stale_handle_'))
    saved_dirs = scanner.DATA_DIRS
    try:
        for t in (test_invalidate_evicts_every_handle_for_path,
                  test_failure_inside_lock_evicts_handle,
                  test_rewritten_file_gets_fresh_handle,
                  test_scanner_recovers_without_restart,
                  test_analysis_info_error_not_cached,
                  test_umap_error_not_cached,
                  test_selfheals_after_external_inplace_rewrite,
                  test_umap_cache_does_not_outlive_the_file):
            print(f'[{t.__name__}]')
            try:
                t(root)
            except Exception:
                FAIL.append(f'{t.__name__} raised')
                print('  ✗ 异常:\n' + traceback.format_exc())
            print()
    finally:
        scanner.DATA_DIRS = saved_dirs
        shutil.rmtree(root, ignore_errors=True)

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL B42 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
