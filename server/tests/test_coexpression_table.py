#!/usr/bin/env python3
"""4+ 基因共表达：排除全不表达的细胞，并把组合计数打印成 Markdown 表格 —— 回归测试。

背景（用户报的现象）：`find_related_genes.py` 的 4+ 分支只产出一张 UpSet PNG，
没有任何数字输出。而 `from_memberships` 收到的是**每一个**细胞，包括一个基因都
不表达的细胞。实测（4 基因 / 200 细胞，稀疏率 25%）：

    (False, False, False, False) -> 63      <- 全场最高，且排在最左

`sort_by='cardinality'` 是升序，全 False 的基数最小，所以最强的一根柱子
（"什么都不表达"，63/200）留在最左，把真正关心的组合压到 y 轴底部。

用户原话：「四个基因及以上的，不需要展现都不表达的数据，只需要看这四个基因相关的，
另能不能把这些数值整理成表格」。所以本测试钉住两件事：
  (a) 4+ 分支先把全不表达的细胞剔出分析，再把剩下的喂给 UpSet 与表格
  (b) 2/3/4+ 三个分支都打印 Markdown 表格，数值口径为**重叠**

(b) 里最重要的是**重叠 ≠ 互斥**。位编码 + `value_counts()` 得到的是互斥分区
（"只表达 A 且不表达 B/C/D"），与重叠（"表达 A 和 B，不管 C/D"）不是一回事。
同一份数据实测：互斥给 `('A',) = 306`，重叠给 `('A',) = 583`。混用会产出
"同名不同义"的数字。本仓库现有 3 基因分支的 `(detected[g1] & detected[g2]).sum()`
本来就是重叠，2 基因的 venn2 交集区也是 —— 所以口径定为重叠，2/3 分支的数字
**一个都不该变**。

顺带钉住的两个既存缺陷（都在 4+ 分支，今天都会让图/表消失）：
  - `print(f'![UpSet](//api/results?...")')` 是**协议相对 URL**，浏览器会去请求
    主机名 `api`；且 `ChatPanel.tsx` 的 markdown components 覆盖了 table/th/td/h3/strong
    但**没有 img**，坏 URL 不会兜底 —— 这张图从来没显示成功过。
  - `except ImportError` 兜不住 `from_memberships([])` 的 `ValueError`
    （过滤后剩 0 个细胞时会触发），也兜不住末尾 `100*n/len(expr)` 的 `ZeroDivisionError`。

运行：python3 server/tests/test_coexpression_table.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。

合成数据全部用 var.index 里**已存在**的名字，避免触发 `_resolve_via_mygene` 的网络请求。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import sys
import shutil
import tempfile
import traceback
from pathlib import Path

# 必须在 import anndata 之前设置，否则并发读会挂
os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'
os.environ.setdefault('MPLBACKEND', 'Agg')

SERVER_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SERVER_DIR / 'skills' / 'statistical-analysis' / 'scripts' / 'find_related_genes.py'

import numpy as np
import pandas as pd
import anndata
import scipy.sparse as sp

GENES4 = ['GENE1', 'GENE2', 'GENE3', 'GENE4']

# 逐个细胞手写成员关系，好让期望值可以手算。n_all = 13。
#
#   idx  membership                    对 GENE1+GENE2 的贡献
#    0   ()                            不含（全不表达）
#    1   ()                            不含（全不表达）
#    2-4 ('GENE1',)                    不含
#    5   ('GENE2',)                    不含
#    6   ('GENE3',)                    不含
#    7   ('GENE4',)                    不含
#    8   ('GENE1','GENE2')             **含**
#    9   ('GENE1','GENE2')             **含**
#   10   ('GENE1','GENE3')             不含
#   11   ('GENE2','GENE3','GENE4')     不含（差 GENE1）
#   12   ('GENE1','GENE2','GENE3')     **含**
#
# → GENE1+GENE2 重叠计数 = 3（idx 8,9,12）
#   而互斥计数（同时表达 G1,G2 且**不**表达 G3,G4）= 2（idx 8,9）—— 差 1，可区分两种口径。
#   idx 12 表达三个基因，正是"重叠把多重共表达也计入"的判别样本。
MEMBERSHIPS = [
    (),
    (),
    ('GENE1',),
    ('GENE1',),
    ('GENE1',),
    ('GENE2',),
    ('GENE3',),
    ('GENE4',),
    ('GENE1', 'GENE2'),
    ('GENE1', 'GENE2'),
    ('GENE1', 'GENE3'),
    ('GENE2', 'GENE3', 'GENE4'),
    ('GENE1', 'GENE2', 'GENE3'),
]

# 期望的重叠计数（只列 >=2 基因的组合，按细胞数降序）。
# 计数为 0 的组合**不该**出现在表里：
#   GENE1+GENE4、GENE1+GENE2+GENE4、GENE1+GENE3+GENE4、GENE1+GENE2+GENE3+GENE4
EXPECTED_PAIRS = [
    (('GENE1', 'GENE2'), 3),
    (('GENE1', 'GENE3'), 2),
    (('GENE2', 'GENE3'), 2),
    (('GENE2', 'GENE4'), 1),
    (('GENE3', 'GENE4'), 1),
    (('GENE1', 'GENE2', 'GENE3'), 1),
    (('GENE2', 'GENE3', 'GENE4'), 1),
]

N_ALL, N_KEPT = 13, 11

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        PASS.append(label)
        print(f'  ✓ {label}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(label)
        print(f'  ✗ {label}  {detail}')


# ─────────────────────────── 合成数据 ───────────────────────────

def make_h5ad(path: Path, memberships, genes) -> Path:
    """按成员关系表造一个稀疏表达矩阵：表达的基因置 5.0，其余 0.0。"""
    mat = np.zeros((len(memberships), len(genes)), dtype=np.float32)
    for i, mem in enumerate(memberships):
        for g in mem:
            mat[i, genes.index(g)] = 5.0
    obs = pd.DataFrame({'Sample': [f'S{i}' for i in range(len(memberships))]},
                       index=[f'cell{i}' for i in range(len(memberships))])
    adata = anndata.AnnData(X=sp.csr_matrix(mat), obs=obs, var=pd.DataFrame(index=genes))
    adata.write_h5ad(path)
    return path


def all_subsets_memberships(genes) -> list:
    """2^G - 1 个非空子集各一个细胞 —— 用来撑爆表格行数上限。"""
    from itertools import combinations
    out = []
    for r in range(1, len(genes) + 1):
        for c in combinations(genes, r):
            out.append(c)
    return out


# ─────────────────────────── 跑脚本 ───────────────────────────

def run_script(h5ad, genes, outdir) -> str:
    """以脚本方式跑 find_related_genes.py，返回它打印到 stdout 的全部内容。

    每次重新 exec 模块，避免 _TS / 模块级状态在多次调用间串味。
    """
    spec = importlib.util.spec_from_file_location('_frg_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = sys.argv
    sys.argv = [str(SCRIPT), str(h5ad), ','.join(genes), str(outdir)]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    finally:
        sys.argv = saved
    return buf.getvalue()


def table_rows(out: str) -> list:
    """取出 Markdown 表格的数据行（跳过表头行与 |---|---| 分隔行）。"""
    rows = []
    for line in out.splitlines():
        s = line.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if not cells or set(''.join(cells)) <= set('-: '):
            continue                      # 分隔行
        if cells[0].lower().startswith('combination'):
            continue                      # 表头
        rows.append(s)
    return rows


def row_count(out: str) -> int:
    return len(table_rows(out))


def cell_value(out: str, combo: str):
    """取某个组合行的 Cells 列；该组合不在表里则返回 None。"""
    for line in table_rows(out):
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells[0] == combo:
            return int(cells[1])
    return None


# ─────────────────────────── 用例 ───────────────────────────

def run() -> None:
    tmpdir = tempfile.mkdtemp(prefix='gensci_coexpr_')
    try:
        base = make_h5ad(Path(tmpdir) / 'base.h5ad', MEMBERSHIPS, GENES4)

        # ── 前置：确认脚本确实以"脚本"方式可跑，且基因名无需联网解析 ──
        print('\n[前置]')
        check('脚本文件存在', SCRIPT.is_file(), str(SCRIPT))
        out4 = run_script(base, GENES4, tmpdir)
        check('未触发 mygene 别名解析（否则会联网）',
              'mygene.info' not in out4, out4[:160].replace('\n', ' ⏎ '))

        # ── (a) 全不表达的细胞被剔出分析 ──
        print('\n[(a) 全不表达的细胞被排除]')
        m = re.search(r'(\d+)\s*/\s*(\d+)', out4)
        check('打印了"表达 >=1 个基因"的细胞数说明行',
              m is not None and 'excluded' in out4, out4[:200].replace('\n', ' ⏎ '))
        if m:
            check(f'kept = {N_KEPT}（{N_ALL} 个细胞里 2 个全不表达）',
                  int(m.group(1)) == N_KEPT, f'得到 {m.group(1)}')
            check(f'all = {N_ALL}', int(m.group(2)) == N_ALL, f'得到 {m.group(2)}')
        check('说明行写明排除了 2 个',
              re.search(r'excluded\s+2\b', out4) is not None,
              [l for l in out4.splitlines() if 'excluded' in l][:1])

        # 分母必须是 n_kept：GENE1 出现在 idx 2,3,4,8,9,10,12 = 7 个细胞
        check(f'每基因表达率的分母是 {N_KEPT} 而不是 {N_ALL}',
              re.search(r'GENE1:\s*7\s*/\s*11\b', out4) is not None,
              [l for l in out4.splitlines() if l.strip().startswith('GENE1:')][:1])
        check('表头标明分母是"表达细胞"而非全部细胞',
              '% of expressing cells' in out4,
              [l for l in out4.splitlines() if l.strip().startswith('| Combination')][:1])

        # ── (b) 表格：重叠口径、只留实际出现的组合 ──
        print('\n[(b) 组合计数表格 —— 重叠口径]')
        check('4+ 分支打印了 Markdown 表格', row_count(out4) > 0,
              f'数据行 {row_count(out4)}')
        check('只列 >=2 基因的组合（单基因计数已在表达率行给出）',
              cell_value(out4, 'GENE1') is None, f'得到 {cell_value(out4, "GENE1")}')

        # 判别性断言：重叠 = 3，互斥 = 2。钉住重叠语义。
        check('GENE1 + GENE2 的重叠计数 = 3（互斥口径会给 2）',
              cell_value(out4, 'GENE1 + GENE2') == 3,
              f'得到 {cell_value(out4, "GENE1 + GENE2")}')
        check(f'表里恰好 {len(EXPECTED_PAIRS)} 种组合（其余 4 种该基因组合为 0）',
              row_count(out4) == len(EXPECTED_PAIRS),
              f'得到 {row_count(out4)}，期望 {len(EXPECTED_PAIRS)}')

        for combo, n in EXPECTED_PAIRS:
            got = cell_value(out4, ' + '.join(combo))
            check(f'{" + ".join(combo)} = {n}', got == n, f'得到 {got}')

        print('\n[计数为 0 的组合不出现]')
        for absent in ['GENE1 + GENE4', 'GENE1 + GENE2 + GENE4',
                       'GENE1 + GENE3 + GENE4', 'GENE1 + GENE2 + GENE3 + GENE4']:
            check(f'{absent} 不在表里（实际计数 0）',
                  cell_value(out4, absent) is None,
                  f'得到 {cell_value(out4, absent)}')

        print('\n[表格按细胞数降序]')
        nums = [int(l.strip('|').split('|')[1].strip()) for l in table_rows(out4)]
        check('行按 Cells 降序', nums == sorted(nums, reverse=True), f'得到 {nums}')

        # ── 图片标签 ──
        print('\n[UpSet 图片标签]')
        check('图片标签是单斜杠 /api/results',
              '](/api/results?file=upset_' in out4,
              [l for l in out4.splitlines() if 'api/results' in l][:1])
        check('不再有协议相对 URL //api/results（那会去请求主机名 api）',
              '//api/results' not in out4,
              [l for l in out4.splitlines() if '//api/results' in l][:1])

        # ── 输出预算 ──
        print('\n[输出预算（ShellTool 只保留最后 5000 字符，且无截断标记）]')
        check('4 基因输出 < 5000 字符', len(out4) < 5000, f'得到 {len(out4)}')

        # ── 2/3 基因分支也出表格，且数字口径不变 ──
        print('\n[2/3 基因分支：同样出表格]')
        out2 = run_script(base, GENES4[:2], tmpdir)
        check('2 基因打印表格', row_count(out2) > 0, f'数据行 {row_count(out2)}')
        check('2 基因 GENE1 + GENE2 = 3', cell_value(out2, 'GENE1 + GENE2') == 3,
              f'得到 {cell_value(out2, "GENE1 + GENE2")}')
        check('2 基因不排除细胞（不出现 excluded 说明行）',
              'excluded' not in out2, [l for l in out2.splitlines() if 'excluded' in l][:1])

        out3 = run_script(base, GENES4[:3], tmpdir)
        check('3 基因打印表格', row_count(out3) > 0, f'数据行 {row_count(out3)}')
        # 这几个数必须与改动前逐字一致：原实现是 (detected[g1] & detected[g2]).sum()
        for combo, n in [(('GENE1', 'GENE2'), 3), (('GENE1', 'GENE3'), 2),
                         (('GENE2', 'GENE3'), 2),
                         (('GENE1', 'GENE2', 'GENE3'), 1)]:
            got = cell_value(out3, ' + '.join(combo))
            check(f'3 基因 {" + ".join(combo)} = {n}（与改动前一致）', got == n, f'得到 {got}')

        # ── 边界：今天会崩的几种输入 ──
        print('\n[边界 1：所有细胞都全不表达]')
        none_all = make_h5ad(Path(tmpdir) / 'none.h5ad', [(), (), (), ()], GENES4)
        out_none = run_script(none_all, GENES4, tmpdir)
        check('不抛异常', True)
        check('给出可读提示而不是空表',
              'express' in out_none.lower() and 'none' in out_none.lower(),
              out_none.strip().replace('\n', ' ⏎ ')[:160])
        check('没有产出空表格', row_count(out_none) == 0, f'数据行 {row_count(out_none)}')
        check('没有除零崩溃（仍打印表达率 0/N）',
              re.search(r'GENE1:\s*0\s*/', out_none) is not None,
              [l for l in out_none.splitlines() if l.strip().startswith('GENE1:')][:1])

        print('\n[边界 2：过滤后只剩一个基因出现]')
        one_gene = make_h5ad(Path(tmpdir) / 'one.h5ad',
                             [('GENE1',), ('GENE1',), ('GENE1',), (), ()], GENES4)
        out_one = run_script(one_gene, GENES4, tmpdir)
        check('不抛异常（from_memberships 在单类别时会 ValueError）', True)
        check('明确说明没有 >=2 基因的共表达',
              'no cell' in out_one.lower() or row_count(out_one) == 0,
              out_one.strip().replace('\n', ' ⏎ ')[:160])

        print('\n[边界 3：只有 3 个细胞表达任一基因]')
        tiny = make_h5ad(Path(tmpdir) / 'tiny.h5ad',
                         [('GENE1',), ('GENE1', 'GENE2'), ()], GENES4)
        out_tiny = run_script(tiny, GENES4, tmpdir)
        check('不抛异常', True)
        check('GENE1 + GENE2 = 1', cell_value(out_tiny, 'GENE1 + GENE2') == 1,
              f'得到 {cell_value(out_tiny, "GENE1 + GENE2")}')

        print('\n[边界 4：某个基因全不表达]')
        no_g4 = make_h5ad(Path(tmpdir) / 'nog4.h5ad',
                          [('GENE1',), ('GENE1', 'GENE2'), ('GENE3',)], GENES4)
        out_g4 = run_script(no_g4, GENES4, tmpdir)
        check('不抛异常', True)
        check('GENE4 不出现在任何组合行里',
              all('GENE4' not in r for r in table_rows(out_g4)),
              [r for r in table_rows(out_g4) if 'GENE4' in r][:1])
        check('GENE4 表达率为 0', re.search(r'GENE4:\s*0\s*/', out_g4) is not None,
              [l for l in out_g4.splitlines() if l.strip().startswith('GENE4:')][:1])

        # ── 边界：行数上限 ──
        print('\n[边界 5：组合数超过行数上限]')
        genes6 = [f'G{i}' for i in range(1, 7)]
        many = make_h5ad(Path(tmpdir) / 'many.h5ad',
                         all_subsets_memberships(genes6), genes6)
        out_many = run_script(many, genes6, tmpdir)
        check('不抛异常', True)
        check('表格行数 <= 50', row_count(out_many) <= 50, f'得到 {row_count(out_many)}')
        # 6 个基因里 >=2 的组合数 = 2^6 - 1 - 6 = 57；截到 50 → 少 7 种
        check('显式说明还有多少种没列出（绝不静默截断）',
              re.search(r'\b7\b', out_many) is not None
              and re.search(r'more|omitted|not shown', out_many, re.I) is not None,
              [l for l in out_many.splitlines()
               if re.search(r'more|omitted|not shown', l, re.I)][:1])
        check('超限时输出仍 < 5000 字符', len(out_many) < 5000, f'得到 {len(out_many)}')

    except Exception:
        FAIL.append('unexpected exception')
        traceback.print_exc()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL co-expression table CHECKS PASSED')


if __name__ == '__main__':
    run()
