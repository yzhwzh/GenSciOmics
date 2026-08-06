#!/usr/bin/env python3
"""Gene expression statistics module."""

import sys
from pathlib import Path

import numpy as np
import anndata
from core.adata_cache import get_adata

from caches import LRUCache


# Cache for expression stats
_expr_cache = LRUCache(max_size=500)


def _get_expression_stats(real_path: Path, genes_str: str,
                          group_by: str = 'Sample', cell_type_filter: str = '',
                          condition_col: str = '') -> dict:
    """Compute per-sample, per-cell-type gene expression stats.

    Returns:
    - by_sample: per-sample raw values with condition labels
    - by_celltype: aggregate per cell type
    - conditions: list of unique condition (Group) values
    """
    genes = [g.strip() for g in genes_str.split(',') if g.strip()]

    cache_key = (str(real_path), real_path.stat().st_mtime, condition_col or '', tuple(sorted(genes)))
    cached = _expr_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        adata = get_adata(str(real_path))

        # Resolve gene indices
        gene_indices = []
        valid_genes = []
        var_names = adata.var_names
        for g in genes:
            mask = [n.lower() == g.lower() for n in var_names]
            if any(mask):
                idx = mask.index(True)
                gene_indices.append(idx)
                valid_genes.append(str(var_names[idx]))
            else:
                partial = [n for n in var_names if g.lower() in n.lower()]
                if partial:
                    idx = list(var_names).index(partial[0])
                    gene_indices.append(idx)
                    valid_genes.append(str(var_names[idx]))
                else:
                    gene_indices.append(-1)
                    valid_genes.append(g)

        # Validate required columns
        if group_by not in adata.obs.columns:
            return {'error': f'Column {group_by} not in obs'}
        # Condition column (for grouping in box plots)
        cond_col = None
        if condition_col and condition_col != 'None' and condition_col in adata.obs.columns:
            cond_col = condition_col

        sample_vals = adata.obs[group_by].values
        cond_vals = adata.obs[cond_col].values if cond_col else None
        unique_samples = sorted(set(str(x) for x in sample_vals))
        unique_conditions = sorted(set(str(x) for x in cond_vals)) if cond_col else ['All']
        all_ct_values = adata.obs['CellType'].values if 'CellType' in adata.obs.columns else None
        unique_ct = sorted(set(str(x) for x in all_ct_values)) if all_ct_values is not None else []

        X = adata.X

        # Per-sample stats (for box plots)
        by_sample: list[dict] = []
        for gi, gn in zip(gene_indices, valid_genes):
            if gi < 0:
                continue
            col = X[:, gi]
            gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()

            for us in unique_samples:
                s_mask = sample_vals == us
                sub_expr = gene_expr[s_mask]
                n_cells = int(s_mask.sum())
                if n_cells == 0:
                    continue
                n_expressing = int((sub_expr > 0).sum())
                # Determine condition for this sample (take the mode)
                condition = 'All'
                if cond_vals is not None:
                    c_sub = cond_vals[s_mask]
                    condition = str(c_sub[0])  # all cells in a sample share the same condition

                by_sample.append({
                    'gene': gn,
                    'sample': us,
                    'condition': condition,
                    'mean_expression': round(float(sub_expr.mean()), 4),
                    'expression_pct': round(float((sub_expr > 0).mean() * 100), 2),
                    'n_cells': n_cells,
                    'n_expressing': n_expressing,
                })

        # Per-cell-type aggregate (for table)
        by_celltype: list[dict] = []
        if all_ct_values is not None:
            for gi, gn in zip(gene_indices, valid_genes):
                if gi < 0:
                    continue
                col = X[:, gi]
                gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
                for ct in unique_ct:
                    ct_mask = all_ct_values == ct
                    sub_expr = gene_expr[ct_mask]
                    n_cells = int(ct_mask.sum())
                    if n_cells == 0:
                        continue
                    n_expressing = int((sub_expr > 0).sum())
                    by_celltype.append({
                        'gene': gn,
                        'cell_type': ct,
                        'mean_expression': round(float(sub_expr.mean()), 4),
                        'expression_pct': round(float((sub_expr > 0).mean() * 100), 2),
                        'n_cells': n_cells,
                        'n_expressing': n_expressing,
                    })

        # Per-sample x per-cell-type stats (for cell-type x-axis box plot)
        by_sample_celltype: list[dict] = []
        if all_ct_values is not None and len(unique_ct) > 0:
            for gi, gn in zip(gene_indices, valid_genes):
                if gi < 0:
                    continue
                col = X[:, gi]
                gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
                for us in unique_samples:
                    s_mask = sample_vals == us
                    condition = str(cond_vals[s_mask][0]) if cond_vals is not None else 'All'
                    for ct in unique_ct:
                        ct_mask = all_ct_values == ct
                        combo = s_mask & ct_mask
                        n_cells = int(combo.sum())
                        if n_cells < 2:
                            continue
                        sub_expr = gene_expr[combo]
                        by_sample_celltype.append({
                            'gene': gn,
                            'sample': us,
                            'cell_type': ct,
                            'condition': condition,
                            'mean_expression': round(float(sub_expr.mean()), 4),
                            'expression_pct': round(float((sub_expr > 0).mean() * 100), 2),
                            'n_cells': n_cells,
                            'n_expressing': int((sub_expr > 0).sum()),
                        })
        output = {
            'genes': valid_genes,
            'conditions': unique_conditions,
            'samples': unique_samples,
            'cell_types': unique_ct,
            'by_sample': by_sample,
            'by_celltype': by_celltype,
            'by_sample_celltype': by_sample_celltype,
        }
        _expr_cache.set(cache_key, output)
        return output
    except Exception as e:
        print(f'[GenSci] Expression stats error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e)}
