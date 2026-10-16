#!/usr/bin/env python3
"""Gene expression statistics module."""

import sys
from pathlib import Path

import numpy as np
import anndata
from core.adata_cache import locked_backed_adata

from analysis.utils import extract_gene_columns
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

    Note: `cell_type_filter` 是**死参数** —— 签名里有，函数体从不读它，也无人传入
    （全仓只有这一处出现）。保留只是为了不动调用方签名；别以为它真在过滤。
    """
    genes = [g.strip() for g in genes_str.split(',') if g.strip()]

    # `group_by` 必须进缓存键：`by_sample` 是**按 group_by 分组**的结果，
    # 键里不带它的话，第二次用别的 group_by 请求会命中第一次的缓存，页面拿到
    # 的是另一套分组的数据（而且看不出来）。condition_col 同理，早已在键里。
    cache_key = (str(real_path), real_path.stat().st_mtime, condition_col or '',
                 group_by, tuple(sorted(genes)))
    cached = _expr_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        with locked_backed_adata(str(real_path)) as adata:

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

            # 标签一律取字符串 —— 与 stats.py / plots.py 同一个 idiom（B43）。
            #
            # 不这么做的话，下面每一条 `sample_vals == us` / `all_ct_values == ct`
            # 都是拿**原始值**比**字符串标签**（us / ct 来自 `str(x)` 的集合）：
            # 组列或 CellType 若是 int64，比较全 False → 三个 by_* 列表**全空**，
            # 而且**不抛任何异常** —— 前端只是一片空白，没人会知道是标签类型的问题。
            sample_vals = adata.obs[group_by].values.astype(str)
            cond_vals = adata.obs[cond_col].values.astype(str) if cond_col else None
            unique_samples = sorted(set(sample_vals))
            unique_conditions = sorted(set(cond_vals)) if cond_col else ['All']
            all_ct_values = (adata.obs['CellType'].values.astype(str)
                             if 'CellType' in adata.obs.columns else None)
            # all_ct_values 上面已 .astype(str)，这里不必再 str(x) 空包一层。
            unique_ct = sorted(set(all_ct_values)) if all_ct_values is not None else []

            # Every requested gene column is read once, here, while the file lock
            # is held. Three aggregation passes below each need all of them, and
            # X[:, gi] is a real HDF5 read against a handle that must not escape.
            # extract_gene_columns materialises the matrix once for the whole set —
            # a bare per-column loop re-reads it once per gene (see utils).
            dense_by_gene = extract_gene_columns(adata.X, gene_indices)
        # Lock released — the aggregation passes below touch no HDF5.

        # Per-sample stats (for box plots)
        by_sample: list[dict] = []
        for gi, gn in zip(gene_indices, valid_genes):
            if gi < 0:
                continue
            gene_expr = dense_by_gene[gi]

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
                gene_expr = dense_by_gene[gi]
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
                gene_expr = dense_by_gene[gi]
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
