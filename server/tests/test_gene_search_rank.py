#!/usr/bin/env python3
"""基因搜索排序回归测试。

/api/search-genes 把子串命中截断到前 100 条。子串命中按字母序排列时，
**一个真实基因可能被挤出它自己的搜索结果**：在 Lung IPF（33,694 基因）里，
"F2" 和 "T" 各有 >100 个基因名包含它们，按字母序都排在 100 名开外。

后果不是"搜不到"这么轻：前端基因框只接受与候选完全相等的名字（geneInput.ts，
BUG_LOG B28），候选里没有 F2 → 用户无法选择 F2。修复前则是静默解析成别的基因。
两个方向都不能接受，所以精确命中必须排在截断之前。

运行：python3 server/tests/test_gene_search_rank.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

_failures = 0


def check(label: str, got, want) -> None:
    global _failures
    if got == want:
        print(f'  ok   {label}')
    else:
        _failures += 1
        print(f'  FAIL {label}\n       got  {got!r}\n       want {want!r}')


print('rank_gene_matches')

from search import rank_gene_matches  # noqa: E402

# The real-world shape: a short gene name that is a substring of many others.
MANY_F2 = ['F2RL1', 'F2RL2', 'F2R', 'F2RL3'] + [f'XXF2{i:03d}' for i in range(120)] + ['F2']

check('a real gene survives its own [:100] cap',
      'F2' in rank_gene_matches(MANY_F2, 'f2', limit=100), True)
check('the exact match is returned first',
      rank_gene_matches(MANY_F2, 'f2', limit=100)[0], 'F2')
check('the cap is still applied',
      len(rank_gene_matches(MANY_F2, 'f2', limit=100)), 100)
check('the cap is still applied below the limit',
      len(rank_gene_matches(['AA', 'AB', 'BB'], 'b')), 2)

# Substring search is the point of the box — typing "col1" must still list COL1A1.
check('substring matches are still returned',
      rank_gene_matches(['COL1A1', 'COL1A2', 'ACTB'], 'col1'),
      ['COL1A1', 'COL1A2'])
check('matching ignores case on both sides',
      rank_gene_matches(['COL1A1'], 'CoL1a1'), ['COL1A1'])
check('a miss returns nothing rather than everything',
      rank_gene_matches(['COL1A1', 'ACTB'], 'zzz'), [])

# Ordering among non-exact hits stays alphabetical, so the list does not shuffle
# between keystrokes.
check('non-exact hits stay alphabetical',
      rank_gene_matches(['EGF', 'EGFR', 'EGR1'], 'eg'),
      ['EGF', 'EGFR', 'EGR1'])

# An exact hit that is also a prefix must not be duplicated.
check('no duplicate when the exact hit would also match as a substring',
      rank_gene_matches(['EGF', 'EGFR'], 'egf'), ['EGF', 'EGFR'])

print()
if _failures:
    print(f'{_failures} check(s) failed')
    sys.exit(1)
print('all checks passed')
