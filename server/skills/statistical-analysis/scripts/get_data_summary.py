"""Dataset summary: cells, genes, cell types, samples, groups.
Usage: python3 get_data_summary.py <data.h5ad>
"""
import sys, scanpy as sc
adata = sc.read_h5ad(sys.argv[1])
ct = adata.obs['CellType'].unique().tolist() if 'CellType' in adata.obs else []
sm = adata.obs['Sample'].unique().tolist() if 'Sample' in adata.obs else []
gr = adata.obs['Group'].unique().tolist() if 'Group' in adata.obs else []
print(f'Cells: {adata.n_obs:,}')
print(f'Genes: {adata.n_vars:,}')
print(f'Cell types: {len(ct)}')
print(f'Samples: {len(sm)}')
print(f'Groups: {gr}')
