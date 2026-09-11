#!/usr/bin/env python3
"""画图的端点必须回传它实际用了哪个基因 —— 回归测试。

背景：未知基因名走**子串回退**解析（`analysis/utils.py:124`，`plots.py` 里还有一份
同样的内联实现，`bulk.py` 的 `_resolve_gene` 同形）。实测 Lung IPF（33,694 基因）：

    CD3  → ABCD3      COL1 → COL16A1      A1 → VWA1

也就是说用户输入一个**本数据集中不存在**的名字，拿回的是一张完全正常、但画的是**别的
基因**的图。图、表、数字都自洽，看的人没有任何办法发现。

本轮不改解析语义（B28 已决定保留子串回退），改的是**把用了哪个基因说出来**：
端点成功返回时带 `gene_resolved`，前端据此在基因框下方出警告行。

本测试钉住三件事：
  (a) 子串命中时回传的是**真正的 var 名**，不是用户输入的 token
  (b) 精确/大小写命中时回传**规范拼写**，且与输入等价（前端据此保持静默）
  (c) bulk 的**两个 return 分支**都带该字段 —— 专抓「只改了一个 return」

(c) 不是凑数：`bulk_boxplot` 的 group 分支是 `return _render_group_boxplot(...)`
直通，只改 `bulk_boxplot` 里那个 return 的话，单疾病数据集（永远走 group 分支）
拿不到字段，而多疾病数据集能拿到 —— 一个只在部分数据集上出现的缺口。

运行：python3 server/tests/test_gene_resolved_echo.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。

合成数据（48 细胞 × 4 基因，稀疏），var.index 含 ABCD3 而**不含** CD3。
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import traceback
import warnings
from pathlib import Path

# 必须在 import anndata 之前设置，否则并发读会挂
os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'
os.environ.setdefault('MPLBACKEND', 'Agg')

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata
import scipy.sparse as sp

from analysis.plots import _generate_plot, _generate_celltype_composition
from analysis.bulk import bulk_boxplot

# ABCD3 存在、CD3 不存在 —— 复刻用户报的那一例。
GENES = ['ABCD3', 'EGFR', 'COL16A1', 'TP53']
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


def build_dataset(tmpdir: str) -> Path:
    rng = np.random.default_rng(20260911)
    mat = rng.integers(0, 6, size=(N_CELLS, len(GENES))).astype(np.float32)
    mat[rng.random(size=mat.shape) < 0.3] = 0.0  # 稀疏化
    obs = pd.DataFrame(
        {
            'Sample': [f'S{i % 4}' for i in range(N_CELLS)],
            'CellType': [['T', 'B', 'M'][i % 3] for i in range(N_CELLS)],
            # 两个 Disease × 两个 Group，保证 panel 模式和 group 模式都有数据
            'Disease': [['D1', 'D2'][(i // 2) % 2] for i in range(N_CELLS)],
            'Group': [['Tumor', 'Normal'][i % 2] for i in range(N_CELLS)],
        },
        index=[f'cell{i}' for i in range(N_CELLS)],
    )
    adata = anndata.AnnData(X=sp.csr_matrix(mat), obs=obs, var=pd.DataFrame(index=GENES))
    path = Path(tmpdir) / 'gene_resolved_echo.h5ad'
    adata.write_h5ad(path)
    return path


def build_alias_dataset(tmpdir: str) -> str:
    """var.index = Ensembl ids, the symbols live in a `gene_symbols` column.

    39 of the 93 datasets in Data/ carry such a column, so the alias branch is
    the normal case there, not an exotic one — and it was the branch with no
    coverage until this fixture existed.
    """
    rng = np.random.default_rng(20260912)
    mat = rng.integers(0, 6, size=(N_CELLS, len(GENES))).astype(np.float32)
    obs = pd.DataFrame(
        {'CellType': [['T', 'B', 'M'][i % 3] for i in range(N_CELLS)]},
        index=[f'cell{i}' for i in range(N_CELLS)],
    )
    # var.index deliberately shares no value with GENES: only the column matches.
    var = pd.DataFrame({'gene_symbols': GENES},
                       index=[f'ENSG{i:09d}' for i in range(1, len(GENES) + 1)])
    adata = anndata.AnnData(X=sp.csr_matrix(mat), obs=obs, var=var)
    path = Path(tmpdir) / 'alias_echo.h5ad'
    adata.write_h5ad(path)
    return str(path)


def run() -> None:
    tmpdir = tempfile.mkdtemp(prefix='gensci_echo_')
    try:
        path = build_dataset(tmpdir)
        p = str(path)

        print('\n[前置：CD3 确实不在本数据集里，而子串回退会命中 ABCD3]')
        check('var 含 ABCD3', 'ABCD3' in GENES)
        check('var 不含 CD3', 'CD3' not in GENES)
        hits = [g for g in GENES if 'cd3' in g.lower()]
        check('子串回退命中 ABCD3 且只有一个', hits == ['ABCD3'], f'命中 {hits}')

        print('\n[_generate_plot — 子串命中时回传真正的 var 名]')
        res = _generate_plot(p, 'CD3', 'Group', 'expression_pct', 'barplot')
        check('CD3 不报错（子串回退照常画图）', 'error' not in res, str(res.get('error', ''))[:120])
        check('回传 gene_resolved == ABCD3', res.get('gene_resolved') == 'ABCD3',
              f"得到 {res.get('gene_resolved')!r}")

        print('\n[_generate_plot — 精确 / 大小写命中回传规范拼写]')
        exact = _generate_plot(p, 'ABCD3', 'Group', 'expression_pct', 'boxplot')
        check('精确命中回传 ABCD3', exact.get('gene_resolved') == 'ABCD3',
              f"得到 {exact.get('gene_resolved')!r}")
        lower = _generate_plot(p, 'abcd3', 'Group', 'expression_pct', 'boxplot')
        check('全小写输入回传规范拼写 ABCD3', lower.get('gene_resolved') == 'ABCD3',
              f"得到 {lower.get('gene_resolved')!r}")

        print('\n[_generate_plot — 完全没命中时仍然报错，不带该字段]')
        miss = _generate_plot(p, 'NOTAGENE', 'Group', 'expression_pct', 'boxplot')
        check('NOTAGENE 报错', 'error' in miss)
        check('报错时不带 gene_resolved', 'gene_resolved' not in miss)

        print('\n[别名列命中 —— var.index 是 Ensembl，基因符号在 gene_symbols 列]')
        alias_path = build_alias_dataset(tmpdir)
        # 行标签是 Ensembl，用户打的符号只在列里。回显「行标签」会给一个用户从没
        # 打过的名字，而前端「resolved ≠ asked 就警告」的规则会把一次完全正确的
        # 命中报成警告 —— 所以这里回显的是**命中的那个值**。
        a = _generate_celltype_composition(alias_path, 'ABCD3')
        check('别名列命中无 error', 'error' not in a, str(a.get('error', ''))[:120])
        check('回显的是命中的符号 ABCD3（不是行标签 ENSG…）',
              a.get('gene_resolved') == 'ABCD3', f"得到 {a.get('gene_resolved')!r}")
        check('回显值不等于行标签（否则前端会误报）',
              a.get('gene_resolved') != 'ENSG000000001', f"得到 {a.get('gene_resolved')!r}")

        # 别名列必须用 .iloc[i] 取，不能写 adata.var[col][i]：Series.__getitem__
        # 收到整数键时按**标签**解释（pandas 2.x 只是弃用告警，3.x 无条件按标签
        # ——对 str 索引就是 KeyError）。两种写法今天返回值相同，所以只能靠这个
        # 告警区分；这是本文件里唯一能钉住该缺陷的信号。
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _generate_celltype_composition(alias_path, 'ABCD3')
        deprecations = [str(w.message) for w in caught
                        if issubclass(w.category, FutureWarning)
                        and '__getitem__' in str(w.message)]
        check('别名列解析不触发 Series.__getitem__ 的位置式取用（即用了 .iloc）',
              not deprecations, f'捕获到 {deprecations[:1]}')

        print('\n[_generate_celltype_composition — 命中时回传]')
        comp = _generate_celltype_composition(p, 'ABCD3')
        check('无 error', 'error' not in comp, str(comp.get('error', ''))[:120])
        check('回传 gene_resolved == ABCD3', comp.get('gene_resolved') == 'ABCD3',
              f"得到 {comp.get('gene_resolved')!r}")
        # 记录本次未统一的差异：composition 是**仅精确**解析，同一个 CD3 在
        # 主图上被换成 ABCD3、在这里直接报错。前端据此**不**让 composition
        # 参与驱动警告行，否则它会把主图刚设好的警告清掉。
        comp_cd3 = _generate_celltype_composition(p, 'CD3')
        check('CD3 在 composition 端仍是 error（exact-only，本次不统一）',
              'error' in comp_cd3, f"得到 {list(comp_cd3)[:3]}")

        print('\n[bulk_boxplot — panel 模式（多疾病，disease=None）]')
        panel = bulk_boxplot(p, 'CD3')
        check('无 error', 'error' not in panel, str(panel.get('error', ''))[:120])
        check('panel 模式回传 ABCD3', panel.get('gene_resolved') == 'ABCD3',
              f"得到 {panel.get('gene_resolved')!r}")

        print('\n[bulk_boxplot — group 模式（指定疾病 → 走 _render_group_boxplot 直通）]')
        group = bulk_boxplot(p, 'CD3', disease='D1')
        check('无 error', 'error' not in group, str(group.get('error', ''))[:120])
        check('group 模式回传 ABCD3（只改一个 return 会漏掉这里）',
              group.get('gene_resolved') == 'ABCD3', f"得到 {group.get('gene_resolved')!r}")

        print('\n[bulk_boxplot — 精确 / 大小写]')
        b_exact = bulk_boxplot(p, 'ABCD3')
        check('精确命中回传 ABCD3', b_exact.get('gene_resolved') == 'ABCD3',
              f"得到 {b_exact.get('gene_resolved')!r}")
        b_lower = bulk_boxplot(p, 'abcd3', disease='D1')
        check('全小写输入回传规范拼写 ABCD3', b_lower.get('gene_resolved') == 'ABCD3',
              f"得到 {b_lower.get('gene_resolved')!r}")

    except Exception:
        FAIL.append('unexpected exception')
        traceback.print_exc()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL gene_resolved echo CHECKS PASSED')


if __name__ == '__main__':
    run()
