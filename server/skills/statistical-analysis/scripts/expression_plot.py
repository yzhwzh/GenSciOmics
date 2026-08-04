"""Gene expression viz: boxplot/barplot. Uses scanpy + matplotlib.
Usage: python3 expression_plot.py <data.h5ad> <gene> <plot_type> [metric] [condition_col] [palette] [min_cells]
"""
import sys, numpy as np, pandas as pd, matplotlib, scanpy as sc, time as _time
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
_TS = str(int(_time.time()))[-6:]  # unique suffix per run

adata = sc.read_h5ad(sys.argv[1])
gene = sys.argv[2]
plot_type = sys.argv[3] if len(sys.argv) > 3 else 'boxplot'
condition_col = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != 'None' else None
min_cells = int(sys.argv[5]) if len(sys.argv) > 5 else 10
outdir = '/tmp/gensci_results'
import os; os.makedirs(outdir, exist_ok=True)

expr = pd.DataFrame({gene: adata[:, gene].X.toarray().flatten(), 'CellType': adata.obs['CellType'].values})
if condition_col:
    expr['Condition'] = adata.obs[condition_col].values

fig, ax = plt.subplots(figsize=(12, 4))
if plot_type == 'boxplot':
    sns.boxplot(data=expr, x='CellType', y=gene, hue=condition_col if condition_col else None, ax=ax)
else:
    agg = expr.groupby(['CellType'] + ([condition_col] if condition_col else []))[gene].mean().reset_index()
    sns.barplot(data=agg, x='CellType', y=gene, hue=condition_col if condition_col else None, ax=ax)
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
fn = f'{gene}_{plot_type}_{_TS}.png'
plt.savefig(f'{outdir}/{fn}', dpi=200, bbox_inches='tight')
plt.close()
print(f'![{gene} {plot_type}](/api/results?file={fn})')
print(f'Done: {fn}')
