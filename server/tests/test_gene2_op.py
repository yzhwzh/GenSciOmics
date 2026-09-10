#!/usr/bin/env python3
"""gene2_op（或 / 且）语义回归测试。

Merge 模式把一组基因合成一个布尔新基因 M：
  'or'  = 成员**任一**表达（并集）——历史行为，缺省值
  'and' = 所有成员**都**表达（交集）
该开关同时作用于 stats._get_aggregate_table（表格）与
plots._generate_celltype_composition（堆叠柱状图）。未解析的成员名必须原样回传
（stats）或在响应里报告（plots），供前端提示，不得静默丢弃。

运行：python3 server/tests/test_gene2_op.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。

合成数据（8 细胞 × 4 基因）：
  COL1A1  A = {c0,c1,c2,c3}        COL1A2  B = {c2,c3,c4}
  FAP     G = {c0,c2,c4,c6}        ACTB      全 0
  CellType: c0-c3 = 'T'，c4-c7 = 'B'
推导： |A∪B| = 5/8 = 62.5%        |A∩B| = 2/8 = 25.0%
      |G∪(A∪B)| = 6/8 = 75.0%     |G∩(A∪B)| = 3/8 = 37.5%
      |G∪(A∩B)| = 5/8 = 62.5%     |G∩(A∩B)| = 1/8 = 12.5%
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

from analysis.stats import _get_aggregate_table
from analysis.plots import _generate_celltype_composition

GENES = ['COL1A1', 'COL1A2', 'FAP', 'ACTB']
POSITIVE = {'COL1A1': [0, 1, 2, 3], 'COL1A2': [2, 3, 4], 'FAP': [0, 2, 4, 6], 'ACTB': []}

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def make_fixture(root: Path) -> Path:
    d = root / 'Human' / 'TestOrgan' / 'TestDisease' / 'scRNA'
    d.mkdir(parents=True, exist_ok=True)
    fp = d / '88888888.TestDisease.h5ad'
    n = 8
    X = np.zeros((n, len(GENES)), dtype=np.float32)
    for j, g in enumerate(GENES):
        for c in POSITIVE[g]:
            X[c, j] = 1.0
    obs = pd.DataFrame({
        'CellType': ['T'] * 4 + ['B'] * 4,
        'Group': ['Control'] * 4 + ['Disease'] * 4,
        'Tissue': ['TestOrgan'] * n,
    }, index=[f'c{i}' for i in range(n)])
    var = pd.DataFrame(index=pd.Index(GENES))
    anndata.AnnData(X=X, obs=obs, var=var).write_h5ad(fp)
    return fp


# ── 小工具：跨 celltype 汇总 ────────────────────────────────────

def _num(res: dict, label: str) -> int:
    """label 在所有 celltype 上的阳性细胞数合计。"""
    return sum(r['GeneExpressionNumber'] for r in res['rows'] if r['Gene'] == label)


def _ct_pct(res: dict, label: str, ct: str):
    """label 在某个 celltype 内的阳性比例（%）。"""
    for r in res['rows']:
        if r['Gene'] == label and r['CellType'] == ct:
            return r['GeneExpressionPct']
    return None


def _mean(res: dict, label: str):
    """label 的 GeneMeanExpression（布尔合成基因应为 None）。"""
    vals = [r['GeneMeanExpression'] for r in res['rows'] if r['Gene'] == label]
    return vals[0] if vals else 'MISSING'


def _agg(path: Path, gene2: str, op: str = '', label: str = '', group_col: str = ''):
    return _get_aggregate_table(str(path), 'FAP', group_col, 'CellType', gene2, label, op)


# ── 测试 ────────────────────────────────────────────────────────

def test_normalize_op(path: Path) -> None:
    """归一化集中在 analysis.utils（routes/stats/plots 三处共用）。"""
    import analysis.utils as u
    fn = getattr(u, 'normalize_gene2_op', None)
    check(fn is not None, 'analysis.utils.normalize_gene2_op 存在')
    if fn is None:
        return
    check(fn('AND') == 'and', "normalize_gene2_op('AND') == 'and'")
    check(fn('  and  ') == 'and', "normalize_gene2_op('  and  ') == 'and'")
    check(fn('or') == 'or', "normalize_gene2_op('or') == 'or'")
    check(fn('') == 'or', "normalize_gene2_op('') 缺省回落 'or'")
    check(fn(None) == 'or', "normalize_gene2_op(None) 缺省回落 'or'")
    check(fn('bogus') == 'or', "normalize_gene2_op('bogus') 未知值回落 'or'")


def test_default_is_or(path: Path) -> None:
    """不传 op = 历史 OR 行为（退回旧 URL 必须逐字节等价的语义保证）。"""
    res = _agg(path, 'COL1A1|COL1A2')
    check('error' not in res, f"无 error (得到 {res.get('error')})")
    check(_num(res, 'COL1A1|COL1A2') == 5, f"缺省 M = |A∪B| = 5 (得到 {_num(res, 'COL1A1|COL1A2')})")
    check(_mean(res, 'COL1A1|COL1A2') is None, 'M 是布尔合成基因 (GeneMeanExpression is None)')
    check(_ct_pct(res, 'COL1A1|COL1A2', 'T') == 100.0,
          f"M 在 CellType=T 内 4/4 = 100.0 (得到 {_ct_pct(res, 'COL1A1|COL1A2', 'T')})")
    check(_num(res, 'FAP') == 4, f"主基因 FAP = 4 (得到 {_num(res, 'FAP')})")


def test_and_is_intersection(path: Path) -> None:
    """op='and' → M = 成员交集。"""
    res = _agg(path, 'COL1A1|COL1A2', 'and')
    check('error' not in res, f"无 error (得到 {res.get('error')})")
    check(_num(res, 'COL1A1&COL1A2') == 2,
          f"M = |A∩B| = 2 (得到 {_num(res, 'COL1A1&COL1A2')})")
    check(_num(res, 'COL1A1|COL1A2') == 0, 'AND 下不得再产生并集标签的行')
    check(_mean(res, 'COL1A1&COL1A2') is None, 'AND 的 M 同样是布尔合成基因')
    check(_ct_pct(res, 'COL1A1&COL1A2', 'T') == 50.0,
          f"M 在 CellType=T 内 2/4 = 50.0 (得到 {_ct_pct(res, 'COL1A1&COL1A2', 'T')})")


def test_combo_rows_keep_own_operator(path: Path) -> None:
    """'{g1} | M' / '{g1} & M' 的算符是行自己的，不随开关变 —— 但操作数 M 会变。"""
    or_res = _agg(path, 'COL1A1|COL1A2', 'or')
    and_res = _agg(path, 'COL1A1|COL1A2', 'and')
    check(_num(or_res, 'FAP | COL1A1|COL1A2') == 6,
          f"or: |G∪(A∪B)| = 6 (得到 {_num(or_res, 'FAP | COL1A1|COL1A2')})")
    check(_num(and_res, 'FAP | COL1A1&COL1A2') == 5,
          f"and: |G∪(A∩B)| = 5 (得到 {_num(and_res, 'FAP | COL1A1&COL1A2')})")
    check(_num(or_res, 'FAP & COL1A1|COL1A2') == 3,
          f"or: |G∩(A∪B)| = 3 (得到 {_num(or_res, 'FAP & COL1A1|COL1A2')})")
    check(_num(and_res, 'FAP & COL1A1&COL1A2') == 1,
          f"and: |G∩(A∩B)| = 1 (得到 {_num(and_res, 'FAP & COL1A1&COL1A2')})")
    check(_mean(or_res, 'FAP | COL1A1|COL1A2') is None, '组合行 | 无 mean')
    check(_mean(and_res, 'FAP & COL1A1&COL1A2') is None, '组合行 & 无 mean')


def test_fallback_label_separator(path: Path) -> None:
    """无自定义别名时，兜底标签的分隔符必须反映真实算符（避免把交集标成并集）。"""
    or_res = _agg(path, 'COL1A1|COL1A2', 'or')
    and_res = _agg(path, 'COL1A1|COL1A2', 'and')
    check(_num(or_res, 'COL1A1|COL1A2') == 5, "or 兜底标签用 '|'")
    check(_num(and_res, 'COL1A1&COL1A2') == 2, "and 兜底标签用 '&'")
    check(_num(and_res, 'COL1A1|COL1A2') == 0, "and 下 '|' 标签不得出现")
    check(_num(or_res, 'COL1A1&COL1A2') == 0, "or 下 '&' 标签不得出现（组合行除外）")


def test_custom_label_wins(path: Path) -> None:
    """用户自定义别名对两种 op 都生效，且覆盖兜底标签。"""
    for op in ('or', 'and'):
        res = _agg(path, 'COL1A1|COL1A2', op, 'M2')
        check(_num(res, 'M2') > 0, f"{op}: 自定义别名 M2 出现在表中")
        check(_num(res, f'COL1A1{"|" if op == "or" else "&"}COL1A2') == 0,
              f'{op}: 自定义别名覆盖兜底标签')
    check(_num(_agg(path, 'COL1A1|COL1A2', 'and', 'M2'), 'M2') == 2, "and + 别名 M2 = 2")


def test_unresolved_and_resolved_reported(path: Path) -> None:
    """未解析的成员名必须回传（不得静默丢弃），解析结果同样回传供前端计数。"""
    res = _agg(path, 'COL1A1|NOPE|COL1A2', 'and')
    check(res.get('gene2_unresolved') == ['NOPE'],
          f"gene2_unresolved == ['NOPE'] (得到 {res.get('gene2_unresolved')!r})")
    check(res.get('gene2_resolved') == ['COL1A1', 'COL1A2'],
          f"gene2_resolved == ['COL1A1','COL1A2'] (得到 {res.get('gene2_resolved')!r})")
    check(_num(res, 'COL1A1&COL1A2') == 2, '缺一个成员仍按剩余成员取交集')
    ok = _agg(path, 'COL1A1|COL1A2', 'or')
    check(ok.get('gene2_unresolved') == [], f"全部解析时为空列表 (得到 {ok.get('gene2_unresolved')!r})")
    check(ok.get('gene2_resolved') == ['COL1A1', 'COL1A2'], '全部解析时 gene2_resolved 列出全部成员')


def test_degenerate_single_member(path: Path) -> None:
    """只剩 1 个成员时 is_merge=False，落到**真实基因**路径 —— M 不再是布尔值。"""
    res = _agg(path, 'NOPE|COL1A1', 'and')
    check(res.get('gene2_resolved') == ['COL1A1'],
          f"只剩 1 个成员 (得到 {res.get('gene2_resolved')!r})")
    check(res.get('gene2_unresolved') == ['NOPE'],
          f"被丢弃的成员名仍要回传 (得到 {res.get('gene2_unresolved')!r})")
    check(_mean(res, 'COL1A1') is not None,
          '退化后走真实基因路径 → GeneMeanExpression 是连续值（前端应据此提示）')
    check(_num(res, 'COL1A1') == 4, '退化后标签是真实基因名 COL1A1 且表达数正确')


def test_grouped_mode_reports(path: Path) -> None:
    """分组模式走**另一个** return 分支，两个 key 与 fisher 行都必须带上。"""
    res = _agg(path, 'COL1A1|COL1A2', 'and', '', group_col='Group')
    check('error' not in res, f"无 error (得到 {res.get('error')})")
    check(res.get('groups') == ['Disease', 'Control'],
          f"分组顺序 disease 在前 (得到 {res.get('groups')!r})")
    check(res.get('gene2_resolved') == ['COL1A1', 'COL1A2'],
          f"分组分支带 gene2_resolved (得到 {res.get('gene2_resolved')!r})")
    check(res.get('gene2_unresolved') == [],
          f"分组分支带 gene2_unresolved (得到 {res.get('gene2_unresolved')!r})")
    fisher_genes = {r['gene'] for r in (res.get('fisher') or {}).get('rows', [])}
    check('COL1A1&COL1A2' in fisher_genes, f'fisher 含 AND 的 M 标签 (得到 {sorted(fisher_genes)})')
    check('COL1A1|COL1A2' not in fisher_genes, 'fisher 不含并集标签')


def test_composition_plot_op(path: Path) -> None:
    """图那条路径同样支持 op，并报告未解析成员。"""
    res = _generate_celltype_composition(str(path), 'FAP', 'default', 'COL1A1|COL1A2', '', 'and')
    check('error' not in res, f"and 图无 error (得到 {res.get('error')})")
    check(str(res.get('image', '')).startswith('data:image/png'),
          '返回 base64 PNG')
    check(res.get('gene2_resolved') == ['COL1A1', 'COL1A2'],
          f"图路径带 gene2_resolved (得到 {res.get('gene2_resolved')!r})")
    check(res.get('gene2_unresolved') == [], '全部解析时为空列表')

    bad = _generate_celltype_composition(str(path), 'FAP', 'default', 'NOPE|COL1A1', '', 'and')
    check(bad.get('gene2_unresolved') == ['NOPE'],
          f"拼错的成员被回传而不是静默丢弃 (得到 {bad.get('gene2_unresolved')!r})")

    or_res = _generate_celltype_composition(str(path), 'FAP', 'default', 'COL1A1|COL1A2', '')
    check(str(or_res.get('image', '')).startswith('data:image/png'),
          '缺省 op 仍能出图（旧 URL 兼容）')


def test_shared_helpers_are_safe_to_call_directly(path: Path) -> None:
    """reduce_bool_masks / merge_op_separator 自带归一化，不依赖调用方先 normalize。"""
    import numpy as np
    import analysis.utils as u
    bm = getattr(u, 'reduce_bool_masks', None)
    sep = getattr(u, 'merge_op_separator', None)
    check(bm is not None and sep is not None, '两个 helper 都存在')
    if bm is None or sep is None:
        return
    check(bm([], 'and') is None, 'reduce_bool_masks([]) 返回 None（无成员 ≠ 无阳性）')
    check(sep('and') == '&' and sep('or') == '|' and sep(None) == '|',
          "merge_op_separator: and→& , or/None→|")
    a = np.array([True, True, False, False])
    b = np.array([True, False, True, False])
    # 'AND' 未归一化时会被当成未知值 → 若 helper 不自己归一化就会静默取并集
    check(list(bm([a, b], 'AND')) == [True, False, False, False],
          f"裸传 'AND' 也走交集 (得到 {list(bm([a, b], 'AND'))})")
    check(list(bm([a, b], 'or')) == [True, True, True, False], "'or' 走并集")
    # 单元素不能把调用方的数组别名返回出去（本仓库禁用 in-place 修改）
    out = bm([a], 'or')
    out[0] = False
    check(bool(a[0]) is True, '返回的是副本，改它不会污染输入掩码')


def test_primary_gene_unresolvable_still_reports(path: Path) -> None:
    """主基因解析失败时 features 为空、合并块整段跳过 —— 但仍须回传未解析成员。

    否则 rows=[] 的响应会声称"合并成员全都正常"，前端一条警告都不显示。
    """
    from analysis.stats import _get_aggregate_table
    res = _get_aggregate_table(str(path), 'NOSUCHGENE', '', 'CellType', 'COL1A1|NOPE', '', 'and')
    check('error' not in res, f"无 error (得到 {res.get('error')})")
    check(not res['rows'], f"主基因解析失败 → 无数据行 (得到 {len(res['rows'])} 行)")
    check(res.get('gene2_unresolved') == ['NOPE'],
          f"仍要回传未解析成员 ['NOPE'] (得到 {res.get('gene2_unresolved')})")


def test_plots_dedupes_unresolved(path: Path) -> None:
    """图路径的重复拼错成员要去重，否则警告会读成 '未找到 NOPE、NOPE'。"""
    from analysis.plots import _generate_celltype_composition
    res = _generate_celltype_composition(str(path), 'FAP', 'default', 'NOPE|NOPE|COL1A1', '', 'and')
    check('error' not in res, f"无 error (得到 {res.get('error')})")
    check(res.get('gene2_unresolved') == ['NOPE'],
          f"去重后只报一次 (得到 {res.get('gene2_unresolved')})")


def test_known_partial_match_hazard(path: Path) -> None:
    """B28 已知隐患（后端未修，仅钉住现状）：resolve_gene_indices 有子串回退，
    'COL1' 会静默解析成 COL1A1 并被报成"已解析"，警告因此不显示。

    本用例直接调 _get_aggregate_table，**绕过 UI** —— 后端至今仍是这个行为，接口
    直连可以触发。前端侧已在 Merge 成员选择器上关掉 Create 项堵死入口（见
    docs/BUG_LOG.md B28「可达性」），所以这条测试不会因 UI 改动而失效。
    修掉后端时本用例应当失败并被改写，不是被删掉。"""
    res = _agg(path, 'COL1|COL1A2', 'and')
    check(res.get('gene2_unresolved') == [],
          f"现状：子串命中不算未解析 (得到 {res.get('gene2_unresolved')})")
    check(res.get('gene2_resolved') == ['COL1A1', 'COL1A2'],
          f"现状：'COL1' 被静默当作 COL1A1 (得到 {res.get('gene2_resolved')})")


def main() -> int:
    print('gene2_op 回归: 合并新基因的 或/且 规则\n')
    root = Path(tempfile.mkdtemp(prefix='gene2_op_'))
    try:
        path = make_fixture(root)
        tests = (
            test_normalize_op, test_default_is_or, test_and_is_intersection,
            test_combo_rows_keep_own_operator, test_fallback_label_separator,
            test_custom_label_wins, test_unresolved_and_resolved_reported,
            test_degenerate_single_member, test_grouped_mode_reports,
            test_composition_plot_op, test_shared_helpers_are_safe_to_call_directly,
            test_primary_gene_unresolvable_still_reports, test_plots_dedupes_unresolved,
            test_known_partial_match_hazard,
        )
        for t in tests:
            print(f'[{t.__name__}]')
            try:
                t(path)
            except Exception:
                FAIL.append(f'{t.__name__} raised')
                print('  ✗ 异常:\n' + traceback.format_exc())
            print()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL gene2_op CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
