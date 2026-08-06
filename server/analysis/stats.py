#!/usr/bin/env python3
"""Statistical tests for per-sample and aggregate analysis."""

import sys
import itertools

import numpy as np
import pandas as pd
import anndata
from core.adata_cache import get_adata
from scipy.stats import mannwhitneyu, fisher_exact
from config import OBS_COLUMNS

from analysis.utils import resolve_gene_indices, resolve_group_column


def _get_per_sample_table(real_path: str, genes_str: str,
                           group_col: str = 'Group',
                           celltype_col: str = 'CellType') -> dict:
    """Per-sample x per-cell-type detail table for the BoxPlot tab.

    Returns JSON with 'rows': list of {SampleID, CellType, CellTypeNumber,
    CellTotalNumber, CellTypeRatio, Gene, GeneMeanExpression,
    GeneExpressionPct, GeneExpressionNumber, Group}.
    """
    try:
        adata = get_adata(real_path)

        if 'Sample' not in adata.obs.columns:
            return {'error': 'Sample column not found'}
        if celltype_col not in adata.obs.columns:
            return {'error': f'{celltype_col} not found in obs'}

        # Resolve group column (skip grouping when 'None')
        if group_col and group_col != 'None':
            group_col = resolve_group_column(adata, group_col)
        else:
            group_col = ''

        # Resolve genes
        genes = [g.strip() for g in genes_str.split(',') if g.strip()]
        var_names = adata.var_names
        gene_indices, valid_genes = [], []
        for g in genes:
            idx = None
            for i, n in enumerate(var_names):
                if n.lower() == g.lower():
                    idx, _ = i, str(n)
                    break
            if idx is None:
                partial = [n for n in var_names if g.lower() in n.lower()]
                if partial:
                    idx = list(var_names).index(partial[0])
            gene_indices.append(idx if idx is not None else -1)
            valid_genes.append(str(var_names[idx]) if idx is not None else g)

        sample_vals = adata.obs['Sample'].values.astype(str)
        ct_vals = adata.obs[celltype_col].values.astype(str)
        unique_samples = sorted(set(sample_vals))
        unique_ct = sorted(set(ct_vals))

        # Sample -> Group map
        s_to_g = {}
        if group_col and group_col in adata.obs.columns:
            sf = pd.DataFrame({'Sample': sample_vals, 'G': adata.obs[group_col].values.astype(str)}).drop_duplicates('Sample')
            s_to_g = dict(zip(sf['Sample'], sf['G']))

        X = adata.X
        rows = []

        for gi, gn in zip(gene_indices, valid_genes):
            if gi < 0:
                continue
            col = X[:, gi]
            gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()

            for us in unique_samples:
                s_mask = sample_vals == us
                total_n = int(s_mask.sum())
                if total_n == 0:
                    continue
                condition = s_to_g.get(us, 'Unknown')

                for ct in unique_ct:
                    combo = s_mask & (ct_vals == ct)
                    ct_n = int(combo.sum())
                    if ct_n > 0:
                        sub = gene_expr[combo]
                        mn = round(float(sub.mean()), 4)
                        pct = round(float((sub > 0).mean() * 100), 2)
                        expr_n = int((sub > 0).sum())
                    else:
                        mn, pct, expr_n = 0.0, 0.0, 0
                    rows.append({
                        'SampleID': us,
                        'CellType': ct,
                        'CellTypeNumber': ct_n,
                        'CellTotalNumber': total_n,
                        'CellTypeRatio': round(ct_n / total_n * 100, 2),
                        'Gene': gn,
                        'GeneMeanExpression': mn,
                        'GeneExpressionPct': pct,
                        'GeneExpressionNumber': expr_n,
                        'Group': condition,
                    })
        return {'rows': rows, 'n_rows': len(rows)}
    except Exception as e:
        print(f'[GenSci] Per-sample table error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


def _get_per_sample_mutest(real_path: str, genes_str: str,
                            group_col: str = 'Group',
                            celltype_col: str = 'CellType',
                            min_cells: int = 2) -> dict:
    """Per-cell-type MU test between group pairs, for mean_expression
    and expression_pct separately.

    Returns:
      'groups': ordered group names
      'cell_types': [...]
      'mean_matrix': [[pval, ...], ...]
      'pct_matrix':  [[pval, ...], ...]
      'pairs': ['A_vs_B', ...]
    """
    try:
        adata = get_adata(real_path)

        if 'Sample' not in adata.obs.columns:
            return {'error': 'Sample column not found'}
        if celltype_col not in adata.obs.columns:
            return {'error': f'{celltype_col} not found'}

        # Resolve group column (skip grouping when 'None')
        if group_col and group_col != 'None':
            group_col = resolve_group_column(adata, group_col)
        else:
            group_col = ''

        # Resolve genes (only first gene for this test)
        genes = [g.strip() for g in genes_str.split(',') if g.strip()]
        var_names = adata.var_names
        gene_idx, gene_name = -1, genes[0] if genes else ''
        for g in genes:
            for i, n in enumerate(var_names):
                if n.lower() == g.lower():
                    gene_idx, gene_name = i, str(n)
                    break
            if gene_idx >= 0:
                break
        if gene_idx < 0:
            return {'error': f'Gene "{genes[0]}" not found'}

        sample_vals = adata.obs['Sample'].values.astype(str)
        ct_vals = adata.obs[celltype_col].values.astype(str)
        cond_vals = adata.obs[group_col].values.astype(str) if group_col and group_col in adata.obs.columns else ['All'] * adata.n_obs
        unique_ct = sorted(set(ct_vals))
        unique_samples = sorted(set(sample_vals))

        # Order groups: disease first, control last
        def _g_sort(g):
            return 1 if any(k in g.lower() for k in ('control', 'normal', 'healthy')) else 0
        unique_groups = sorted(set(cond_vals), key=lambda g: (_g_sort(g), g))

        # Sample -> group map
        sf = pd.DataFrame({'S': sample_vals, 'G': cond_vals}).drop_duplicates('S')
        s_to_g = dict(zip(sf['S'], sf['G']))

        X = adata.X
        col = X[:, gene_idx]
        gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
        # Per-sample, per-cell-type aggregates
        agg_store: dict[tuple[str, str], dict] = {}
        for us in unique_samples:
            s_mask = sample_vals == us
            if s_mask.sum() == 0:
                continue
            for ct in unique_ct:
                combo = s_mask & (ct_vals == ct)
                n = int(combo.sum())
                if n <= min_cells:
                    continue
                sub = gene_expr[combo]
                agg_store[(us, ct)] = {
                    'mean': float(sub.mean()),
                    'pct': float((sub > 0).mean() * 100),
                }

        # Group pairs
        pairs = list(itertools.combinations(unique_groups, 2))
        pair_labels = [f'{a}_vs_{b}' for a, b in pairs]

        mean_matrix, pct_matrix = [], []
        for a, b in pairs:
            mean_row, pct_row = [], []
            for ct in unique_ct:
                vals_a_mean = []
                vals_a_pct = []
                vals_b_mean = []
                vals_b_pct = []
                for us in unique_samples:
                    g = s_to_g.get(us, '')
                    key = (us, ct)
                    if key not in agg_store:
                        continue
                    rec = agg_store[key]
                    if g == a:
                        vals_a_mean.append(rec['mean'])
                        vals_a_pct.append(rec['pct'])
                    elif g == b:
                        vals_b_mean.append(rec['mean'])
                        vals_b_pct.append(rec['pct'])

                # MU test for mean_expression
                if len(vals_a_mean) >= 2 and len(vals_b_mean) >= 2:
                    try:
                        _, p = mannwhitneyu(vals_a_mean, vals_b_mean, alternative='two-sided')
                        mean_row.append(round(float(p), 6))
                    except Exception:
                        mean_row.append(None)
                else:
                    mean_row.append(None)

                # MU test for expression_pct
                if len(vals_a_pct) >= 2 and len(vals_b_pct) >= 2:
                    try:
                        _, p = mannwhitneyu(vals_a_pct, vals_b_pct, alternative='two-sided')
                        pct_row.append(round(float(p), 6))
                    except Exception:
                        pct_row.append(None)
                else:
                    pct_row.append(None)

            mean_matrix.append(mean_row)
            pct_matrix.append(pct_row)

        return {
            'groups': unique_groups,
            'cell_types': unique_ct,
            'pairs': pair_labels,
            'mean_matrix': mean_matrix,
            'pct_matrix': pct_matrix,
        }

    except Exception as e:
        print(f'[GenSci] Per-sample mutest error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


def _get_aggregate_table(real_path: str, genes_str: str,
                          group_col: str = 'Group',
                          celltype_col: str = 'CellType') -> dict:
    """Per-gene, per-celltype, per-group stats + Fisher exact test.

    Returns:
      'rows': flat list of {Gene, CellType, Group, CellTypeNumber,
              CellTotalNumber, CellTypeRatio, GeneMeanExpression,
              GeneExpressionPct, GeneExpressionNumber}
      'groups': ordered group names (disease first, control last)
      'fisher': {'pairs': [...], 'cell_types': [...], 'matrix': [[pval,...],...]}
    """
    try:
        adata = get_adata(real_path)

        if celltype_col not in adata.obs.columns:
            return {'error': f'{celltype_col} not found in obs'}

        # Resolve genes
        genes = [g.strip() for g in genes_str.split(',') if g.strip()]
        var_names = adata.var_names
        gene_indices, valid_genes = [], []
        for g in genes:
            idx = None
            for i, n in enumerate(var_names):
                if n.lower() == g.lower():
                    idx, _ = i, str(n)
                    break
            if idx is None:
                partial = [n for n in var_names if g.lower() in n.lower()]
                if partial:
                    idx = list(var_names).index(partial[0])
            gene_indices.append(idx if idx is not None else -1)
            valid_genes.append(str(var_names[idx]) if idx is not None else g)

        # Get celltype array
        ct_vals = adata.obs[celltype_col].values.astype(str)
        unique_ct = sorted(set(ct_vals))

        X = adata.X
        rows = []

        if not group_col:
            # ── Ungrouped mode: aggregate per CellType only ──
            for gi, gn in zip(gene_indices, valid_genes):
                if gi < 0: continue
                col = X[:, gi]
                gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
                for ct in unique_ct:
                    ct_mask = ct_vals == ct
                    ct_n = int(ct_mask.sum())
                    if ct_n > 0:
                        sub = gene_expr[ct_mask]
                        mn = round(float(sub.mean()), 4)
                        pct = round(float((sub > 0).mean() * 100), 2)
                        expr_n = int((sub > 0).sum())
                    else:
                        mn, pct, expr_n = 0.0, 0.0, 0
                    rows.append({
                        'Gene': gn, 'CellType': ct, 'Group': '',
                        'CellTypeNumber': ct_n, 'CellTotalNumber': adata.n_obs,
                        'CellTypeRatio': round(ct_n / adata.n_obs * 100, 2),
                        'GeneMeanExpression': mn, 'GeneExpressionPct': pct,
                        'GeneExpressionNumber': expr_n,
                    })
            return {'rows': rows, 'groups': [], 'fisher': None}

        # ── Grouped mode (original) ──
        group_col = resolve_group_column(adata, group_col)
        g_vals = adata.obs[group_col].values.astype(str)
        unique_groups = sorted(set(g_vals), key=lambda g: (
            1 if any(k in g.lower() for k in ('control', 'normal', 'healthy')) else 0, g))

        for gi, gn in zip(gene_indices, valid_genes):
            if gi < 0:
                continue
            col = X[:, gi]
            gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()

            for grp in unique_groups:
                g_mask = g_vals == grp
                total_in_group = int(g_mask.sum())
                if total_in_group == 0:
                    continue

                for ct in unique_ct:
                    combo = g_mask & (ct_vals == ct)
                    ct_n = int(combo.sum())
                    if ct_n > 0:
                        sub = gene_expr[combo]
                        mn = round(float(sub.mean()), 4)
                        pct = round(float((sub > 0).mean() * 100), 2)
                        expr_n = int((sub > 0).sum())
                    else:
                        mn, pct, expr_n = 0.0, 0.0, 0

                    rows.append({
                        'Gene': gn, 'CellType': ct, 'Group': grp,
                        'CellTypeNumber': ct_n, 'CellTotalNumber': total_in_group,
                        'CellTypeRatio': round(ct_n / total_in_group * 100, 2) if total_in_group > 0 else 0.0,
                        'GeneMeanExpression': mn, 'GeneExpressionPct': pct,
                        'GeneExpressionNumber': expr_n,
                    })
        # Fisher exact test for each group pair x cell type
        group_pairs = list(itertools.combinations(unique_groups, 2))
        pair_labels = [f'{a}_vs_{b}' for a, b in group_pairs]
        fisher_matrix = []

        # Build a lookup: (Gene, CellType, Group) -> row
        lookup = {}
        for r in rows:
            lookup[(r['Gene'], r['CellType'], r['Group'])] = r

        for a, b in group_pairs:
            row_pvals = []
            for ct in unique_ct:
                r_a = lookup.get((valid_genes[0] if valid_genes else '', ct, a))
                r_b = lookup.get((valid_genes[0] if valid_genes else '', ct, b))
                if r_a and r_b:
                    a_expr = r_a['GeneExpressionNumber']
                    a_non = r_a['CellTypeNumber'] - a_expr
                    b_expr = r_b['GeneExpressionNumber']
                    b_non = r_b['CellTypeNumber'] - b_expr
                    table = [[a_expr, b_expr], [a_non, b_non]]
                    try:
                        _, p = fisher_exact(table)
                        row_pvals.append(round(float(p), 6))
                    except Exception:
                        row_pvals.append(None)
                else:
                    row_pvals.append(None)
            fisher_matrix.append(row_pvals)

        return {
            'rows': rows,
            'n_rows': len(rows),
            'groups': unique_groups,
            'fisher': {
                'pairs': pair_labels,
                'cell_types': unique_ct,
                'matrix': fisher_matrix,
            },
        }

    except Exception as e:
        print(f'[GenSci] Aggregate table error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


# ═══════════════════════════════════════════════════════
# Raw expression data download
# ═══════════════════════════════════════════════════════

MAX_GENES = 50
MAX_ROWS = 100_000


def _get_raw_expression(real_path: str, genes_str: str,
                        cell_types_str: str = '') -> str:
    """Build CSV string of obs metadata + gene expression for download.

    Filters to specified cell types, enforces row/gene limits.
    Returns CSV as a string (or 'error\\tmessage' on failure).
    Genes and cell_types are comma-separated.
    """
    genes = [g.strip() for g in genes_str.split(',') if g.strip()]
    if not genes:
        return 'error\tNo genes specified'
    if len(genes) > MAX_GENES:
        return f'error\tToo many genes ({len(genes)}), max {MAX_GENES}'

    req_ct = {c.strip() for c in cell_types_str.split(',') if c.strip()}

    try:
        adata = get_adata(real_path)
    except Exception as e:
        return f'error\tFailed to read h5ad: {e}'

    resolved = resolve_gene_indices(adata.var_names, genes)
    valid = [(idx, name) for idx, name in resolved if idx >= 0]
    if not valid:
        return 'error\tNo valid genes found'

    seen_idx = set()
    deduped = []
    for idx, name in valid:
        if idx not in seen_idx:
            seen_idx.add(idx)
            deduped.append((idx, name))

    obs_cols = [c for c in OBS_COLUMNS if c in adata.obs.columns]
    ct_col = 'CellType' if 'CellType' in adata.obs.columns else (obs_cols[0] if obs_cols else '')
    if not ct_col:
        return 'error\tNo CellType-like column found in obs'

    ct_vals = adata.obs[ct_col].values.astype(str)

    if req_ct:
        valid_mask = np.isin(ct_vals, list(req_ct))
        matching = set(ct_vals[valid_mask])
        if not matching:
            available = sorted(set(ct_vals))
            return f'error\tNone of the specified cell types found\nAvailable: {", ".join(available[:20])}'
    else:
        valid_mask = np.ones(adata.n_obs, dtype=bool)

    row_indices = np.where(valid_mask)[0]
    total = len(row_indices)
    if total > MAX_ROWS:
        row_indices = row_indices[:MAX_ROWS]
        truncated = True
    else:
        truncated = False

    # Pre-extract obs index (cell barcodes)
    obs_index = adata.obs.index.values.astype(str)

    header_cols = ['Cell'] + list(obs_cols) + [name for _, name in deduped]
    csv_lines = [','.join(header_cols)]

    X = adata.X
    expr_data = {}
    for g_idx, g_name in deduped:
        col = X[:, g_idx]
        expr_data[g_name] = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()

    for ri in row_indices:
        row_vals = [obs_index[ri]]
        for c in obs_cols:
            v = str(adata.obs[c].values[ri])
            if ',' in v:
                v = f'"{v}"'
            row_vals.append(v)
        for _, g_name in deduped:
            row_vals.append(f'{expr_data[g_name][ri]:.6f}')
        csv_lines.append(','.join(row_vals))
    if truncated:
        last_col = header_cols[-1]
        csv_lines.append(f'# TRUNCATED: {total} rows matched, showing first {MAX_ROWS}')

    return '\n'.join(csv_lines)