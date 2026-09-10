#!/usr/bin/env python3
"""B27 回归测试：瞬时 obs 读取失败不得被当成权威结果持久化。

背景：scanner._read_obs_stats 读失败时返回全 0 兜底，调用方把它写进
.scanner_cache.json；持久缓存按 mtime 复用，文件 mtime 不再变化 →
一次瞬时 HDF5 并发读失败 = 永久 Patient 0（B26 同类缺陷的持久化版本）。

运行：python3 server/tests/test_scanner_obs_cache.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import sys
import shutil
import tempfile
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata

import scanner
import core.adata_cache as adata_cache

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def make_fixture(root: Path) -> Path:
    """Data/<Species>/<Tissue>/<Disease>/scRNA/<pmid>.<disease>.h5ad"""
    d = root / 'Monkey' / 'TestOrgan' / 'TestDisease' / 'scRNA'
    d.mkdir(parents=True, exist_ok=True)
    fp = d / '99999999.TestDisease.h5ad'
    n = 60
    obs = pd.DataFrame({
        'Patient': ['P1', 'P2'] * (n // 2),
        'Sample': ['S1', 'S2', 'S3'] * (n // 3),
        'Group': ['G1', 'G2'] * (n // 2),
        'CellType': ['T', 'B', 'M'] * (n // 3),
        'Tissue': ['Tissue'] * n,
    }, index=[f'c{i}' for i in range(n)])
    ad = anndata.AnnData(X=np.zeros((n, 3), dtype=np.float32), obs=obs)
    ad.write_h5ad(fp)
    return fp


def _reset(root: Path) -> None:
    """Reset scan root + caches. Closes shared handles first — the fixture
    writes to the same path, and h5py cannot truncate a file that is open."""
    scanner.DATA_DIRS = [root]
    scanner._obs_cache.clear()
    for a in list(adata_cache._cache.values()):
        try:
            a.file.close()
        except Exception:
            pass
    adata_cache._cache.clear()


def test_failure_not_persisted(root: Path) -> None:
    """读取失败 → 展示层给占位值，但绝不写进持久缓存。"""
    _reset(root)
    fp = make_fixture(root)
    orig = anndata.read_h5ad

    def boom(*a, **k):
        raise RuntimeError("Can't synchronously read data (bad heap index)")

    anndata.read_h5ad = boom
    try:
        cache: dict = {}
        res = scanner.resolve_h5ad(fp, cache)
    finally:
        anndata.read_h5ad = orig

    check(cache == {}, f'读取失败时不得写持久缓存 (实际写入 {len(cache)} 条)')
    check(res is not None, '读取失败时仍返回可渲染的条目')
    if res is not None:
        check(res.get('patient_count', 0) == 0, '失败时为占位值(仅本次展示，未固化)')


def test_legacy_poisoned_entry_recomputed(root: Path) -> None:
    """已中毒的旧缓存条目（obs_columns 为空）应被判为无效并重算。"""
    _reset(root)
    fp = make_fixture(root)
    cache = {str(fp): {
        'mtime': fp.stat().st_mtime, 'filename': fp.name, 'species': 'Monkey',
        'tissue': 'TestOrgan', 'disease': 'TestDisease', 'pmid': '99999999',
        'omics_type': 'scRNA', 'size_mb': 0.1,
        'patient_count': 0, 'sample_count': 0, 'celltype_count': 0,
        'celltype_names': [], 'n_obs': 0, 'n_vars': 0, 'disease_count': 0,
        'group_dist': '', 'tissue_obs': '', 'sample_names': [],
        'group_names': [], 'obs_columns': [],
    }}
    res = scanner.resolve_h5ad(fp, cache)
    got = res.get('patient_count') if res else None
    check(got == 2, f'中毒条目应被重算 (patient_count 得到 {got}，期望 2)')


def test_success_persists(root: Path) -> None:
    """成功读取 → 正常写缓存，值正确（对照组）。"""
    _reset(root)
    fp = make_fixture(root)
    cache: dict = {}
    res = scanner.resolve_h5ad(fp, cache)
    check(str(fp) in cache, '成功读取后写入持久缓存')
    check(cache.get(str(fp), {}).get('patient_count') == 2,
          f"缓存 patient_count={cache.get(str(fp), {}).get('patient_count')} (期望 2)")
    check(res is not None and res.get('n_obs') == 60, 'n_obs 正确 (期望 60)')


def test_uses_shared_locked_handle(root: Path) -> None:
    """obs 读取必须走共享 backed 句柄（不得自开第二个 h5py File）。"""
    _reset(root)
    fp = make_fixture(root)
    fn = getattr(scanner, 'locked_backed_adata', None)
    check(fn is not None, 'scanner 复用 core.adata_cache.locked_backed_adata (共享句柄)')
    if fn is None:
        return
    calls: list[str] = []
    orig = scanner.locked_backed_adata

    def spy(path):
        calls.append(str(path))
        return orig(path)

    scanner.locked_backed_adata = spy
    try:
        scanner._read_obs_stats(fp, fp.stat().st_mtime)
    finally:
        scanner.locked_backed_adata = orig
    check(len(calls) == 1, f'obs 读取经由共享锁定句柄 (调用 {len(calls)} 次)')


def main() -> int:
    print('B27 regression: scanner obs 失败不得固化\n')
    root = Path(tempfile.mkdtemp(prefix='b27_scanner_'))
    saved_dirs = scanner.DATA_DIRS
    try:
        for t in (test_failure_not_persisted, test_legacy_poisoned_entry_recomputed,
                  test_success_persists, test_uses_shared_locked_handle):
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
    print('ALL B27 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
