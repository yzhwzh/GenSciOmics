#!/usr/bin/env python3
"""Bulk RNA analysis: gene-expression boxplot + differential expression.

Bulk datasets have no CellType/X_umap — each obs row is one sample, grouped by
the Group column (Tumor/Normal) and optionally filtered by Disease (cancer type).
These functions read the imported .h5ad cache (see bulk_import.py), not the raw
table.
"""

import base64
import io
import re
import sys
import threading
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import mannwhitneyu, ttest_ind

from core.adata_cache import locked_backed_adata
from analysis.utils import build_cond_palette
from scanner import _extract_data_type  # filename → count/TPM/FPKM/RPKM/Intensity


plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif', 'Times', 'serif']

# Cache the (expensive) full-gene DE result per (path, mtime, disease) so the
# table and volcano endpoints share one t-test instead of each recomputing it.
_de_cache: dict[tuple[str, float, str], tuple[list, int, int]] = {}
_de_cache_lock = threading.Lock()
_DE_CACHE_MAX = 8

# Marker size for the boxplot scatter points (seaborn stripplot `size`), shared
# by both the group-comparison and the disease/tissue panel render.
_STRIP_SIZE = 2.0


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


def _classify_group(value: str) -> str:
    """Classify a Group value as 'case', 'control', or 'unknown'.

    Handles standard naming (Tumor/Normal, Case/Control, Disease/Healthy) via
    keyword + negation-prefix rules. Concrete disease acronyms (GHoma/NFPA) are
    'unknown' — the caller surfaces them for manual selection.
    """
    v = value.strip().lower()
    if not v:
        return 'unknown'
    if v.startswith(('non', 'not', 'adjacent', 'adj', 'para', 'peri')):
        return 'control'
    if any(k in v for k in ('tumor', 'tumour', 'cancer', 'carcinoma', 'case',
                            'disease', 'patient', 'lesion', 'positive')):
        return 'case'
    if any(k in v for k in ('normal', 'healthy', 'control', 'negative', 'benign',
                            'reference', 'wild')):
        return 'control'
    return 'unknown'


def _group_sort_key(name: str) -> tuple:
    """Boxplot group order: if a group name contains a number, sort by that
    number ascending; non-numeric names (e.g. 'Normal') come after, with
    control/normal/healthy last. Both tuple branches share the (int, int, str)
    shape so mixed names stay comparable."""
    ln = name.lower()
    m = re.search(r'\d+', name)
    if m:
        return (0, int(m.group()), name)
    is_ctrl = any(k in ln for k in ('control', 'normal', 'healthy'))
    return (1, 1 if is_ctrl else 0, name)


def _find_case_control(group_vals) -> tuple[str | None, str | None]:
    """Auto-classify group values into (case, control).

    Prefers an explicit control name (Normal/Healthy/Control) over a negated one
    (Non-tumor/Para-tumor) when both are present. Returns (None, None) when no
    value is classifiable (e.g. concrete disease acronyms), signalling the caller
    to ask for manual case_group/control_group.
    """
    seen = sorted(set(str(g) for g in group_vals))
    case = control = None
    negated_control = None
    for g in seen:
        c = _classify_group(g)
        if c == 'case' and case is None:
            case = g
        elif c == 'control':
            gl = g.lower()
            if gl.startswith(('non', 'not', 'adjacent', 'adj', 'para', 'peri')):
                negated_control = negated_control or g
            elif control is None:
                control = g
    if control is None:
        control = negated_control
    return case, control


def _json_safe(v):
    """Return a JSON-safe float (None for NaN/inf, which are invalid JSON).

    Welch t-test produces NaN for genes with zero variance or all-NaN expression;
    the browser's JSON.parse rejects the literal `NaN` token.
    """
    f = float(v)
    return f if np.isfinite(f) else None


def _tissue_column(obs_columns) -> str | None:
    """Return the obs column literally named 'Tissue' (the canonical organ axis).

    Used to offer 'Tissue' as an alternative panel x-axis (see bulk_boxplot).
    Matching is exact and case-insensitive; no fuzzy keyword guessing.
    """
    for c in obs_columns:
        if str(c).strip().lower() == 'tissue':
            return str(c)
    return None


def bulk_diseases(real_path: str) -> dict:
    """Return the distinct Disease values for a bulk dataset, plus whether it has
    an organ/tissue axis ('tissue_column' — None when absent)."""
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Disease' not in adata.obs.columns:
                return {'diseases': [], 'error': 'Disease column not found in obs'}
            diseases = sorted(set(str(d) for d in adata.obs['Disease'].dropna()))
            tissue = _tissue_column(adata.obs.columns)
        return {'diseases': diseases, 'tissue_column': tissue}
    except Exception as e:
        print(f'[GenSci] bulk_diseases error: {e}', file=sys.stderr)
        return {'diseases': [], 'tissue_column': None, 'error': str(e)}


def bulk_groups(real_path: str) -> dict:
    """Return the distinct Group values for a bulk dataset."""
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'groups': [], 'error': 'Group column not found in obs'}
            groups = sorted(set(str(g) for g in adata.obs['Group'].dropna()), key=_group_sort_key)
        return {'groups': groups}
    except Exception as e:
        print(f'[GenSci] bulk_groups error: {e}', file=sys.stderr)
        return {'groups': [], 'error': str(e)}


def _layout_brackets(pairs: list[tuple[int, int, float]]) -> list[tuple[int, int, float, int]]:
    """Assign each significant pair (i, j, p) a non-overlapping bracket level.

    Greedy interval colouring: pairs are processed most-significant first; each
    takes the lowest level whose already-placed bracket at that level does not
    overlap in x-range (overlap iff i <= other_j and j >= other_i). Returns
    (i, j, p, level).
    """
    placed: list[tuple[int, int, int]] = []  # (i, j, level)
    out: list[tuple[int, int, float, int]] = []
    for i, j, p in sorted(pairs, key=lambda t: t[2]):
        level = 0
        while any(pl == level and i <= oi and j >= oj for oj, oi, pl in placed):
            level += 1
        placed.append((i, j, level))
        out.append((i, j, p, level))
    return out


def _render_group_boxplot(real_path: str, expr, group_vals, actual_gene: str,
                          disease: str | None, palette_name: str,
                          target_group: str | None = None,
                          groups: list[str] | None = None) -> dict:
    """Group-mode boxplot: x = Group, pairwise Mann-Whitney U significance.

    expr/group_vals are already masked to the selected disease. Boxes + jittered
    scatter share the disease-mode styling; significant pairs (p < 0.05) get a
    bracket with stars (* <0.05, ** <0.01, *** <0.001) above the boxes.
    groups (optional): plot only the samples whose Group is in this list; the
    pairwise brackets/stars recompute over the shown subset only.
    """
    if not np.isfinite(expr).any():
        return {'error': 'No valid expression values for the selected disease'}
    # Show-groups subset: plot only the samples whose Group the user selected.
    # If none of the requested names match, keep everything — never render empty.
    if groups:
        keep = np.isin(group_vals, groups)
        if keep.any():
            expr = expr[keep]
            group_vals = group_vals[keep]
    df = pd.DataFrame({'Group': group_vals, 'Expression': expr})
    group_order = sorted(df['Group'].unique(), key=_group_sort_key)
    palette = build_cond_palette(group_order, palette_name)
    n_groups = len(group_order)

    # Pairwise Mann-Whitney U (two-sided); only significant pairs get brackets.
    sig: list[tuple[int, int, float]] = []
    for gi in range(n_groups):
        for gj in range(gi + 1, n_groups):
            a = expr[group_vals == group_order[gi]]
            b = expr[group_vals == group_order[gj]]
            a = a[np.isfinite(a)]
            b = b[np.isfinite(b)]
            if a.size < 2 or b.size < 2:
                continue
            try:
                _, p = mannwhitneyu(a, b, alternative='two-sided')
            except Exception:
                continue
            if not np.isfinite(p) or p >= 0.05:
                continue
            sig.append((gi, gj, float(p)))

    # Target filter: when a specific group is chosen, only draw brackets/stars
    # for significant pairs involving it (x-axis still shows every group).
    if target_group and target_group in group_order:
        ti = group_order.index(target_group)
        sig = [(i, j, p) for (i, j, p) in sig if i == ti or j == ti]

    fig_w = max(6, min(22, n_groups * 0.5))
    fig_h = 5.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)
    sns.boxplot(data=df, x='Group', y='Expression', hue='Group',
                order=group_order, hue_order=group_order, palette=palette, ax=ax,
                showfliers=False, fill=False, linewidth=1.3, legend=False)
    sns.stripplot(data=df, x='Group', y='Expression', hue='Group',
                  order=group_order, hue_order=group_order, palette=palette, ax=ax,
                  size=_STRIP_SIZE, alpha=0.9, jitter=0.2, dodge=False, edgecolor='k',
                  linewidth=0.5, legend=False)

    ymin = float(np.nanmin(expr))
    ymax = float(np.nanmax(expr))
    yrange = ymax - ymin if ymax > ymin else 1.0
    if sig:
        brackets = _layout_brackets(sig)
        gap = 0.08 * yrange
        step = 0.12 * yrange
        for i, j, p, level in brackets:
            y = ymax + gap + level * step
            stars = '***' if p < 0.001 else '**' if p < 0.01 else '*'
            # 学术风显著性括号（参照 server/skills/light-figure-drawing 的 sig_bar）：
            # 实线细线 lw=0.8，星号 fontsize=8（与图下方图例一致）；横线在上、两端竖线向下指向 box。
            ax.plot([i, i, j, j], [y, y + 0.02 * yrange, y + 0.02 * yrange, y],
                    color='black', lw=0.8, ls='-')
            ax.text((i + j) / 2, y + 0.02 * yrange, stars,
                    ha='center', va='bottom', fontsize=8, color='black')
        top = ymax + gap + (max(lv for _, _, _, lv in brackets) + 1) * step + 0.05 * yrange
        ax.set_ylim(top=top)
    else:
        ax.set_ylim(top=ymax + 0.13 * yrange)

    ax.set_title(actual_gene, fontsize=12)
    dtype = _extract_data_type(Path(real_path).stem)
    ax.set_ylabel(f'Expression ({dtype})' if dtype else 'Expression')
    ax.set_xlabel(None)
    if n_groups > 8:
        ax.tick_params(axis='x', labelrotation=90)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    # Significance-stars legend below the plot (dashes + stars only appear in
    # group mode, where this function is the only renderer). bbox_inches='tight'
    # crops the saved figure to include this axes-fraction text.
    ax.annotate('* p < 0.05    ** p < 0.01    *** p < 0.001 (Mann-Whitney U)',
                xy=(0, -0.16), xycoords='axes fraction', ha='left', va='top',
                fontsize=8, color='0.35', annotation_clip=False)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                facecolor='white')
    plt.close(fig)
    img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return {'image': img_b64, 'width': fig_w, 'height': fig_h,
            'gene_resolved': actual_gene}


def bulk_boxplot(real_path: str, gene: str, disease: str | None = None,
                 palette_name: str = 'default',
                 target_group: str | None = None,
                 groups: list[str] | None = None,
                 x_factor: str | None = None) -> dict:
    """Boxplot of a single gene's expression.

    x-axis = the panel factor (default Disease / cancer type), hue = Group
    (Tumor/Normal). x_factor selects another obs column as the panel factor
    (e.g. the 'Tissue' organ axis); it falls back to Disease when the column is
    absent. disease=None → one panel per factor value; otherwise only that
    disease's samples are shown (group mode).
    target_group (group mode only) restricts significance brackets/stars to
    pairs involving that group.
    groups restricts which Group samples are plotted — group mode recomputes
    the shown subset (x-axis + brackets); panel mode hides the hue boxes +
    legend entries for unselected groups.
    Returns {'image': base64, 'width', 'height', 'gene_resolved': str} or
    {'error': str}. `gene_resolved` is the var name actually plotted — `_resolve_gene`
    falls back to a substring match, so an unknown token silently charts a
    different gene and the UI needs to be able to say so.
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

            # Panel x-axis factor: default Disease; an explicit x_factor selects
            # another obs column (e.g. the 'Tissue' organ axis) when present.
            panel_col = 'Disease'
            if x_factor and str(x_factor).strip().lower() != 'disease':
                if str(x_factor) in adata.obs.columns:
                    panel_col = str(x_factor)
            factor_vals = (disease_vals.copy() if panel_col == 'Disease'
                           else adata.obs[panel_col].astype(str).values.copy())

            # x-axis mode: a specific disease (or a single-disease dataset) shows
            # pairwise Group comparison; otherwise one panel per factor value,
            # hue=Group. The panel factor is always Disease for this decision.
            all_diseases = sorted(set(str(d) for d in adata.obs['Disease'].dropna()))
            force_group = len(all_diseases) <= 1
            group_mode = (disease and disease != 'All') or force_group

            mask = np.ones(adata.n_obs, dtype=bool)
            if disease and disease != 'All':
                mask = disease_vals == disease

        expr = expr[mask]
        group_vals = group_vals[mask]
        disease_vals = disease_vals[mask]
        factor_vals = factor_vals[mask]

        if group_mode:
            return _render_group_boxplot(real_path, expr, group_vals, actual_gene,
                                         disease, palette_name, target_group, groups)

        # Show-groups subset (panel mode): plot only the samples whose Group the
        # user selected — hue boxes + legend entries follow the shown subset.
        if groups:
            keep = np.isin(group_vals, groups)
            if keep.any():
                expr = expr[keep]
                group_vals = group_vals[keep]
                factor_vals = factor_vals[keep]

        if panel_col == 'Disease':
            # Keep the existing Disease display: strip the TCGA- prefix.
            axis_vals = np.array([str(v)[5:] if str(v).startswith('TCGA-') else str(v)
                                  for v in factor_vals])
        else:
            axis_vals = factor_vals
        df = pd.DataFrame({'Axis': axis_vals, 'Group': group_vals, 'Expression': expr})
        axis_order = sorted(df['Axis'].unique())
        group_order = sorted(df['Group'].unique(), key=_group_sort_key)
        palette = build_cond_palette(group_order, palette_name)
        n_axes = len(axis_order)

        fig_w = max(6, min(22, n_axes * 0.45))
        fig, ax = plt.subplots(figsize=(fig_w, 5), dpi=100)
        sns.boxplot(
            data=df, x='Axis', y='Expression', hue='Group',
            order=axis_order, hue_order=group_order,
            palette=palette, ax=ax, showfliers=False, fill=False,
            linewidth=1.3,
        )
        # Scatter points keep a small jitter so overlapping dots spread
        # horizontally; dark edge keeps each dot distinct over box borders.
        sns.stripplot(
            data=df, x='Axis', y='Expression', hue='Group',
            order=axis_order, hue_order=group_order,
            palette=palette, ax=ax, size=_STRIP_SIZE, alpha=0.9, jitter=0.2,
            dodge=True, edgecolor='k', linewidth=0.5, legend=False,
        )
        ax.set_title(actual_gene, fontsize=12)
        # y-axis label follows the file's annotation (TPM/FPKM/RPKM/count/Intensity)
        dtype = _extract_data_type(Path(real_path).stem)
        ax.set_ylabel(f'Expression ({dtype})' if dtype else 'Expression')
        ax.set_xlabel(None)
        if n_axes > 8:
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
        return {'image': img_b64, 'width': fig_w, 'height': 5,
                'gene_resolved': actual_gene}
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


def _compute_de(adata, disease: str | None,
                case_group: str | None = None,
                control_group: str | None = None) -> tuple[list[dict], int, int, str, str]:
    """Run case vs control Welch t-test + BH FDR across all features.

    Returns (rows, n_case, n_control, case_g, control_g) where rows is sorted by
    padj. case/control are auto-detected from standard names (Tumor/Normal etc.)
    unless case_group/control_group are provided. Caller must hold the adata lock.
    """
    group_vals = adata.obs['Group'].astype(str).values
    mask = np.ones(adata.n_obs, dtype=bool)
    if disease and disease != 'All':
        mask = adata.obs['Disease'].astype(str).values == disease
    group_vals = group_vals[mask]
    if case_group and control_group:
        case_g = case_group
        control_g = control_group
    else:
        case_g, control_g = _find_case_control(group_vals)
    if case_g is None or control_g is None:
        raise ValueError('Group must contain both case and control values; '
                         'specify case_group/control_group')

    var_names = list(adata.var_names)
    case_mask = mask & (adata.obs['Group'].astype(str).values == case_g)
    control_mask = mask & (adata.obs['Group'].astype(str).values == control_g)

    x_case = adata.X[case_mask]
    x_control = adata.X[control_mask]
    x_case = x_case.toarray() if hasattr(x_case, 'toarray') else np.asarray(x_case)
    x_control = x_control.toarray() if hasattr(x_control, 'toarray') else np.asarray(x_control)
    x_case = x_case.astype(np.float64)
    x_control = x_control.astype(np.float64)

    if x_case.shape[0] < 2 or x_control.shape[0] < 2:
        raise ValueError('Insufficient case/control samples for the test')

    mean_case = x_case.mean(axis=0)
    mean_control = x_control.mean(axis=0)
    _, pvals = ttest_ind(x_case, x_control, axis=0, equal_var=False, nan_policy='omit')
    padj = _bh_fdr(pvals)
    log2fc = np.log2((mean_case + 1.0) / (mean_control + 1.0))

    n_genes = len(var_names)
    rows = []
    for i in range(n_genes):
        rows.append({
            'gene': str(var_names[i]),
            'mean_tumor': round(float(mean_case[i]), 4),
            'mean_normal': round(float(mean_control[i]), 4),
            'log2fc': round(float(log2fc[i]), 4),
            'pvalue': float(pvals[i]),
            'padj': float(padj[i]),
        })
    rows.sort(key=lambda r: (r['padj'], r['pvalue']))
    return rows, int(x_case.shape[0]), int(x_control.shape[0]), case_g, control_g


def _compute_de_cached(real_path: str, adata, disease: str | None,
                       case_group: str | None = None,
                       control_group: str | None = None):
    """Memoised _compute_de keyed by (path, mtime, disease, case, control)."""
    mtime = Path(real_path).stat().st_mtime
    key = (real_path, mtime, disease or 'All', case_group, control_group)
    with _de_cache_lock:
        hit = _de_cache.get(key)
        if hit is not None:
            return hit
    result = _compute_de(adata, disease, case_group, control_group)
    with _de_cache_lock:
        _de_cache[key] = result
        while len(_de_cache) > _DE_CACHE_MAX:
            _de_cache.pop(next(iter(_de_cache)))
    return result


def bulk_de(real_path: str, disease: str | None = None, top_n: int = 100,
            case_group: str | None = None, control_group: str | None = None) -> dict:
    """Differential expression: case vs control (Welch t-test + BH FDR).

    Returns {'genes': [{gene, mean_tumor, mean_normal, log2fc, pvalue, padj}],
             'n_total', 'n_tumor', 'n_normal', 'case_group', 'control_group',
             'disease'} sorted by padj.
    top_n <= 0 returns ALL genes (used for CSV download). Errors as {'error'}.
    """
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'error': 'Group column not found in obs'}
            rows, n_case, n_control, case_g, control_g = _compute_de_cached(
                real_path, adata, disease, case_group, control_group)
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
            'n_tumor': n_case,
            'n_normal': n_control,
            'case_group': case_g,
            'control_group': control_g,
            'disease': disease if disease and disease != 'All' else 'All',
        }
    except Exception as e:
        print(f'[GenSci] bulk_de error: {e}', file=sys.stderr)
        return {'error': str(e)}


def bulk_volcano(real_path: str, disease: str | None = None,
                 fc_thresh: float = 1.0, alpha: float = 0.05,
                 case_group: str | None = None, control_group: str | None = None) -> dict:
    """Volcano plot: -log10(padj) vs log2fc, up/down/n.s. genes highlighted.

    Returns {'image': base64, 'width', 'height', 'n_up', 'n_down', 'n_ns'}.
    """
    try:
        with locked_backed_adata(real_path) as adata:
            if 'Group' not in adata.obs.columns:
                return {'error': 'Group column (Tumor/Normal) not found in obs'}
            rows, _, _, case_g, control_g = _compute_de_cached(
                real_path, adata, disease, case_group, control_group)

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
        ax.set_xlabel(f'log2 Fold Change ({case_g} / {control_g})')
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
