#!/usr/bin/env python3
"""UMAP data extraction from .h5ad files."""

import sys
from pathlib import Path

import numpy as np
import anndata

def _get_umap_data(real_path: Path, color_by: str = 'CellType',
                   max_points: int = 50000, gene: str = '',
                   palette_name: str = 'default',
                   gene2: str = '') -> dict:
    """Read UMAP coordinates + obs annotations for scatter plot coloring.

    Supports categorical coloring (by obs column) or continuous (by gene expression),
    as well as dual-gene RGB overlay when both gene and gene2 are provided.
    """
    try:
        adata = anndata.read_h5ad(str(real_path), backed='r')
        n_cells = adata.n_obs

        if 'X_umap' not in adata.obsm:
            adata.file.close()
            return {'error': 'No X_umap in obsm'}

        umap = adata.obsm['X_umap']
        step = max(1, n_cells // max_points)
        indices = range(0, n_cells, step)

        # Build points array
        points = [[float(umap[i, 0]), float(umap[i, 1])] for i in indices]

        colors_hex = []
        legend = []
        color_type = 'categorical'

        if color_by == 'Gene' and gene:
            var_names = adata.var_names

            def _resolve_gene(query: str) -> tuple[int, str]:
                idx = -1
                name = query
                for i, n in enumerate(var_names):
                    if n.lower() == query.lower():
                        idx = i; name = str(n); break
                if idx < 0:
                    for i, n in enumerate(var_names):
                        if query.lower() in n.lower():
                            idx = i; name = str(n); break
                return idx, name

            gene1_idx, gene1_name = _resolve_gene(gene)

            # ─── Single gene mode ───────────────────────────────
            if gene1_idx >= 0 and not gene2:
                color_type = 'continuous'
                X = adata.X
                col = X[:, gene1_idx]
                gene_expr = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
                points = []
                sampled_expr_vals = []
                for i in indices:
                    v = float(gene_expr[i])
                    points.append([float(umap[i, 0]), float(umap[i, 1]), v])
                    sampled_expr_vals.append(v)
                min_val = min(sampled_expr_vals) if sampled_expr_vals else 0
                max_val = max(sampled_expr_vals) if sampled_expr_vals else 1
                legend = [{"name": gene1_name, "min": round(min_val, 4), "max": round(max_val, 4)}]

                # Generate per-point hex colors matching the frontend gradient legend
                range_val = max_val - min_val if max_val > min_val else 1
                # Colors matching frontend gradient: #fff5f0→#fee0d2→#fc9272→#de2d26→#a50f15
                _gradient = [
                    (0xff, 0xf5, 0xf0), (0xfe, 0xe0, 0xd2), (0xfc, 0x92, 0x72),
                    (0xde, 0x2d, 0x26), (0xa5, 0x0f, 0x15),
                ]
                colors_hex = []
                for v in sampled_expr_vals:
                    t = (v - min_val) / range_val
                    t = max(0.0, min(1.0, t))
                    pos = t * (len(_gradient) - 1)
                    lo, hi = int(pos), min(int(pos) + 1, len(_gradient) - 1)
                    frac = pos - lo
                    r = int(_gradient[lo][0] + (_gradient[hi][0] - _gradient[lo][0]) * frac)
                    g = int(_gradient[lo][1] + (_gradient[hi][1] - _gradient[lo][1]) * frac)
                    b = int(_gradient[lo][2] + (_gradient[hi][2] - _gradient[lo][2]) * frac)
                    colors_hex.append(f'#{r:02x}{g:02x}{b:02x}')

            # ─── Dual-gene RGB overlay mode ─────────────────────
            elif gene1_idx >= 0 and gene2:
                gene2_idx, gene2_name = _resolve_gene(gene2)
                if gene2_idx >= 0:
                    color_type = 'dual_gene'
                    X = adata.X
                    col1 = X[:, gene1_idx]
                    col2 = X[:, gene2_idx]
                    expr1 = col1.toarray().flatten() if hasattr(col1, 'toarray') else np.array(col1).flatten()
                    expr2 = col2.toarray().flatten() if hasattr(col2, 'toarray') else np.array(col2).flatten()

                    # Compute per-gene max for normalization
                    sampled1 = [float(expr1[i]) for i in indices]
                    sampled2 = [float(expr2[i]) for i in indices]
                    max_g1 = max(sampled1) if sampled1 else 1
                    max_g2 = max(sampled2) if sampled2 else 1

                    points = []
                    colors_hex = []

                    # Build Seurat-style 10×10 BlendMatrix lookup table
                    # Colors: lightgrey → pure red/green/yellow
                    _neg_col = (211, 211, 211)  # lightgrey
                    _g1_col = (255, 0, 0)       # pure red
                    _g2_col = (0, 255, 0)       # pure green
                    _g_size = 10
                    _blend_matrix = []
                    for gi in range(_g_size):   # Gene2 (row)
                        row = []
                        for gj in range(_g_size):  # Gene1 (col)
                            t1 = gj / (_g_size - 1)
                            t2 = gi / (_g_size - 1)
                            mx = max(t1, t2)
                            if mx < 1e-6:
                                rr, gg, bb = _neg_col
                            else:
                                w1 = t1 / mx
                                w2 = t2 / mx
                                rr = int(_neg_col[0] + (_g1_col[0] * w1 + _g2_col[0] * w2 - _neg_col[0]) * mx)
                                gg = int(_neg_col[1] + (_g1_col[1] * w1 + _g2_col[1] * w2 - _neg_col[1]) * mx)
                                bb = int(_neg_col[2] + (_g1_col[2] * w1 + _g2_col[2] * w2 - _neg_col[2]) * mx)
                            row.append((min(255, rr), min(255, gg), min(255, bb)))
                        _blend_matrix.append(row)

                    for i in indices:
                        v1 = float(expr1[i])
                        v2 = float(expr2[i])
                        points.append([float(umap[i, 0]), float(umap[i, 1]), v1, v2])
                        r_norm = min(1.0, v1 / max_g1) if max_g1 > 0 else 0.0
                        g_norm = min(1.0, v2 / max_g2) if max_g2 > 0 else 0.0
                        idx1 = min(_g_size - 1, int(r_norm * _g_size * 0.999))
                        idx2 = min(_g_size - 1, int(g_norm * _g_size * 0.999))
                        r, g, b = _blend_matrix[idx2][idx1]
                        colors_hex.append(f'#{r:02x}{g:02x}{b:02x}')

                    legend = [
                        {"name": gene1_name, "color": "#ff0000",
                         "min": round(min(sampled1), 4), "max": round(max(sampled1), 4)},
                        {"name": gene2_name, "color": "#00ff00",
                         "min": round(min(sampled2), 4), "max": round(max(sampled2), 4)},
                    ]
        elif color_by in adata.obs.columns:
            # Categorical coloring by obs column
            from collections import Counter
            from analysis.utils import CATEGORICAL_PALETTE_MAP
            vals = adata.obs[color_by].values
            label_counts = Counter(str(v) for v in vals)
            unique_labels = sorted(label_counts.keys())

            palette = CATEGORICAL_PALETTE_MAP.get(palette_name, CATEGORICAL_PALETTE_MAP['default'])
            label_to_color = {}
            for j, lbl in enumerate(unique_labels):
                c = palette[j % len(palette)]
                label_to_color[lbl] = c
                legend.append({'name': lbl, 'color': c, 'count': label_counts[lbl]})

            sampled_vals = [str(vals[i]) for i in indices]
            colors_hex = [label_to_color.get(v, '#999999') for v in sampled_vals]

        adata.file.close()
        return {
            'points': points,
            'colors': colors_hex,
            'legend': legend,
            'color_type': color_type,
            'n_cells': n_cells,
            'sampled': step > 1,
            'sample_step': step,
        }
    except Exception as e:
        print(f'[GenSci] UMAP data error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'error': str(e)}
