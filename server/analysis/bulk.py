#!/usr/bin/env python3
"""Bulk RNA analysis: gene-expression boxplot + differential expression.

Bulk datasets have no CellType/X_umap — each obs row is one sample, grouped by
the Group column (Tumor/Normal) and optionally filtered by Disease (cancer type).
These functions read the imported .h5ad cache (see bulk_import.py), not the raw
table.
"""

import base64
import io
import sys
import threading
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import ttest_ind

from core.adata_cache import locked_backed_adata
from analysis.utils import build_cond_palette, cond_sort_key


plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif', 'Times', 'serif']

# Cache the (expensive) full-gene DE result per (path, mtime, disease) so the
# table and volcano endpoints share one t-test instead of each recomputing it.
_de_cache: dict[tuple[str, float, str], tuple[list, int, int]] = {}
_de_cache_lock = threading.Lock()
_DE_CACHE_MAX = 8


def _resolve_gene(var_names, gene: str) -> tuple[int, str]:
    """Return (index, actual_name) for a gene, exact then partial match."""
    gene = gene.strip()
    for i, n in enumerate(var_names):
        if str(n).lower() == gene.lower():
            return i, str(n)
    partial = [n for n in var_names if gene.lower() in str(n).lower()]
    if partial:
        i = list(var_names).index(partial[0])
        return i, str(var_names[i])
    return -1, gene


def _find_group(group_vals, keyword: str) -> str | None:
    """Return the first group value containing `keyword` (case-insensitive)."""
    seen = sorted(set(str(g) for g in group_vals))
    return next((g for g in seen if keyword in g.lower()), None)


def _json_safe(v):
    """Return a JSON-safe float (None for NaN/inf, which are invalid JSON).

    Welch t-test produces NaN for genes with zero variance or all-NaN expression;
    the browser's JSON.parse rejects the literal `NaN` token.
    """
    f = float(v)
    return f if np.isfinite(f) else None


def bulk_diseases(real_path: str) -> dict:
    """Return the distinct Disease values for a bulk dataset."""
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Disease' not in adata.obs.columns:
                return {'diseases': [], 'error': 'Disease column not found in obs'}
            diseases = sorted(set(str(d) for d in adata.obs['Disease'].dropna()))
        return {'diseases': diseases}
    except Exception as e:
        print(f'[GenSci] bulk_diseases error: {e}', file=sys.stderr)
        return {'diseases': [], 'error': str(e)}


def bulk_boxplot(real_path: str, gene: str, disease: str | None = None,
                 palette_name: str = 'default') -> dict:
    """Boxplot of a single gene's expression.

    x-axis = Disease (cancer type), hue = Group (Tumor/Normal).
    disease=None → one panel per disease (all cancers on the x-axis);
    otherwise only that disease's samples are shown.
    Returns {'image': base64, 'width', 'height'} or {'error': str}.
    """
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'error': 'Group column (Tumor/Normal) not found in obs'}
            if 'Disease' not in adata.obs.columns:
                return {'error': 'Disease column not found in obs'}
            gene_idx, actual_gene = _resolve_gene(adata.var_names, gene)
            if gene_idx < 0:
                return {'error': f'Gene "{gene}" not found'}

            col = adata.X[:, gene_idx]
            expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.asarray(col).flatten()
            expr = expr.astype(np.float64)
            group_vals = adata.obs['Group'].astype(str).values.copy()
            disease_vals = adata.obs['Disease'].astype(str).values.copy()

            mask = np.ones(adata.n_obs, dtype=bool)
            if disease and disease != 'All':
                mask = disease_vals == disease

        expr = expr[mask]
        group_vals = group_vals[mask]
        disease_vals = disease_vals[mask]

        disp_disease = [str(d)[5:] if str(d).startswith('TCGA-') else str(d) for d in disease_vals]
        df = pd.DataFrame({'Disease': disp_disease, 'Group': group_vals, 'Expression': expr})
        disease_order = sorted(df['Disease'].unique())
        group_order = sorted(df['Group'].unique(), key=cond_sort_key)
        palette = build_cond_palette(group_order, palette_name)
        n_diseases = len(disease_order)

        fig_w = max(6, min(22, n_diseases * 0.45))
        fig, ax = plt.subplots(figsize=(fig_w, 5), dpi=100)
        sns.boxplot(
            data=df, x='Disease', y='Expression', hue='Group',
            order=disease_order, hue_order=group_order,
            palette=palette, ax=ax, showfliers=False, fill=False,
            linewidth=1.3,
        )
        sns.stripplot(
            data=df, x='Disease', y='Expression', hue='Group',
            order=disease_order, hue_order=group_order,
            palette=palette, ax=ax, size=1.5, alpha=0.35, jitter=0.28,
            dodge=True, legend=False,
        )
        title = f'{actual_gene} — {disease if disease and disease != "All" else "All diseases"}'
        ax.set_title(title, fontsize=12)
        ax.set_ylabel('Expression (TPM)')
        ax.set_xlabel(None)
        if n_diseases > 8:
            ax.tick_params(axis='x', labelrotation=90)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)

        # Legend (one entry per Group)
        handles = [plt.Rectangle((0, 0), 0, 0, color=palette[g], label=g) for g in group_order]
        ax.legend(handles=handles, bbox_to_anchor=(1.01, 0.5), loc='center left',
                  frameon=False, fontsize=10, title=None)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                    facecolor='white')
        plt.close(fig)
        img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {'image': img_b64, 'width': fig_w, 'height': 5}
    except Exception as e:
        print(f'[GenSci] bulk_boxplot error: {e}', file=sys.stderr)
        return {'error': str(e)}


def _bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR correction (vectorized, NaN-safe)."""
    p = np.asarray(pvals, dtype=float)
    n = p.size
    fdr = np.ones(n)
    valid = ~np.isnan(p)
    m = int(valid.sum())
    if m == 0:
        return fdr
    pv = p[valid]
    order = np.argsort(pv)
    ranked = pv[order]
    adjusted = ranked * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    fdr_valid = np.empty(m)
    fdr_valid[order] = adjusted
    fdr[valid] = fdr_valid
    return fdr


def _compute_de(adata, disease: str | None) -> tuple[list[dict], int, int]:
    """Run Tumor vs Normal Welch t-test + BH FDR across all genes.

    Returns (rows, n_tumor, n_normal) where rows is sorted by padj. Caller must
    hold the adata lock (backed file must remain open while X is read).
    """
    group_vals = adata.obs['Group'].astype(str).values
    mask = np.ones(adata.n_obs, dtype=bool)
    if disease and disease != 'All':
        mask = adata.obs['Disease'].astype(str).values == disease
    group_vals = group_vals[mask]
    tumor_g = _find_group(group_vals, 'tumor')
    normal_g = _find_group(group_vals, 'normal')
    if tumor_g is None or normal_g is None:
        raise ValueError('Group must contain both Tumor and Normal values')

    var_names = list(adata.var_names)
    tumor_mask = mask & (adata.obs['Group'].astype(str).values == tumor_g)
    normal_mask = mask & (adata.obs['Group'].astype(str).values == normal_g)

    x_tumor = adata.X[tumor_mask]
    x_normal = adata.X[normal_mask]
    x_tumor = x_tumor.toarray() if hasattr(x_tumor, 'toarray') else np.asarray(x_tumor)
    x_normal = x_normal.toarray() if hasattr(x_normal, 'toarray') else np.asarray(x_normal)
    x_tumor = x_tumor.astype(np.float64)
    x_normal = x_normal.astype(np.float64)

    if x_tumor.shape[0] < 2 or x_normal.shape[0] < 2:
        raise ValueError('Insufficient Tumor/Normal samples for the test')

    mean_tumor = x_tumor.mean(axis=0)
    mean_normal = x_normal.mean(axis=0)
    _, pvals = ttest_ind(x_tumor, x_normal, axis=0, equal_var=False, nan_policy='omit')
    padj = _bh_fdr(pvals)
    log2fc = np.log2((mean_tumor + 1.0) / (mean_normal + 1.0))

    n_genes = len(var_names)
    rows = []
    for i in range(n_genes):
        rows.append({
            'gene': str(var_names[i]),
            'mean_tumor': round(float(mean_tumor[i]), 4),
            'mean_normal': round(float(mean_normal[i]), 4),
            'log2fc': round(float(log2fc[i]), 4),
            'pvalue': float(pvals[i]),
            'padj': float(padj[i]),
        })
    rows.sort(key=lambda r: (r['padj'], r['pvalue']))
    return rows, int(x_tumor.shape[0]), int(x_normal.shape[0])


def _compute_de_cached(real_path: str, adata, disease: str | None) -> tuple[list, int, int]:
    """Memoised _compute_de keyed by (path, mtime, disease)."""
    mtime = Path(real_path).stat().st_mtime
    key = (real_path, mtime, disease or 'All')
    with _de_cache_lock:
        hit = _de_cache.get(key)
        if hit is not None:
            return hit
    result = _compute_de(adata, disease)
    with _de_cache_lock:
        _de_cache[key] = result
        while len(_de_cache) > _DE_CACHE_MAX:
            _de_cache.pop(next(iter(_de_cache)))
    return result


def bulk_de(real_path: str, disease: str | None = None, top_n: int = 100) -> dict:
    """Differential expression: Tumor vs Normal (Welch t-test + BH FDR).

    Returns {'genes': [{gene, mean_tumor, mean_normal, log2fc, pvalue, padj}],
             'n_total', 'n_tumor', 'n_normal', 'disease'} sorted by padj.
    top_n <= 0 returns ALL genes (used for CSV download). Errors as {'error'}.
    """
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'error': 'Group column (Tumor/Normal) not found in obs'}
            rows, n_tumor, n_normal = _compute_de_cached(real_path, adata, disease)
        genes = rows[:top_n] if top_n > 0 else rows
        safe_genes = [
            {
                'gene': g['gene'],
                'mean_tumor': _json_safe(g['mean_tumor']),
                'mean_normal': _json_safe(g['mean_normal']),
                'log2fc': _json_safe(g['log2fc']),
                'pvalue': _json_safe(g['pvalue']),
                'padj': _json_safe(g['padj']),
            }
            for g in genes
        ]
        return {
            'genes': safe_genes,
            'n_total': len(rows),
            'n_tumor': n_tumor,
            'n_normal': n_normal,
            'disease': disease if disease and disease != 'All' else 'All',
        }
    except Exception as e:
        print(f'[GenSci] bulk_de error: {e}', file=sys.stderr)
        return {'error': str(e)}


def bulk_volcano(real_path: str, disease: str | None = None,
                 fc_thresh: float = 1.0, alpha: float = 0.05) -> dict:
    """Volcano plot: -log10(padj) vs log2fc, up/down/n.s. genes highlighted.

    Returns {'image': base64, 'width', 'height', 'n_up', 'n_down', 'n_ns'}.
    """
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'error': 'Group column (Tumor/Normal) not found in obs'}
            rows, _, _ = _compute_de_cached(real_path, adata, disease)

        log2fc = np.array([r['log2fc'] for r in rows], dtype=float)
        padj = np.array([r['padj'] for r in rows], dtype=float)
        neg_log = -np.log10(np.clip(padj, 1e-300, None))

        up = (log2fc >= fc_thresh) & (padj < alpha)
        down = (log2fc <= -fc_thresh) & (padj < alpha)
        ns = ~(up | down)

        fig, ax = plt.subplots(figsize=(7, 6), dpi=100)
        ax.scatter(log2fc[ns], neg_log[ns], s=5, c='#c0c0c0', alpha=0.4,
                   label=f'n.s. ({int(ns.sum())})', rasterized=True)
        ax.scatter(log2fc[up], neg_log[up], s=6, c='#d62728', alpha=0.5,
                   label=f'Up ({int(up.sum())})', rasterized=True)
        ax.scatter(log2fc[down], neg_log[down], s=6, c='#1f77b4', alpha=0.5,
                   label=f'Down ({int(down.sum())})', rasterized=True)
        ax.axhline(-np.log10(alpha), color='#888888', linestyle='--', linewidth=0.8)
        ax.axvline(fc_thresh, color='#888888', linestyle='--', linewidth=0.8)
        ax.axvline(-fc_thresh, color='#888888', linestyle='--', linewidth=0.8)
        ax.set_xlabel('log2 Fold Change (Tumor / Normal)')
        ax.set_ylabel('-log10(adjusted p-value)')
        title = f'Volcano — {disease if disease and disease != "All" else "All diseases"}'
        ax.set_title(title, fontsize=12)
        ax.legend(frameon=False, fontsize=9, markerscale=2)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                    facecolor='white')
        plt.close(fig)
        img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {
            'image': img_b64, 'width': 7, 'height': 6,
            'n_up': int(up.sum()), 'n_down': int(down.sum()), 'n_ns': int(ns.sum()),
        }
    except Exception as e:
        print(f'[GenSci] bulk_volcano error: {e}', file=sys.stderr)
        return {'error': str(e)}
