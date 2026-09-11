#!/usr/bin/env python3
"""K 个基因列只读一次矩阵 —— `extract_gene_columns` / `in_memory_matrix` 回归测试。

背景：`adata.X` 在 backed 模式下是惰性 `_CSRDataset`，不是数组。anndata 的快路径
要求**行轴**是 slice；列索引不是 slice，于是回落到 `to_memory()`，把整个矩阵从盘上
读出来（174k 细胞数据集上 934 MB）。所以「每个基因切一次」的写法等于把同一份矩阵读 K 次。

实测（Monkey 174233 × 31165，2026-09-11）：
    K=1 → 1.01x（持平）  K=2 → 1.55x  K=3 → 1.88x  K=5 → 2.23x  K=7 → 2.45x

本测试钉住两件事，缺一不可：
  (a) **值不变** —— 新写法与旧写法逐位相同（改坏索引就是静默的生物学错误）
  (b) **读次数不变** —— 每次调用 `to_memory()` 至多发生一次（这才是优化本身）

只有 (a) 的话，切片写法写错也能过；(b) 带一个旧写法对照组，先证明计数器确实有效。

运行：python3 server/tests/test_gene_column_extraction.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。

合成数据（48 细胞 × 6 基因，稀疏，值域 0–5），obs 列 Sample / Group / CellType。
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import traceback
from pathlib import Path

# 必须在 import anndata 之前设置，否则并发读会挂
os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata
import scipy.sparse as sp

from analysis.utils import extract_gene_columns, in_memory_matrix
from analysis.stats import _get_aggregate_table, _get_raw_expression
from analysis.expression import _get_expression_stats

GENES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6']
N_CELLS = 48

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        PASS.append(label)
        print(f'  ✓ {label}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(label)
        print(f'  ✗ {label}  {detail}')


class CountingToMemory:
    """统计 `to_memory()` 在块内的调用次数。

    在**类**上打补丁，不是在实例上 —— 被测函数走 `get_adata()` 拿到的是缓存里的
    另一个 AnnData 实例，但类型相同，所以类级补丁照样计数。
    """

    def __init__(self, backed_adata):
        self.cls = type(backed_adata.X)
        self.calls = 0

    def __enter__(self):
        self._orig = self.cls.to_memory
        outer = self

        def counting(inner_self):
            outer.calls += 1
            return outer._orig(inner_self)

        self.cls.to_memory = counting
        return self

    def __exit__(self, *exc):
        self.cls.to_memory = self._orig
        return False


def build_dataset(tmpdir: str) -> Path:
    rng = np.random.default_rng(1234)
    mat = rng.integers(0, 6, size=(N_CELLS, len(GENES))).astype(np.float32)
    mat[rng.random(size=mat.shape) < 0.35] = 0.0  # 稀疏化，避免全稠密
    obs = pd.DataFrame(
        {
            'Sample': [f'S{i % 4}' for i in range(N_CELLS)],
            'Group': ['Control' if i % 2 else 'Disease' for i in range(N_CELLS)],
            'CellType': [['T', 'B', 'M'][i % 3] for i in range(N_CELLS)],
        },
        index=[f'cell{i}' for i in range(N_CELLS)],
    )
    adata = anndata.AnnData(X=sp.csr_matrix(mat), obs=obs, var=pd.DataFrame(index=GENES))
    path = Path(tmpdir) / 'col_extract.h5ad'
    adata.write_h5ad(path)
    return path


def run() -> None:
    tmpdir = tempfile.mkdtemp(prefix='gensci_cols_')
    try:
        path = build_dataset(tmpdir)
        backed = anndata.read_h5ad(path, backed='r')
        # 非 backed 读取作为真值来源 —— 与新写法走完全独立的代码路径
        truth = anndata.read_h5ad(path)

        print('\n[backed 句柄]')
        check('X 是 backed 惰性句柄（非内存矩阵）', hasattr(backed.X, 'to_memory'),
              f'type={type(backed.X).__name__}')
        check('in_memory_matrix 对内存矩阵原样返回', in_memory_matrix(truth.X) is truth.X)

        print('\n[值：与真值逐位相同]')
        idx = [0, 2, 4]
        got = extract_gene_columns(backed.X, idx)
        check('返回键 == 请求索引', set(got) == set(idx), f'得到 {sorted(got)}')
        for gi in idx:
            want = np.asarray(truth.X[:, gi].todense()).flatten()
            check(f'{GENES[gi]} 列值逐位相同', np.array_equal(got[gi], want),
                  f'dtype={got[gi].dtype}')

        print('\n[边界]')
        check('空索引 → {}', extract_gene_columns(backed.X, []) == {})
        check('全负索引（未解析基因）→ {}', extract_gene_columns(backed.X, [-1, -3]) == {})
        dup = extract_gene_columns(backed.X, [1, 1, 1])
        check('重复索引去重为一个键', list(dup) == [1], f'得到 {list(dup)}')
        check('乱序索引返回同一结果',
              set(extract_gene_columns(backed.X, [4, 0, 2])) == set(idx))

        print('\n[读次数：对照组 —— 旧写法确实读 K 次]')
        with CountingToMemory(backed) as old:
            for gi in [0, 1, 2]:
                _ = backed.X[:, gi].toarray().flatten()
        check('旧写法 K=3 → to_memory 3 次', old.calls == 3, f'实际 {old.calls}')

        print('\n[读次数：新写法只读一次]')
        with CountingToMemory(backed) as new:
            extract_gene_columns(backed.X, [0, 1, 2])
        check('K=3 → to_memory 1 次', new.calls == 1, f'实际 {new.calls}')

        with CountingToMemory(backed) as one:
            extract_gene_columns(backed.X, [0])
        check('K=1 → to_memory 1 次（与旧写法持平，2.23x 的收益从 K=2 起）',
              one.calls == 1, f'实际 {one.calls}')

        print('\n[端到端：_get_aggregate_table 的 Merge 路径]')
        # 主基因 G1 + 合并集 G2|G3|G4 = 4 次 _dense 调用
        with CountingToMemory(backed) as agg:
            res = _get_aggregate_table(str(path), 'G1', 'Group', 'CellType', 'G2|G3|G4', 'M', 'or')
        check('无 error', 'error' not in res, str(res.get('error', ''))[:120])
        check('Merge(K=4) 全程 to_memory 1 次（改前为 4 次）', agg.calls == 1,
              f'实际 {agg.calls}')

        # 值对拍：M = 成员任一表达
        member_pos = np.zeros(N_CELLS, dtype=bool)
        for name in ['G2', 'G3', 'G4']:
            col = np.asarray(truth.X[:, GENES.index(name)].todense()).flatten()
            member_pos |= col > 0
        m_rows = [r for r in res.get('rows', []) if r['Gene'] == 'M']
        check('M 行存在', len(m_rows) > 0, f'共 {len(m_rows)} 行')
        # 注意字段语义：CellTypeNumber 是该 celltype 的细胞总数（与基因无关），
        # 阳性细胞数才是 GeneExpressionNumber。
        m_pos = sum(r['GeneExpressionNumber'] for r in m_rows)
        check('M 的阳性细胞数 == 成员并集大小', m_pos == int(member_pos.sum()),
              f'表 {m_pos} vs 真值 {int(member_pos.sum())}')

        print('\n[端到端：_get_expression_stats 多基因]')
        with CountingToMemory(backed) as expr:
            est = _get_expression_stats(path, 'G1,G2,G3', 'Sample', '', 'Group')
        check('无 error', 'error' not in est, str(est.get('error', ''))[:120])
        check('3 基因 to_memory 1 次', expr.calls == 1, f'实际 {expr.calls}')
        # by_sample 的键是**小写** gene，阳性数在 n_expressing（按样本拆分，求和即总数）
        g1_rows = [b for b in est.get('by_sample', []) if b.get('gene') == 'G1']
        want_g1 = np.asarray(truth.X[:, 0].todense()).flatten()
        nz = int((want_g1 > 0).sum())
        check('by_sample 有 G1 行', len(g1_rows) > 0, f'{len(g1_rows)} 行')
        check('G1 表达细胞数对得上真值',
              sum(b['n_expressing'] for b in g1_rows) == nz,
              f'表 {sum(b["n_expressing"] for b in g1_rows)} vs 真值 {nz}')
        check('三个基因都出现在 by_sample',
              {b.get('gene') for b in est.get('by_sample', [])} == {'G1', 'G2', 'G3'},
              f'{sorted({b.get("gene") for b in est.get("by_sample", [])})}')

        print('\n[端到端：_get_raw_expression 多基因]')
        with CountingToMemory(backed) as raw:
            csv = _get_raw_expression(str(path), 'G1,G2,G3', '')
        check('返回非空 CSV', isinstance(csv, str) and len(csv) > 0, f'{len(csv)} 字符')
        check('3 基因 to_memory 1 次', raw.calls == 1, f'实际 {raw.calls}')
        header = csv.splitlines()[0]
        check('表头含三个基因', all(g in header for g in ('G1', 'G2', 'G3')), header)

        # 新鲜度：清掉 adata 缓存，确认从零冷读也一样
        print('\n[冷缓存：清空 adata 缓存后仍是 1 次]')
        from core import adata_cache
        with adata_cache._cache_lock:
            adata_cache._cache.clear()
        with CountingToMemory(backed) as cold:
            extract_gene_columns(anndata.read_h5ad(path, backed='r').X, [0, 1, 2, 4, 5])
        check('冷句柄 K=5 → to_memory 1 次', cold.calls == 1, f'实际 {cold.calls}')

    except Exception:
        FAIL.append('unexpected exception')
        traceback.print_exc()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL gene-column extraction CHECKS PASSED')


if __name__ == '__main__':
    run()
