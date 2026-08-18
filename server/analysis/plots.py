#!/usr/bin/env python3
"""Matplotlib/seaborn chart generation module."""

import base64
import io
import itertools
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from core.adata_cache import get_adata
import seaborn as sns
from matplotlib.ticker import AutoMinorLocator

from analysis.utils import build_cond_palette, cond_sort_key, get_palette
from scipy.stats import mannwhitneyu
import scanpy as sc
from core.adata_cache import locked_backed_adata


# Matplotlib global config
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif', 'Times', 'serif']
plt.rcParams['mathtext.fontset'] = 'stix'


def _generate_plot(real_path: str, gene: str, condition_col: str,
                   metric: str, plot_type: str, min_cells: int = 2,
                   palette_name: str = 'default') -> dict:
    """Generate a seaborn/matplotlib plot and return as base64 PNG."""
    try:
        # Read data
        adata = get_adata(real_path)

        # Validate columns
        if 'Sample' not in adata.obs.columns or 'CellType' not in adata.obs.columns:
            return {'error': 'Required columns "Sample" and "CellType" not found in obs'}

        # Resolve gene index
        var_names = adata.var_names
        gene_idx = None
        actual_gene = gene
        for i, n in enumerate(var_names):
            if n.lower() == gene.lower():
                gene_idx = i
                actual_gene = str(n)
                break
        if gene_idx is None:
            # Try partial match
            partial = [n for n in var_names if gene.lower() in n.lower()]
            if partial:
                gene_idx = list(var_names).index(partial[0])
                actual_gene = str(var_names[gene_idx])
            else:
                return {'error': f'Gene "{gene}" not found'}

        # Extract expression values
        col = adata.X[:, gene_idx]
        gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()

        sample_vals = adata.obs['Sample'].values
        ct_vals = adata.obs['CellType'].values
        cond_vals = None
        if condition_col and condition_col != 'None' and condition_col in adata.obs.columns:
            cond_vals = adata.obs[condition_col].values

        unique_ct = sorted(set(str(x) for x in ct_vals))
        unique_samples = sorted(set(str(x) for x in sample_vals))
        # Build DataFrame for plotting
        rows = []
        for s in unique_samples:
            s_mask = sample_vals == s
            condition = 'All'
            if cond_vals is not None:
                c_sub = cond_vals[s_mask]
                condition = str(c_sub[0])
            for ct in unique_ct:
                combo = s_mask & (ct_vals == ct)
                n = int(combo.sum())
                if n <= min_cells:
                    continue
                sub = gene_expr[combo]
                if metric == 'expression_pct':
                    val = float((sub > 0).mean() * 100)
                else:
                    val = float(sub.mean())
                rows.append({'CellType': ct, 'Sample': s,
                             'Condition': condition, 'Value': val})

        if not rows:
            return {'error': 'Insufficient data'}

        df = pd.DataFrame(rows)

        # Order: disease -> control
        cond_order = sorted(df['Condition'].unique(), key=cond_sort_key)
        ct_order = sorted(df['CellType'].unique())
        palette = build_cond_palette(cond_order, palette_name)
        n_ct = len(ct_order)

        # Create plot
        n_cond = len(cond_order)
        fig_w = max(12, n_ct * 1.0 + n_cond * 0.6)
        fig_h = max(4.5, n_ct * 0.32)
        fs = max(1.0, fig_w / 12.0)  # font scale: wider figure -> bigger fonts
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)

        if plot_type == 'boxplot':
            # Transparent boxplots + scatter points
            sns.boxplot(
                data=df, x='CellType', y='Value', hue='Condition',
                order=ct_order, hue_order=cond_order,
                palette=palette, ax=ax,
                showfliers=False, fill=False,
                linewidth=1.2,
            )
            sns.stripplot(
                data=df, x='CellType', y='Value', hue='Condition',
                order=ct_order, hue_order=cond_order,
                palette=palette, ax=ax,
                size=3, dodge=True, legend=False,
            )
            ylabel = '% Expressing' if metric == 'expression_pct' else 'Mean Expression'
        else:
            # Aggregate barplot - compute directly from all cells (matches table)
            agg_rows = []
            for ct in unique_ct:
                ct_mask = ct_vals == ct
                for cond in cond_order:
                    combo = ct_mask if cond_vals is None else ct_mask & (cond_vals == cond)
                    n = int(combo.sum())
                    if n == 0:
                        continue
                    sub = gene_expr[combo]
                    if metric == 'expression_pct':
                        val = float((sub > 0).mean() * 100)
                    else:
                        val = float(sub.mean())
                    agg_rows.append({'CellType': ct, 'Condition': cond, 'Value': val})
            agg = pd.DataFrame(agg_rows)
            sns.barplot(
                data=agg, x='CellType', y='Value', hue='Condition',
                order=ct_order, hue_order=cond_order,
                palette=palette, ax=ax,
                edgecolor='white', linewidth=0.5,
            )
            ylabel = '% Expression' if metric == 'expression_pct' else 'Mean Expression'

        # Styling (matches notebook pattern)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_linewidth(1.5)
        ax.spines['left'].set_linewidth(1.5)
        fs_lbl = max(9, int(10 * fs))
        ax.tick_params(axis='y', which='both', labelsize=fs_lbl, length=4, width=1.5)
        ax.tick_params(axis='x', which='both', length=4, width=1.5)
        ax.tick_params(axis='both', which='minor', length=2, width=1.5)
        ax.set_xticklabels(ax.get_xticklabels(), fontsize=fs_lbl,
                           rotation=45 if n_ct > 8 else 0, ha='right' if n_ct > 8 else 'center')
        ax.set_ylabel(ylabel, fontsize=max(11, int(12 * fs)), weight='bold')
        ax.set_title(gene, fontsize=max(11, int(12 * fs)), weight='bold')
        ax.set_xlabel(None)
        ax.grid(False)
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))

        # Legend
        handles = [plt.Rectangle((0, 0), 0, 0, color=palette[c], label=c)
                   for c in cond_order]
        ax.legend(handles=handles, bbox_to_anchor=(1.01, 0.5), loc='center left',
                  frameon=False, fontsize=max(9, int(10 * fs)), title=None)

        fig.tight_layout()

        # Encode to PNG base64
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.5, dpi=100,
                    facecolor='white', edgecolor='none')
        plt.close(fig)
        img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {'image': img_b64, 'width': fig_w, 'height': fig_h}

    except Exception as e:
        print(f'[GenSci] Plot generation error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


def _generate_celltype_composition(real_path: str, gene: str,
                                    palette_name: str = 'default',
                                    gene2: str = '') -> dict:
    """Generate stacked bar chart: among gene-positive cells, cell type proportions.
    If gene2 is provided, show co-expression breakdown: gene1+, gene1+gene2+, gene2+."""
    try:
        adata = get_adata(str(real_path))

        def find_gene_idx(g):
            idx_series = pd.Series(adata.var.index.astype(str))
            matches = idx_series.str.lower() == g.lower()
            if matches.any():
                return int(matches.values.nonzero()[0][0])
            for col in ['index', 'gene_ids', 'gene_symbols', 'feature_name']:
                if col in adata.var.columns:
                    matches = adata.var[col].astype(str).str.lower() == g.lower()
                    if matches.any():
                        return int(matches.values.nonzero()[0][0])
            return None

        g1_idx = find_gene_idx(gene)
        if g1_idx is None:
            return {'error': f'Gene "{gene}" not found'}

        ct_vals = adata.obs['CellType'].values
        # Read only the needed gene columns (avoid full matrix)
        g1_expr = adata[:, g1_idx].X
        g1_expr = np.asarray(g1_expr.toarray() if hasattr(g1_expr, 'toarray') else g1_expr).flatten()

        has_g2 = bool(gene2.strip())
        g2_expr = None
        if has_g2:
            g2_idx = find_gene_idx(gene2)
            if g2_idx is not None:
                g2_expr = adata[:, g2_idx].X
                g2_expr = np.asarray(g2_expr.toarray() if hasattr(g2_expr, 'toarray') else g2_expr).flatten()
        unique_ct = sorted(set(ct_vals))
        cat_colors, _ = get_palette(palette_name)
        palette = cat_colors[:len(unique_ct)] if len(cat_colors) >= len(unique_ct) else \
                  cat_colors * (len(unique_ct) // len(cat_colors) + 1)

        if has_g2 and g2_expr is not None:
            groups = [(f'{gene}+', g1_expr > 0),
                      (f'{gene}+_{gene2}+', (g1_expr > 0) & (g2_expr > 0)),
                      (f'{gene2}+', g2_expr > 0)]
            n_groups = 3
        else:
            groups = [(f'{gene}+', g1_expr > 0)]
            n_groups = 1

        # Compute cell type composition per group
        group_data = []  # list of {ct: count}
        for label, mask in groups:
            ct_counts = {}
            for ct in unique_ct:
                ct_mask = ct_vals == ct
                n_pos = int((mask & ct_mask).sum())
                ct_counts[ct] = n_pos
            group_data.append(ct_counts)

        # Plot vertical stacked bars
        fig, ax = plt.subplots(figsize=(max(3, n_groups * 2.8), 4.5))
        bar_width = 0.5
        x_positions = list(range(n_groups))
        bar_containers = []

        for gi, (label, _) in enumerate(groups):
            counts = group_data[gi]
            total = sum(counts.values())
            bottom = 0.0
            for ci, ct in enumerate(unique_ct):
                cnt = counts[ct]
                pct = cnt / total * 100 if total > 0 else 0
                color = palette[ci % len(palette)]
                bc = ax.bar(gi, pct, bar_width, bottom=bottom, color=color,
                            edgecolor='white', linewidth=0.5)
                if gi == 0:
                    bar_containers.append(bc)
                if pct >= 4:
                    ax.text(gi, bottom + pct/2, f'{pct:.1f}%',
                            ha='center', va='center', fontsize=7, fontweight='medium')
                bottom += pct

        ax.set_xticks(x_positions)
        ax.set_xticklabels([g[0] for g in groups], fontsize=9)
        ax.set_ylabel('% of Gene-Positive Cells', fontsize=10)
        ax.set_ylim(0, 100)
        ax.set_title('Cell Type Composition', fontsize=12, fontweight='bold', pad=8)
        # Legend on right side, auto columns based on count
        ncol = 1 if len(unique_ct) <= 8 else 2 if len(unique_ct) <= 20 else 3
        leg = ax.legend([b[0] for b in bar_containers], unique_ct,
                        fontsize=7, loc='center left',
                        bbox_to_anchor=(1.02, 0.5), ncol=ncol,
                        frameon=False)
        sns.despine()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white',
                    bbox_extra_artists=[leg])
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        buf.close()
        plt.close(fig)

        return {'image': f'data:image/png;base64,{b64}'}
    except Exception as e:
        print(f'[GenSci] Composition plot error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e)}


def _generate_cell_ratio_plot(real_path: str, condition_col: str = '',
                               palette_name: str = 'default') -> dict:
    """Generate cell type ratio plots: stacked bar per sample + hypothesis test boxplot.
    Returns base64 PNGs for both plots."""
    try:
        adata = get_adata(str(real_path))

        if 'Sample' not in adata.obs.columns or 'CellType' not in adata.obs.columns:
            return {'error': 'Required columns "Sample" and "CellType" not found in obs'}

        # Condition column
        cond_col = None
        if condition_col and condition_col != 'None' and condition_col in adata.obs.columns:
            cond_col = condition_col

        # Detect condition column - try common names
        if cond_col is None:
            for candidate in ['Group', 'Disease', 'Condition', 'disease', 'group']:
                if candidate in adata.obs.columns:
                    cond_col = candidate
                    break

        sample_vals = adata.obs['Sample'].values
        ct_vals = adata.obs['CellType'].values
        cond_vals = adata.obs[cond_col].values if cond_col else None
        # Compute cell type ratio per sample
        df = pd.DataFrame({
            'Sample': sample_vals, 'CellType': ct_vals,
            'Cond': cond_vals if cond_vals is not None else ['All'] * len(sample_vals),
        })
        # Pivot: CellType x Sample -> count
        pivot = df.pivot_table(index='CellType', columns='Sample', aggfunc='size', fill_value=0, observed=False)
        ratio = pivot / pivot.sum(axis=0)  # normalize to fractions

        # Order samples: disease -> control
        if cond_vals is not None:
            cond_map = df[['Sample', 'Cond']].drop_duplicates().set_index('Sample')['Cond'].to_dict()
            def sort_key(s):
                c = cond_map.get(s, '')
                is_ctrl = any(k in c.lower() for k in ('control', 'normal', 'healthy'))
                return (0 if is_ctrl else 1, s)
            sample_order = sorted(ratio.columns, key=sort_key)
        else:
            sample_order = sorted(ratio.columns)
        sample_order = [s for s in sample_order if s in ratio.columns]

        cell_types = sorted(ratio.index.tolist(), key=lambda x: -ratio.loc[x, sample_order].sum())
        n_ct = len(cell_types)
        cat_colors, cond_cfg = get_palette(palette_name)
        palette = cat_colors[:n_ct] if n_ct <= len(cat_colors) else ['#3b82f6'] * n_ct

        # Total cells per sample
        total_cells = pivot.sum(axis=0)

        # Plot 1: Stacked bar chart
        fig1, ax1 = plt.subplots(figsize=(max(6, len(sample_order) * 0.35), 5), dpi=100)

        bottom = np.zeros(len(sample_order))
        for i, ct in enumerate(cell_types):
            vals = ratio.loc[ct, sample_order].values
            ax1.bar(range(len(sample_order)), vals, bottom=bottom,
                    width=0.7, color=palette[i % len(palette)], label=ct)
            bottom += vals

        # Total cell count on top (adaptive font: fewer samples → larger)
        n_samp_bar = len(sample_order)
        top_fs = 14 if n_samp_bar <= 15 else (12 if n_samp_bar <= 30 else 10)
        for idx, s in enumerate(sample_order):
            total = int(total_cells.get(s, 0))
            ax1.text(idx, 1.02, str(total), ha='center', va='bottom',
                     fontsize=top_fs, fontweight='bold', color='black')

        # Percentage labels on segments > 3%
        for i, ct in enumerate(cell_types):
            vals = ratio.loc[ct, sample_order].values
            cum_bottom = np.zeros(len(sample_order))
            for j in range(i):
                cum_bottom += ratio.loc[cell_types[j], sample_order].values
            for idx, (v, cb) in enumerate(zip(vals, cum_bottom)):
                if v >= 0.03:
                    ax1.text(idx, cb + v / 2, f'{v:.0%}', ha='center', va='center',
                             fontsize=8, fontweight='bold', color='white')

        # Color x-axis labels by condition
        if cond_vals is not None:
            cond_to_color = {}
            all_conds = sorted(set(cond_vals), key=lambda c: 1 if any(k in c.lower() for k in ('control', 'normal', 'healthy')) else 0)
            for i, c in enumerate(all_conds):
                if any(k in c.lower() for k in ('control', 'normal', 'healthy')):
                    cond_to_color[c] = cond_cfg['control']
                else:
                    cond_to_color[c] = cond_cfg['disease'][i % len(cond_cfg['disease'])]

        ax1.set_xticks(range(len(sample_order)))
        ax1.set_xticklabels(sample_order, fontsize=8, fontweight='semibold', rotation=90)

        # Color x-axis labels by condition AFTER setting labels
        if cond_vals is not None:
            for idx, s in enumerate(sample_order):
                c = cond_map.get(s, '')
                color = cond_to_color.get(c, '#333')
                try:
                    ax1.get_xticklabels()[idx].set_color(color)
                except IndexError:
                    pass
        ax1.set_ylabel('Cells Ratio', fontsize=12, weight='bold')
        ax1.set_xlabel(None)
        ax1.set_ylim(0, 1.1)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['bottom'].set_linewidth(1.5)
        ax1.spines['left'].set_linewidth(1.5)
        ax1.tick_params(axis='y', which='both', labelsize=10, length=4, width=1.5)
        ax1.tick_params(axis='x', which='both', length=4, width=1.5)
        ax1.tick_params(axis='both', which='minor', length=2, width=1.5)
        ax1.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax1.grid(False)
        # Legend (inside the plot so it shows in the PNG at full size)
        ax1.legend(loc='upper left', frameon=True, framealpha=0.9, fancybox=True,
                   ncol=1, fontsize=11, markerscale=1.5)

        fig1.tight_layout()
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                     facecolor='white', edgecolor='none')
        plt.close(fig1)
        img1 = base64.b64encode(buf1.getvalue()).decode('utf-8')

        # Plot 2: Hypothesis test boxplot
        # Melt ratio data for seaborn
        ratio_long = ratio.reset_index().melt(id_vars='CellType', var_name='Sample', value_name='Ratio')
        if cond_vals is not None:
            ratio_long['Condition'] = ratio_long['Sample'].apply(lambda s: cond_map.get(s, 'Unknown'))
        else:
            ratio_long['Condition'] = 'All'

        cond_order = sorted(ratio_long['Condition'].unique(),
                            key=lambda c: 1 if any(k in c.lower() for k in ('control', 'normal', 'healthy')) else 0)
        ct_order = sorted(ratio_long['CellType'].unique())

        # Statistical test: each disease vs control
        control_conds = [c for c in cond_order if any(k in c.lower() for k in ('control', 'normal', 'healthy'))]
        disease_conds = [c for c in cond_order if c not in control_conds]

        sig_celltypes = set()
        if control_conds and disease_conds:
            control_val = control_conds[0]
            for ct in ct_order:
                ct_data = ratio_long[ratio_long['CellType'] == ct]
                ctrl_vals = ct_data[ct_data['Condition'] == control_val]['Ratio'].dropna()
                for dc in disease_conds:
                    dc_vals = ct_data[ct_data['Condition'] == dc]['Ratio'].dropna()
                    if len(ctrl_vals) >= 2 and len(dc_vals) >= 2:
                        try:
                            _, p = mannwhitneyu(dc_vals, ctrl_vals, alternative='greater')
                            if p <= 0.05:
                                sig_celltypes.add(ct)
                        except Exception:
                            pass

        fw2 = max(6, len(ct_order) * 0.5)
        fs2 = max(1.0, fw2 / 6.0)
        fig2, ax2 = plt.subplots(figsize=(fw2, 4), dpi=100)

        palette2 = build_cond_palette(cond_order, palette_name)

        sns.boxplot(data=ratio_long, x='CellType', y='Ratio', hue='Condition',
                    order=ct_order, hue_order=cond_order,
                    palette=palette2, ax=ax2,
                    showfliers=False, fill=False, linewidth=1.2)
        sns.stripplot(data=ratio_long, x='CellType', y='Ratio', hue='Condition',
                      order=ct_order, hue_order=cond_order,
                      palette=palette2, ax=ax2,
                      size=3, dodge=True, legend=False)

        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['bottom'].set_linewidth(1.5)
        ax2.spines['left'].set_linewidth(1.5)
        fs2_lbl = max(10, int(10 * fs2))
        ax2.tick_params(axis='y', which='both', labelsize=fs2_lbl, length=4, width=1.5)
        ax2.tick_params(axis='x', which='both', length=4, width=1.5)
        ax2.tick_params(axis='both', which='minor', length=2, width=1.5)
        ax2.set_xticklabels(ax2.get_xticklabels(), fontsize=fs2_lbl,
                            rotation=45 if len(ct_order) > 8 else 0,
                            ha='right' if len(ct_order) > 8 else 'center')
        ax2.set_ylabel('Cells Ratio', fontsize=max(12, int(12 * fs2)), weight='bold')
        ax2.set_xlabel(None)
        ax2.grid(False)
        ax2.yaxis.set_minor_locator(AutoMinorLocator(2))

        # Highlight significant cell types in red
        for tick in ax2.get_xticklabels():
            if tick.get_text() in sig_celltypes:
                tick.set_color('red')

        # Legend
        handles2 = [plt.Rectangle((0, 0), 0, 0, color=palette2[c], label=c)
                    for c in cond_order if c in palette2]
        ax2.legend(handles=handles2, bbox_to_anchor=(1.01, 0.5), loc='center left',
                   frameon=False, fontsize=max(10, int(9 * fs2)))

        fig2.tight_layout()
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                     facecolor='white', edgecolor='none')
        plt.close(fig2)
        img2 = base64.b64encode(buf2.getvalue()).decode('utf-8')

        return {'stacked_bar': img1, 'boxplot': img2,
                'n_cell_types': n_ct, 'n_samples': len(sample_order)}

    except Exception as e:
        print(f'[GenSci] Cell ratio plot error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


def _generate_umap_ratio_plots(real_path: str, group_var: str = '',
                                palette_name: str = 'default') -> dict:
    """Generate all ratio plots for the UMAP tab: heatmap, cell count bar,
    group boxplot, and stats table. Returns base64 PNGs + JSON stats."""
    try:
        adata = get_adata(str(real_path))

        if 'Sample' not in adata.obs.columns or 'CellType' not in adata.obs.columns:
            return {'error': 'Required columns "Sample" and "CellType" not found'}

        # Determine group variable
        if not group_var or group_var not in adata.obs.columns:
            for candidate in ['Group', 'Disease', 'Condition', 'disease', 'group']:
                if candidate in adata.obs.columns:
                    group_var = candidate
                    break
            else:
                group_var = ''

        # Get available group columns (categorical/object, exclude numeric/float)
        all_group_cols = []
        for col in adata.obs.columns:
            if col in ('Sample', 'CellType', 'Patient'):
                continue
            try:
                dtype = adata.obs[col].dtype
                # Skip numeric/float columns
                if dtype.name.startswith(('float', 'int', 'uint', 'complex', 'timedelta', 'datetime')):
                    continue
                # Only include columns with few unique values (categorical-like)
                if dtype.name in ('category', 'object', 'string', 'bool') or adata.obs[col].nunique() < 30:
                    all_group_cols.append(col)
            except Exception:
                pass

        sample_vals = adata.obs['Sample'].values
        ct_vals = adata.obs['CellType'].values
        group_vals = adata.obs[group_var].values if group_var else None

        unique_ct = sorted(set(str(x) for x in ct_vals))
        unique_samples = sorted(set(str(x) for x in sample_vals))
        # Pivot: CellType x Sample -> count
        df = pd.DataFrame({'Sample': sample_vals, 'CellType': ct_vals})
        pivot = df.pivot_table(index='CellType', columns='Sample', aggfunc='size', fill_value=0, observed=False)
        # Ensure all samples present
        for s in unique_samples:
            if s not in pivot.columns:
                pivot[s] = 0
        # Ensure all cell types present
        for ct in unique_ct:
            if ct not in pivot.index:
                pivot.loc[ct] = 0
        pivot = pivot[unique_samples].loc[unique_ct]
        ratio = pivot / pivot.sum(axis=0)

        # Map sample -> group
        if group_vals is not None:
            s_to_g = (pd.DataFrame({'Sample': sample_vals, 'Group': group_vals})
                      .drop_duplicates('Sample').set_index('Sample')['Group'].to_dict())
        else:
            s_to_g = {}

        # Order: group by condition, then by sample name within each group
        if s_to_g:
            # Determine group order: disease groups first, control last
            group_order = sorted(set(s_to_g.values()),
                                 key=lambda g: 1 if any(k in g.lower() for k in ('control', 'normal', 'healthy')) else 0)
            sample_order = sorted(unique_samples,
                                  key=lambda s: (group_order.index(s_to_g.get(s, 'Unknown')) if s_to_g.get(s, 'Unknown') in group_order else 99, s))
        else:
            sample_order = sorted(unique_samples)

        n_ct = len(unique_ct)

        # Colors
        if group_vals is not None:
            all_groups = sorted(set(str(x) for x in group_vals),
                                key=lambda g: 1 if any(k in g.lower() for k in ('control', 'normal', 'healthy')) else 0)
        else:
            all_groups = ['All']

        cat_pal, cond_cfg = get_palette(palette_name)
        group_colors = {}
        di = 0
        for g in all_groups:
            if any(k in g.lower() for k in ('control', 'normal', 'healthy')):
                group_colors[g] = cond_cfg['control']
            else:
                group_colors[g] = cond_cfg['disease'][di % len(cond_cfg['disease'])]
                di += 1

        sample_colors = [group_colors.get(s_to_g.get(s, ''), '#999') for s in sample_order]
        # Use same categorical palette as UMAP scatter plot
        celltype_colors = cat_pal

        # Plot 1: Stacked bar (Cell Type Ratio per Sample)
        total_per_sample = pivot[sample_order].sum(axis=0).values
        fw1 = max(8, len(sample_order) * 0.45 + n_ct * 0.25)
        fh1 = max(5.5, n_ct * 0.32)
        fs1 = max(1.0, fw1 / 12.0)
        dpi = 120
        fig1, ax1 = plt.subplots(figsize=(fw1, fh1), dpi=dpi)

        bottom = np.zeros(len(sample_order))
        for i, ct in enumerate(unique_ct):
            vals = ratio.loc[ct, sample_order].values
            ax1.bar(range(len(sample_order)), vals, bottom=bottom,
                    width=0.75, color=celltype_colors[i % len(celltype_colors)], label=ct,
                    linewidth=0.4, edgecolor='white')
            bottom += vals

        # Total cell count labels on top (y=1.02)
        n_samp_bar = len(sample_order)
        top_fs = 14 if n_samp_bar <= 15 else (12 if n_samp_bar <= 30 else 10)
        for idx, s in enumerate(sample_order):
            total = int(total_per_sample[idx])
            ax1.text(idx, 1.02, str(total), ha='center', va='bottom',
                     fontsize=top_fs, fontweight='bold', color='black')

        # Percentage labels on segments > 3%
        for i, ct in enumerate(unique_ct):
            vals = ratio.loc[ct, sample_order].values
            cum_bottom = np.zeros(len(sample_order))
            for j in range(i):
                cum_bottom += ratio.loc[unique_ct[j], sample_order].values
            for idx, (v, cb) in enumerate(zip(vals, cum_bottom)):
                if v >= 0.04:
                    ax1.text(idx, cb + v / 2, f'{v:.0%}', ha='center', va='center',
                             fontsize=max(6, int(6 * fs1)), fontweight='bold', color='white',
                             clip_on=True)

        ax1_lbl = max(9, int(10 * fs1))
        ax1.set_xticks(range(len(sample_order)))
        ax1.set_xticklabels(sample_order, fontsize=max(8, int(8 * fs1)), fontweight='semibold', rotation=90)
        ax1.set_ylabel('Cells Ratio', fontsize=max(11, int(12 * fs1)), weight='bold')
        ax1.set_xlabel(None)
        ax1.set_ylim(0, 1.12)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['bottom'].set_linewidth(1.2)
        ax1.spines['left'].set_linewidth(1.2)
        ax1.tick_params(axis='y', which='both', labelsize=ax1_lbl, length=3, width=1.2)
        ax1.tick_params(axis='x', which='both', length=3, width=1.2)
        ax1.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax1.grid(False)
        # Remove x-axis padding (bars start/end at edges)
        ax1.set_xlim(-0.5, len(sample_order) - 0.5)

        # Color x-axis labels by condition
        if group_vals is not None:
            for idx, s in enumerate(sample_order):
                c = s_to_g.get(s, '')
                color = group_colors.get(c, '#333')
                try:
                    ax1.get_xticklabels()[idx].set_color(color)
                except IndexError:
                    pass

        fig1.tight_layout()
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format='png', bbox_inches='tight', pad_inches=0.5, dpi=dpi,
                     facecolor='white', edgecolor='none')
        plt.close(fig1)
        stacked_bar_b64 = base64.b64encode(buf1.getvalue()).decode('utf-8')

        # Plot 2: Cell count heatmap (Sample x CellType)
        count_matrix = pivot[sample_order].astype(int)
        ratio_matrix = ratio[sample_order]
        n_samp = len(sample_order)
        n_ct_h = len(unique_ct)
        n_total = count_matrix.size
        n_low = (count_matrix.values <= 10).sum()
        low_pct = round(n_low / n_total * 100, 1) if n_total > 0 else 0.0

        heat_w = max(6, min(n_samp * 0.35, 18))
        heat_h = max(4, min(n_ct_h * 0.4, 12))
        sample_color_series = pd.Series(
            [group_colors.get(s_to_g.get(s, ''), '#999') for s in sample_order],
            index=sample_order
        )
        g = sns.clustermap(
            ratio_matrix,
            annot=count_matrix.values,
            fmt='d',
            cmap='Blues',
            linewidths=0.5,
            linecolor='white',
            figsize=(heat_w, heat_h),
            row_cluster=False,
            col_cluster=False,
            annot_kws={"fontsize": 5, "fontweight": "semibold"},
            cbar_kws={'shrink': 0.5, 'pad': 0.02},
            cbar_pos=[1.01, 0.4, 0.02, 0.2],
            col_colors=sample_color_series,
            yticklabels=True,
            xticklabels=True,
        )
        g.ax_heatmap.set_xticklabels(g.ax_heatmap.get_xmajorticklabels(),
                                       fontsize=6, fontweight='semibold', rotation=90)
        g.ax_heatmap.set_yticklabels(g.ax_heatmap.get_ymajorticklabels(),
                                       fontsize=6, fontweight='semibold')
        g.ax_heatmap.set(xlabel=None, ylabel=None)

        # Highlight cells <= 10 in red
        for text in g.ax_heatmap.texts:
            t = text.get_text()
            if t:
                try:
                    if int(t) <= 10:
                        text.set_color('red')
                        text.set_fontweight('bold')
                except ValueError:
                    continue

        # Condition legend (on the col_colors bar itself)
        patches = [mpatches.Patch(color=gc, label=gn)
                   for gn, gc in group_colors.items() if gn in s_to_g.values()]
        if patches:
            try:
                n_patches = len(patches)
                ncol = min(n_patches, max(3, n_patches // 2 + 1))
                if hasattr(g, 'ax_col_colors') and g.ax_col_colors:
                    g.ax_col_colors.legend(handles=patches,
                        fontsize=7, frameon=False,
                        ncol=ncol,
                        loc='lower left', bbox_to_anchor=(0, 1.5),
                        handlelength=1.2)
                else:
                    g.ax_heatmap.legend(handles=patches,
                        fontsize=7, frameon=False,
                        ncol=ncol, loc='upper right',
                        handlelength=1.2)
            except Exception:
                pass
        buf2 = io.BytesIO()
        g.savefig(buf2, format='png', bbox_inches='tight', pad_inches=0.3, dpi=120,
                  facecolor='white', edgecolor='none')
        plt.close(g.fig)
        cellcount_b64 = base64.b64encode(buf2.getvalue()).decode('utf-8')

        # Plot 3: Group boxplot
        ratio_long = ratio[sample_order].reset_index().melt(
            id_vars='CellType', var_name='Sample', value_name='Ratio')
        ratio_long['Group'] = ratio_long['Sample'].apply(lambda s: s_to_g.get(s, 'Unknown'))

        group_order = sorted(ratio_long['Group'].unique(),
                             key=lambda g: 1 if any(k in g.lower() for k in ('control', 'normal', 'healthy')) else 0)

        n_groups = len(group_order)
        fw3 = max(12, n_ct * 1.0 + n_groups * 0.6)
        fh3 = max(5.5, n_ct * 0.32)
        fs3 = max(1.0, fw3 / 12.0)
        fig3, ax3 = plt.subplots(figsize=(fw3, fh3), dpi=100)
        box_palette = {g: group_colors.get(g, '#999') for g in group_order}
        sns.boxplot(data=ratio_long, x='CellType', y='Ratio', hue='Group',
                    order=unique_ct, hue_order=group_order,
                    palette=box_palette, ax=ax3,
                    showfliers=False, fill=False, linewidth=1.2)
        sns.stripplot(data=ratio_long, x='CellType', y='Ratio', hue='Group',
                      order=unique_ct, hue_order=group_order,
                      palette=box_palette, ax=ax3,
                      size=2, dodge=True, legend=False)
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.spines['bottom'].set_linewidth(1.5)
        ax3.spines['left'].set_linewidth(1.5)
        fs3_lbl = max(9, int(10 * fs3))
        ax3.tick_params(axis='y', which='both', labelsize=fs3_lbl, length=4, width=1.5)
        ax3.tick_params(axis='x', which='both', length=4, width=1.5)
        ax3.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax3.set_xticklabels(ax3.get_xticklabels(), fontsize=max(8, int(9 * fs3)),
                            rotation=45 if n_ct > 8 else 0,
                            ha='right' if n_ct > 8 else 'center')
        ax3.set_ylabel('Cells Ratio', fontsize=max(11, int(12 * fs3)), weight='bold')
        ax3.set_xlabel(None)
        ax3.grid(False)
        hp = [plt.Rectangle((0, 0), 0, 0, color=box_palette[g], label=g) for g in group_order if g in box_palette]
        ax3.legend(handles=hp, bbox_to_anchor=(1.01, 0.5), loc='center left',
                   frameon=False, fontsize=max(8, int(9 * fs3)))
        fig3.tight_layout()
        buf3 = io.BytesIO()
        fig3.savefig(buf3, format='png', bbox_inches='tight', pad_inches=0.3, dpi=100,
                     facecolor='white', edgecolor='none')
        plt.close(fig3)
        boxplot_b64 = base64.b64encode(buf3.getvalue()).decode('utf-8')

        # Pairwise stats: Mann-Whitney U for every group pair x cell type
        group_pairs = list(itertools.combinations(group_order, 2))
        pair_labels = [f'{a}_vs_{b}' for a, b in group_pairs]
        pairwise = {'pairs': pair_labels, 'cell_types': unique_ct, 'matrix': []}

        for a, b in group_pairs:
            row_pvals = []
            for ct in unique_ct:
                ct_data = ratio_long[ratio_long['CellType'] == ct]
                vals_a = ct_data[ct_data['Group'] == a]['Ratio'].dropna()
                vals_b = ct_data[ct_data['Group'] == b]['Ratio'].dropna()
                if len(vals_a) >= 2 and len(vals_b) >= 2:
                    try:
                        _, p = mannwhitneyu(vals_a, vals_b, alternative='two-sided')
                        row_pvals.append(round(float(p), 6))
                    except Exception:
                        row_pvals.append(None)
                else:
                    row_pvals.append(None)
            pairwise['matrix'].append(row_pvals)

        return {
            'stacked_bar': stacked_bar_b64,
            'cell_count_bar': cellcount_b64,
            'ratio_boxplot': boxplot_b64,
            'pairwise': pairwise,
            'n_cell_types': n_ct,
            'n_samples': len(sample_order),
            'low_cell_pct': round(low_pct, 1),
            'available_group_cols': all_group_cols,
        }

    except Exception as e:
        print(f'[GenSci] UMAP ratio plots error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}


def _generate_marker_dotplot(real_path: str, palette_name: str = 'default',
                              group_filter: str = '', genes: str = '') -> dict:
    """Generate scanpy dotplot for marker genes.

    - Manual datasets: Major marker dict + Target genes merged
    - Non-Manual datasets: Target genes only
    - Target genes: genes param > annotation['Target'] > TARGET_DEFAULT

    Args:
        real_path: symlink path to the .h5ad file
        palette_name: palette name for the plot
        group_filter: Group value to subset (empty = all cells)
        genes: comma-separated Target genes (overrides annotation Target)

    Returns:
        {image, width, height, groups, error?}
    """
    import json as _json
    from pathlib import Path as _Path

    TARGET_DEFAULT = ['IL1A', 'MUC5AC', 'PDCD1', 'CD274', 'IGF1', 'IL1RAP', 'ANGPTL3']

    def _load_sources() -> dict:
        """Load annotation_sources.json (inline, no scanner dependency)."""
        sources_file = _Path(__file__).resolve().parent.parent / 'annotation_sources.json'
        try:
            return _json.loads(sources_file.read_text())
        except Exception:
            return {}

    try:
        # Use unified backed access with per-file lock to prevent dual-handle HDF5
        # conflicts. All lookups and subsetting happen inside the lock; the
        # materialised AnnData is then safe for heavy computation outside.
        with locked_backed_adata(str(real_path)) as adata:
            # Extract PMID from path to look up annotation entry
            path = _Path(real_path)
            fname = path.stem
            pmid = fname.split('.')[0].split('_')[0] if '_' in fname else fname.split('.')[0]

            sources = _load_sources()
            entry = sources.get(pmid, {})
            if isinstance(entry, str):
                entry = {}
            marker_major = entry.get('Major')

            # Determine Target genes: user input > annotation Target > default
            if genes.strip():
                target_genes = [g.strip() for g in genes.split(',') if g.strip()]
            else:
                target_genes = entry.get('Target', TARGET_DEFAULT)

            if not marker_major and not target_genes:
                return {'error': 'No marker genes or Target genes available for this dataset'}

            # Get available groups BEFORE subsetting (for frontend dropdown)
            groups = []
            if 'Group' in adata.obs.columns:
                groups = sorted(set(str(g) for g in adata.obs['Group'].unique()))

            # Build plot_dict from var_names (in memory even with backed mode)
            var_names = set(str(n).upper() for n in adata.var_names)
            plot_dict = {}

            if marker_major:
                for ct, ct_genes in marker_major.items():
                    present = [g for g in ct_genes if g.upper() in var_names]
                    if present:
                        plot_dict[ct] = present

            target_present = [g for g in target_genes if g.upper() in var_names]
            if target_present:
                plot_dict['Target'] = target_present

            if not plot_dict:
                return {'error': 'None of the marker/Target genes found in this dataset'}

            if 'CellType' not in adata.obs.columns:
                return {'error': 'CellType column not found in obs'}

            # Materialise only needed gene columns (not full X) to minimise lock time
            needed_genes = list(set(g for genes in plot_dict.values() for g in genes))

            if group_filter and 'Group' in adata.obs.columns:
                mask = adata.obs['Group'].astype(str) == group_filter
                if mask.sum() == 0:
                    return {'error': f'No cells found for Group="{group_filter}"'}
                adata = adata[mask, needed_genes].to_memory()
            else:
                adata = adata[:, needed_genes].to_memory()
        # Lock released — adata is now an in-memory AnnData, no HDF5 access below

        # Generate dotplot — scanpy ≥1.10 returns Axes dict with return_fig=True
        sc.settings.figdir = '/tmp'
        result = sc.pl.dotplot(
            adata, plot_dict, groupby='CellType',
            standard_scale='var', dot_max=1, return_fig=True,
            show=False, use_raw=False,
        )

        # scanpy ≥1.10 returns DotPlot object (fig is None until make_figure())
        if hasattr(result, 'make_figure'):
            result.make_figure()
            fig = result.fig

            # Annotate Y-axis with cell counts and proportions
            CellNumber = pd.DataFrame(adata.obs['CellType'].value_counts())
            CellNumber.columns = ['CellType']
            CellNumber['Total'] = CellNumber['CellType'].sum()
            CellNumber['Ratio'] = CellNumber['CellType'] / CellNumber['Total'] * 100
            result.get_axes()['mainplot_ax'].set_yticklabels([
                i.get_text() + ' (%d/%d %.2f%%) ' % (CellNumber.loc[i.get_text(), 'CellType'],
                                                     CellNumber.loc[i.get_text(), 'Total'],
                                                     CellNumber.loc[i.get_text(), 'Ratio'])
                for i in result.get_axes()['mainplot_ax'].get_yticklabels()
            ], fontsize=12, weight='bold')
        elif hasattr(result, 'fig') and result.fig is not None:
            fig = result.fig
        elif hasattr(result, 'figure'):
            fig = result.figure
        elif isinstance(result, dict):
            first_ax = next(iter(result.values()))
            fig = first_ax.figure if hasattr(first_ax, 'figure') else first_ax
        elif hasattr(result, 'savefig'):
            fig = result
        else:
            fig = plt.gcf()

        # Encode to PNG base64
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.5, dpi=120,
                    facecolor='white', edgecolor='none')
        plt.close(fig)
        img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        fig_w, fig_h = fig.get_size_inches()
        return {'image': img_b64, 'width': round(fig_w, 1), 'height': round(fig_h, 1),
                'groups': groups}

    except Exception as e:
        print(f'[GenSci] Marker dotplot error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e) + '\n' + traceback.format_exc()}
