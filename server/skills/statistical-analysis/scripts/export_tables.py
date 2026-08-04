"""Export tables to CSV.
Usage: python3 export_tables.py <data.h5ad> <table_type> [gene]
"""
import sys, os, time, pandas as pd, scanpy as sc
adata = sc.read_h5ad(sys.argv[1])
ttype = sys.argv[2] if len(sys.argv) > 2 else 'cell_counts'
outdir = '/tmp/gensci_results'
os.makedirs(outdir, exist_ok=True)
_TS = str(int(time.time() * 1000))[-8:]
if ttype == 'cell_counts':
    ct = adata.obs.groupby(['CellType', 'Group']).size().unstack(fill_value=0)
    fn = f'cell_counts_{_TS}.csv'
    ct.to_csv(f'{outdir}/{fn}')
    print(ct)
    print(f'[Download CSV](/api/results?file={fn})')
elif ttype == 'expression':
    gene = sys.argv[3] if len(sys.argv) > 3 else 'FAP'
    expr = pd.DataFrame({gene: adata[:, gene].X.toarray().flatten(), 'CellType': adata.obs['CellType'].values, 'Group': adata.obs['Group'].values})
    fn = f'{gene}_expression_{_TS}.csv'
    expr.to_csv(f'{outdir}/{fn}', index=False)
    print(f'Saved {gene}_expression.csv')
    print(f'[Download CSV](/api/results?file={fn})')
