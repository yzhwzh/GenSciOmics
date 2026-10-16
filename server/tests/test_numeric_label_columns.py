#!/usr/bin/env python3
"""B43 回归测试：标签列不是字符串时，图表不得崩。

现场（2026-10-16，数据集 40425564.STGD.h5ad）：
用户点进数据，柱状图整页报错

    ValueError: Could not interpret value `CellType` for `x`.
                An entry with this name does not appear in `data`.

这句话会把人引到错的方向 —— `CellType` **明明在 obs 里**（第 9 列）。真相是
`data` 那个 DataFrame 是**空的**：`pd.DataFrame([])` 没有列，seaborn 报的是
「这个列不在数据里」，而不是「数据里没有行」。

而它为什么是空的：`plots.py` 的聚合分支拿**原始 obs 值**去比**字符串标签** ——

    condition = str(c_sub[0])               # '150'
    combo = ct_mask & (cond_vals == cond)   # int64 数组 == '150' → 全 False

这份数据的 `Group` 列是 **int64**（40/90/150/200/260，是分化天数，不是 Disease/
Control），于是每一组 mask 全 False、`agg_rows` 全空，最后在 seaborn 里炸开。

**同一份数据在 `stats.py` 里是好的** —— 那里每一处取数都写了 `.astype(str)`
（:59 :163 :328 :571）。也就是说这不是「新缺陷」，是 `plots.py` 漏抄了表格那层
已有的处理。所以修法就是把这层补上，而不是另发明一套。

运行：python3 server/tests/test_numeric_label_columns.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import numpy as np
import pandas as pd
import anndata

import analysis.plots as plots
import analysis.expression as expression

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def write_fixture(path: Path, *, group_dtype, celltype_dtype, n: int = 90) -> None:
    """写一份标签列类型可控的 .h5ad。

    group_dtype / celltype_dtype 传 'str' 或 'int' —— 3 个组、6 个样本、3 个
    细胞类型，保证 boxplot 分支的 `n <= min_cells` 过滤不会把行全滤掉。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    groups = [40, 90, 150]
    cts = [0, 1, 2]
    obs = pd.DataFrame({
        'Sample': [f'S{i}' for i in range(6)] * (n // 6),
        'Group': [groups[i % 3] for i in range(n)],
        'CellType': [cts[i % 3] for i in range(n)],
    }, index=[f'c{i}' for i in range(n)])
    if group_dtype == 'str':
        obs['Group'] = obs['Group'].astype(str)
    if celltype_dtype == 'str':
        obs['CellType'] = obs['CellType'].astype(str)
    rng = np.random.RandomState(0)
    X = np.zeros((n, 3), dtype=np.float32)
    X[:, 0] = rng.rand(n)   # 一列有表达、两列全零
    # X_umap 是 _generate_umap_ratio_plots 的前提（它按 group_var 出比例图）
    obsm = {'X_umap': rng.rand(n, 2).astype(np.float32)}
    anndata.AnnData(X=X, obs=obs, obsm=obsm,
                    var=pd.DataFrame(index=['EGFR', 'CD3D', 'PTPRC'])).write_h5ad(path)


def call_plot(fp: Path, plot_type: str, metric: str = 'expression_pct') -> dict:
    return plots._generate_plot(str(fp), 'EGFR', 'Group', metric, plot_type, 2, 'default')


def _report(label: str, res: dict) -> None:
    """断言成功，失败时把真实错误打出来（不要只说「返回了 error」）。"""
    err = res.get('error')
    check(not err,
          f'{label} 不得报错' + (f'（实际: {err.splitlines()[0][:110]}）' if err else ''))
    check(bool(res.get('image')), f'{label} 必须返回图片基址')


def test_barplot_with_numeric_group(tmp: Path) -> None:
    """用户的现场：Group 是 int64 → 聚合柱状图必须画得出来。"""
    fp = tmp / 'A' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='str')
    _report('int64 Group + 柱状图', call_plot(fp, 'barplot'))


def test_boxplot_with_numeric_group(tmp: Path) -> None:
    """箱线图那条分支也要过 —— 它同样拿原始值比字符串。"""
    fp = tmp / 'B' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='str')
    _report('int64 Group + 箱线图', call_plot(fp, 'boxplot'))


def test_numeric_celltype(tmp: Path) -> None:
    """CellType 是数字（seurat_clusters 这种）时同样不得崩。

    这份 fixture 的 Group 是字符串，所以它只压 CellType 这一侧。
    """
    fp = tmp / 'C' / 'x.h5ad'
    write_fixture(fp, group_dtype='str', celltype_dtype='int')
    _report('int64 CellType + 柱状图', call_plot(fp, 'barplot'))
    _report('int64 CellType + 箱线图', call_plot(fp, 'boxplot'))


def test_numeric_both(tmp: Path) -> None:
    """两侧都是数字（最坏情况）。"""
    fp = tmp / 'D' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='int')
    _report('int64 Group + int64 CellType + 柱状图', call_plot(fp, 'barplot'))


def test_string_labels_still_work(tmp: Path) -> None:
    """对照组：原来能跑的字符串标签不得被这次修复弄坏。"""
    fp = tmp / 'E' / 'x.h5ad'
    write_fixture(fp, group_dtype='str', celltype_dtype='str')
    _report('字符串标签 + 柱状图（对照组）', call_plot(fp, 'barplot'))
    _report('字符串标签 + 箱线图（对照组）', call_plot(fp, 'boxplot'))


# ── 另外几个被改到 / 该类的函数 ──────────────────────────────

def test_marker_dotplot_with_numeric_celltype(tmp: Path) -> None:
    """`_generate_marker_dotplot` —— 数值 CellType 会让 scanpy 自动分箱。

    `sc.pl.dotplot(groupby='CellType')` 对数值列自动分箱，刻度文字变成
    `Interval(0.286, 0.571, closed='right')`；随后按刻度文字回查细胞计数的
    `.loc[...]` 就 KeyError。修法与其它处一致（转字符串），但**只转数值列** ——
    category 列不能被降级成 object，否则 y 轴细胞类型顺序会被字典序重排。

    真实数据集（40425564.STGD）的 CellType 是 category，所以这一条目前是**潜在**
    缺陷而非现场故障；但把 CellType 存成整数编码的数据集很常见。

    显式传 genes='EGFR'：默认 Target 基因表里没有 fixture 的这三个基因。
    """
    fp = tmp / 'I' / 'x.h5ad'
    write_fixture(fp, group_dtype='str', celltype_dtype='int')
    res = plots._generate_marker_dotplot(str(fp), 'default', '', 'EGFR')
    err = res.get('error')
    check(not err, 'marker dotplot 不得报错' + (f'（实际: {err.splitlines()[0][:90]}）' if err else ''))
    check(bool(res.get('image')), 'marker dotplot 必须返回图片基址')
    # 返回给前端下拉框的 groups 也要是数值序（B45）—— 字典序会给 150/40/90
    check(res.get('groups') == ['40', '90', '150'],
          f"groups 应为数值序 ['40','90','150'] (实际 {res.get('groups')})")

    # 反面：category（字符串标签）不得被这次修改改变行为 —— 仍要出图。
    fp2 = tmp / 'L' / 'x.h5ad'
    write_fixture(fp2, group_dtype='str', celltype_dtype='str')
    res2 = plots._generate_marker_dotplot(str(fp2), 'default', '', 'EGFR')
    check(not res2.get('error') and bool(res2.get('image')),
          'marker dotplot 字符串 CellType 仍须出图（防降级 category 的回归）')


def test_cell_ratio_plot_with_numeric_group(tmp: Path) -> None:
    """`_generate_cell_ratio_plot` —— UMAP 页的比例图（自动探测 Group 列）。"""
    fp = tmp / 'J' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='str')
    res = plots._generate_cell_ratio_plot(str(fp), 'Group')
    err = res.get('error')
    check(not err, 'cell ratio plot 不得报错' + (f'（实际: {err}）' if err else ''))
    check(bool(res.get('stacked_bar')), 'cell ratio plot 必须返回 stacked_bar 图')


def test_umap_ratio_plots_with_numeric_group(tmp: Path) -> None:
    """`_generate_umap_ratio_plots` —— group_var 指向 **int64** 列时。

    必须传 int64 的那一列（Group）。原先这条传的是 `'CellType'`（字符串列），
    于是无论修没修都过 —— 一个不会失败的用例。前端
    `src/api/analysis.ts:373` 的默认 `groupVar` 恰好就是 `'Group'`，而本数据集
    的 Group 正是 int64，所以这条对应的是**现场真实路径**：修复前报
    `'int' object has no attribute 'lower'`（分组排序那里拿标签调 `.lower()`）。
    """
    fp = tmp / 'K' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='str')
    res = plots._generate_umap_ratio_plots(str(fp), 'Group')
    err = res.get('error')
    check(not err, 'umap ratio plots 不得报错' + (f'（实际: {err.splitlines()[0][:90]}）' if err else ''))
    check(bool(res.get('stacked_bar')), 'umap ratio plots 必须返回 stacked_bar 图')


# ── 同一缺陷类在 expression.py 里的形态：不报错，只是**空** ──────────────

def test_expression_stats_with_numeric_celltype(tmp: Path) -> None:
    """标签是数字时 expression-stats 不得静默返回空表。

    这条比图表的崩溃更值得测：`all_ct_values == ct` 全 False 不会抛异常，
    它只是让 `by_celltype` / `by_sample_celltype` 变成空列表 —— 前端表格空白，
    没有任何地方说「出错了」。静默的错比报错难查。
    """
    fp = tmp / 'G' / 'x.h5ad'
    write_fixture(fp, group_dtype='str', celltype_dtype='int')
    out = expression._get_expression_stats(fp, 'EGFR', group_by='Sample',
                                           cell_type_filter='', condition_col='Group')
    err = out.get('error')
    check(not err, 'expression-stats 不得报错' + (f'（实际: {err}）' if err else ''))
    check(len(out.get('by_celltype') or []) > 0,
          f"by_celltype 不得为空 (实际 {len(out.get('by_celltype') or [])} 行)")
    check(len(out.get('by_sample_celltype') or []) > 0,
          f"by_sample_celltype 不得为空 (实际 {len(out.get('by_sample_celltype') or [])} 行)")


def test_expression_stats_with_numeric_group_by(tmp: Path) -> None:
    """`group_by` 指向 int64 列时，by_sample 同样不得静默为空。"""
    fp = tmp / 'H' / 'x.h5ad'
    write_fixture(fp, group_dtype='int', celltype_dtype='str')
    out = expression._get_expression_stats(fp, 'EGFR', group_by='Group',
                                           cell_type_filter='', condition_col='')
    check(not out.get('error'), f"不得报错 (实际 {out.get('error')})")
    check(len(out.get('by_sample') or []) > 0,
          f"by_sample 不得为空 (实际 {len(out.get('by_sample') or [])} 行)")
    # 比集合而不是列表：这里要证的是**标签内容**（是 40/90/150 而不是 40.0 或空），
    # 不是顺序。顺序是另一件事 —— 组名按字典序排出来是 ['150','40','90']，
    # 天数被打乱了，那属于 cond_sort_key 的语义问题（见 BUG_LOG B43「遗留」一节）。
    check(set(out.get('samples') or []) == {'40', '90', '150'},
          f"组名应为 40/90/150 (实际 {sorted(out.get('samples') or [])})")


TESTS = (
    test_barplot_with_numeric_group,
    test_boxplot_with_numeric_group,
    test_numeric_celltype,
    test_numeric_both,
    test_string_labels_still_work,
    test_marker_dotplot_with_numeric_celltype,
    test_cell_ratio_plot_with_numeric_group,
    test_umap_ratio_plots_with_numeric_group,
    test_expression_stats_with_numeric_celltype,
    test_expression_stats_with_numeric_group_by,
)


def _unregistered() -> list[str]:
    """本模块里定义了、但没进 TESTS 的 test_* 函数名。

    加这道自检是因为它真发生过：用例写好了却没登记，`npm run test:py` 照样全绿，
    等于没写。静默跳过的测试比没有测试更坏 —— 它让人以为覆盖到了。
    """
    declared = {n for n, v in globals().items()
                if n.startswith('test_') and callable(v)}
    registered = {t.__name__ for t in TESTS}
    return sorted(declared - registered)


def main() -> int:
    print('B43 regression: 标签列不是字符串时图表不得崩\n')

    missing = _unregistered()
    if missing:
        FAIL.append(f'未登记的用例: {missing}')
        print(f'  ✗ 有用例定义了却没进 TESTS: {missing}\n')

    tmp = Path(tempfile.mkdtemp(prefix='b43_numeric_labels_'))
    try:
        for t in TESTS:
            print(f'[{t.__name__}]')
            try:
                t(tmp)
            except Exception:
                FAIL.append(f'{t.__name__} raised')
                print('  ✗ 异常:\n' + traceback.format_exc())
            print()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL B43 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
