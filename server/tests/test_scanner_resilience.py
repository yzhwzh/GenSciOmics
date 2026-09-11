#!/usr/bin/env python3
"""B30：坏文件对扫描的影响 —— 逐个失败模式实测，不靠猜。

起因是一句**错误结论**：scan_datasets() 逐文件没有 try/except，于是「一个坏
文件会让整个扫描线程静默死掉，datasets 从此永久为空」。实测证否：

  1. 循环里的每个逐文件调用**各自内部都有 try/except** ——
     _read_obs_stats(:165)、resolve_bulk_table(:280)、_extract_path_fields(:227)、
     _get_annotation_info(:77)。损坏的 .h5ad 在 _read_obs_stats 内就被接住了。
  2. 即使真有异常逃逸，**`datasets.clear()` 写在函数末尾**，所以列表停在上一轮
     的值，而不是被清空成 []（见 [6]）。这个写法本身就是故障原子性，不是疏漏。
  3. 就算连 `_initial_scan` 也死了，`scanner_loop`（main.py:50 另一个线程）每
     30s 还会再跑一次，且自带 try/except。**「永久为空」不成立。**

本脚本因此改为锁死**真实存在**的三条不变量，并把实测中发现的那条真实缺陷
（读失败被洗成合法的 0 计数行）单独打印，见 [8]。

运行：python3 server/tests/test_scanner_resilience.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import io
import os
import json
import sys
import shutil
import contextlib
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata

import scanner

PASS: list[str] = []
FAIL: list[str] = []
GAP: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def gap(msg: str) -> None:
    """已知缺陷 —— 打印出来但不计入退出码（未修，见 BUG_LOG B30）。"""
    GAP.append(msg)
    print('  ⚠ ' + msg)


def write_valid_h5ad(fp: Path, gene: str = 'COL1A1') -> None:
    n = 40
    obs = pd.DataFrame({'Patient': ['P1', 'P2'] * (n // 2),
                        'Group': ['Case', 'Control'] * (n // 2)})
    var = pd.DataFrame(index=[gene, 'FAP'])
    anndata.AnnData(X=np.ones((n, 2), dtype=np.float32), obs=obs, var=var).write_h5ad(str(fp))


def fixture_dir(root: Path, name: str, pmid: str) -> Path:
    """Data/<Species>/<Tissue>/<Disease>/scRNA/ —— 与真实目录结构一致。"""
    d = root / 'Monkey' / 'TestOrgan' / name / 'scRNA'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{pmid}.{name}.h5ad'


def run_scan() -> tuple[str, str]:
    """跑一轮扫描，返回 (stderr, 异常描述或空字符串)。异常不该出现，但要抓到。"""
    err = io.StringIO()
    raised = ''
    try:
        with contextlib.redirect_stderr(err):
            scanner.scan_datasets()
    except Exception as e:  # noqa: BLE001 — 这里就是要捕获"扫描挂掉"这件事
        raised = f'{type(e).__name__}: {e}'
    return err.getvalue(), raised


def row_for(pmid: str) -> dict | None:
    return next((d for d in scanner.datasets if d['pmid'] == pmid), None)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix='gensci_scan_resilience_'))
    extra_roots: list[Path] = []
    cache_file = root / '.scanner_cache.json'
    real_cache = scanner.SCANNER_CACHE_FILE
    real_dirs = scanner.DATA_DIRS
    try:
        scanner.DATA_DIRS = [root]
        scanner.SCANNER_CACHE_FILE = cache_file
        # 逐文件缓存是进程内 LRU，跨轮次存活 —— 不清掉的话「修好文件后重扫」
        # 会命中上一轮失败前的条目，测不出真实行为。
        scanner._obs_cache.clear()

        good = fixture_dir(root, 'GoodDisease', '11111111')
        write_valid_h5ad(good)

        bad = fixture_dir(root, 'BadDisease', '22222222')
        # 后缀是 .h5ad，内容是纯文本 —— 等价于被截断/损坏的数据文件。
        bad.write_bytes(b'this is not an HDF5 file at all\n')

        print('\n[1] 一个坏文件不得让整轮扫描归零，也不得让扫描抛异常')
        scanner.datasets.clear()
        stderr, raised = run_scan()
        check(raised == '', f'扫描不抛异常（实际：{raised or "无"}）')
        pmids = {d['pmid'] for d in scanner.datasets}
        check('11111111' in pmids, '健康数据集仍然入列')
        check(len(scanner.datasets) == 2, f'两轮都入列，未被坏文件打断（实际 {len(scanner.datasets)} 行）')

        print('\n[2] 坏文件本轮以 0 计数占位（B27 设计：本轮展示，下轮重试）')
        badrow = row_for('22222222')
        check(badrow is not None, '损坏文件本轮仍在列表中')
        if badrow:
            check(badrow['patient_count'] == 0 and badrow['n_obs'] == 0,
                  f'占位计数为 0（patient_count={badrow.get("patient_count")}, n_obs={badrow.get("n_obs")}）')
            # B30 核心：0 计数本身没错，错的是让它顶着 'ready' 出门 ——
            # 前端据此显示绿色 Ready + "0 / 0 / 0"，且轮询只在 status !== 'ready'
            # 时启动，于是这一行 0 永远不会自愈。失败必须自带状态。
            check(badrow['status'] == 'error',
                  f'读失败的行必须标 error 而非 ready（实际：{badrow.get("status")}）')
            check('_read_failed' not in badrow, '内部标记不外泄到接口层')
            goodrow = row_for('11111111')
            check(goodrow is not None and goodrow['status'] == 'ready',
                  f'健康行仍为 ready（实际：{goodrow.get("status") if goodrow else "缺失"}）')

        print('\n[3] 失败必须留下痕迹，不得静默')
        check('BadDisease' in stderr or '22222222' in stderr,
              'stderr 指明了是哪个文件出的问题')
        check(bool(stderr.strip()), 'stderr 非空')
        check(stderr.count('\n') == 1, f'恰好一条错误（实际 {stderr.count(chr(10))} 条）')

        print('\n[4] 读失败的结果不得落盘（B27：失败的瞬时性不能被缓存固化）')
        persisted = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        bad_keys = [k for k in persisted if '22222222' in k]
        check(not bad_keys, f'坏文件未被写入持久缓存（实际 {bad_keys}）')
        good_keys = [k for k in persisted if '11111111' in k]
        check(bool(good_keys), '健康文件已正常落盘')

        print('\n[5] 全是坏文件时也不得抛异常，且各自以 0 计数占位')
        # 独立于 root：放进 root 的话 rglob 会连它一起扫到，污染后面 [7] 的结果。
        badonly = Path(tempfile.mkdtemp(prefix='gensci_badonly_'))
        extra_roots.append(badonly)
        for name, pmid in (('OnlyBadA', '33333333'), ('OnlyBadB', '44444444')):
            fixture_dir(badonly, name, pmid).write_bytes(b'not HDF5 either\n')
        scanner.DATA_DIRS = [badonly]
        scanner._obs_cache.clear()
        _stderr3, raised3 = run_scan()
        check(raised3 == '', f'全坏时也不抛异常（实际：{raised3 or "无"}）')
        check({d['pmid'] for d in scanner.datasets} == {'33333333', '44444444'},
              f'两条都在列（实际 {sorted(d["pmid"] for d in scanner.datasets)}）')
        check(all(d['n_obs'] == 0 for d in scanner.datasets), '计数全为 0')
        scanner.DATA_DIRS = [root]

        print('\n[6] 故障注入：真有异常逃逸时，datasets 必须保持上一轮的值而非被清空')
        # 循环里没有任何 try/except，这条不变量完全靠 clear()/extend() 写在函数
        # 末尾来保证 —— 注入一个真的异常，把这个性质钉住，而不是靠读代码断言。
        scanner._obs_cache.clear()
        run_scan()
        before = [d['pmid'] for d in scanner.datasets]
        real_extract = scanner._extract_path_fields
        scanner._extract_path_fields = lambda _p: (_ for _ in ()).throw(RuntimeError('injected'))
        try:
            _stderr4, raised4 = run_scan()
        finally:
            scanner._extract_path_fields = real_extract
        check('RuntimeError' in raised4, f'注入的异常确实逃逸出扫描（实际：{raised4 or "无"}）')
        check([d['pmid'] for d in scanner.datasets] == before,
              f'列表保持原值（前 {before} → 后 {[d["pmid"] for d in scanner.datasets]}）')

        print('\n[7] 修好文件后，下一轮扫描必须认到真实数值（用户的实际工作流）')
        # 只重写坏文件：good 此刻仍被共享 backed 句柄持有，就地覆写会报
        # "unable to truncate a file which is already open"。
        write_valid_h5ad(bad)
        scanner._obs_cache.clear()
        stderr2, raised2 = run_scan()
        check(raised2 == '', f'修复后扫描不抛异常（实际：{raised2 or "无"}）')
        pmids2 = {d['pmid'] for d in scanner.datasets}
        check(pmids2 == {'11111111', '22222222'}, f'两条都在列（实际：{sorted(pmids2)}）')
        fixed = row_for('22222222')
        check(fixed is not None and fixed['n_obs'] == 40,
              f'修好后计数即为真实值（n_obs={fixed.get("n_obs") if fixed else "缺失"}，期望 40）')

        print('\n[8] 不可读目录必须留下痕迹，不得静默丢文件')
        # Path.rglob() 在 3.10 内部是 bare `except OSError: pass` —— 权限不对的目录
        # 底下有什么，调用方永远不知道。数据文件不报错、不告警、直接消失，表现为
        # "数据集少了几条"。实测：rglob 返回 3 个条目，目录里的 b.h5ad 不在其中。
        hidden = Path(tempfile.mkdtemp(prefix='gensci_hidden_'))
        extra_roots.append(hidden)
        write_valid_h5ad(fixture_dir(hidden, 'Visible', '66666666'))
        locked = hidden / 'Monkey' / 'TestOrgan' / 'Locked' / 'scRNA'
        locked.mkdir(parents=True, exist_ok=True)
        write_valid_h5ad(locked / '77777777.Locked.h5ad')
        os.chmod(locked, 0o000)
        try:
            scanner.DATA_DIRS = [hidden]
            scanner._obs_cache.clear()
            stderr_locked, raised_locked = run_scan()
        finally:
            os.chmod(locked, 0o755)
        scanner.DATA_DIRS = [root]
        check(raised_locked == '', f'不可读目录不让扫描抛异常（实际：{raised_locked or "无"}）')
        check('66666666' in {d['pmid'] for d in scanner.datasets}, '可读目录照常入列')
        check('77777777' not in {d['pmid'] for d in scanner.datasets},
              '确实扫不到（前置条件成立，否则本项无意义）')
        check('Locked' in stderr_locked,
              f'不可读目录必须出现在 stderr（实际：{stderr_locked.strip()[:60] or "空"}）')

        print('\n[9] 读成功但一个 obs 列都没有 —— 同样是读失败，不得当 ready 出门')
        # HDF5 没有事务性读取。文件写到一半时 open 可能"成功"返回一个句柄，
        # 而 obs 表还是空的：不抛异常，只是 0 行 / 0 列。_is_valid_cache_entry
        # 早就认定这种条目不可用，status 必须同意 —— 否则前端拿到绿色 Ready
        # 配 0/0/0，轮询只在 status !== 'ready' 时启动，又是一行永不愈合的 0。
        nocols = Path(tempfile.mkdtemp(prefix='gensci_nocols_'))
        extra_roots.append(nocols)
        nocols_file = fixture_dir(nocols, 'NoCols', '55555555')
        anndata.AnnData(X=np.ones((5, 2), dtype=np.float32),
                        var=pd.DataFrame(index=['COL1A1', 'FAP'])).write_h5ad(str(nocols_file))
        scanner.DATA_DIRS = [nocols]
        scanner._obs_cache.clear()
        stderr_nc, raised_nc = run_scan()
        scanner.DATA_DIRS = [root]
        check(raised_nc == '', f'不抛异常（实际：{raised_nc or "无"}）')
        ncrow = row_for('55555555')
        check(ncrow is not None, '该文件仍在列表中（失败也要出列，只是要带状态）')
        if ncrow:
            check(ncrow['status'] == 'error',
                  f'无 obs 列的读必须标 error（实际：{ncrow.get("status")}）')
            check(ncrow['n_obs'] == 0, f'占位计数为 0（实际：{ncrow.get("n_obs")}）')
            check('_read_failed' not in ncrow, '内部标记不外泄')
        check('NoCols' in stderr_nc, f'stderr 指明是哪个文件（实际：{stderr_nc.strip()[:60] or "空"}）')

    finally:
        scanner.DATA_DIRS = real_dirs
        scanner.SCANNER_CACHE_FILE = real_cache
        shutil.rmtree(root, ignore_errors=True)
        for d in extra_roots:
            shutil.rmtree(d, ignore_errors=True)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed, {len(GAP)} known gap(s)')
    for f in FAIL:
        print(f'  FAILED: {f}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
