"""Find marker genes per cell type via scanpy.
Usage: python3 find_marker_genes.py <data.h5ad> [groupby] [method] [n_genes]
"""
import sys, scanpy as sc
adata = sc.read_h5ad(sys.argv[1])
groupby = sys.argv[2] if len(sys.argv) > 2 else 'CellType'
method = sys.argv[3] if len(sys.argv) > 3 else 'wilcoxon'
n_genes = int(sys.argv[4]) if len(sys.argv) > 4 else 10
sc.tl.rank_genes_groups(adata, groupby, method=method, n_genes=n_genes)
for g in adata.obs[groupby].cat.categories[:10]:
    genes = [adata.uns['rank_genes_groups']['names'][g][i] for i in range(min(5, n_genes))]
    print(f'{g}: {", ".join(genes)}')
