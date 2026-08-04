"""Statistical tests: Mann-Whitney U/t-test/ANOVA.
Usage: python3 statistical_analysis.py <data.h5ad> <gene> <groupby> [test]
"""
import sys, numpy as np, pandas as pd, scanpy as sc
from scipy import stats

adata = sc.read_h5ad(sys.argv[1])
gene, groupby = sys.argv[2], sys.argv[3]
test = sys.argv[4] if len(sys.argv) > 4 else 'mannwhitneyu'
expr = pd.DataFrame({gene: adata[:, gene].X.toarray().flatten(), 'group': adata.obs[groupby].values})
groups = expr['group'].unique()
if len(groups) != 2:
    print(f'Need 2 groups, got {len(groups)}')
    sys.exit(1)
g1, g2 = expr[expr['group'] == groups[0]][gene], expr[expr['group'] == groups[1]][gene]
tests = {'ttest_ind': stats.ttest_ind, 'mannwhitneyu': stats.mannwhitneyu, 'f_oneway': lambda a,b: stats.f_oneway(a,b)}
s, p = tests.get(test, stats.mannwhitneyu)(g1, g2)
print(f'{test}: stat={s:.4f}, p={p:.6e}')
print(f'{groups[0]}: n={len(g1)}, mean={g1.mean():.4f}')
print(f'{groups[1]}: n={len(g2)}, mean={g2.mean():.4f}')
