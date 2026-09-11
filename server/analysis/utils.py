#!/usr/bin/env python3
"""Shared utility functions for analysis modules."""

import numpy as np


# Maximally-distinguishable categorical palette (glasbey-like)
CATEGORICAL_PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#f58231', '#911eb4', '#42d4f5', '#f032e6', '#bfef45',
    '#fabed4', '#469990', '#dcbeff', '#9A6324', '#fffac8',
    '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075',
    '#a9a9a9', '#ff6f61', '#6b5b95', '#88b04b', '#f7cac9',
    '#92a8d1', '#f4a460', '#b565a7', '#b0c4de', '#3cb371',
    '#fa8072', '#20b2aa', '#778899', '#b0e0e6', '#c71585',
]

# ─── Named Palettes ───────────────────────────────────────────

PALETTE_DEFAULT = CATEGORICAL_PALETTE  # 40-color glasbey-like

PALETTE_PASTEL = [
    '#fbb4ae', '#b3cde3', '#ccebc5', '#decbe4', '#fed9a6',
    '#ffffcc', '#e5d8bd', '#fddaec', '#f2f2f2', '#b3e2cd',
    '#fdcdac', '#cbd5e8', '#f4cae4', '#e6f5c9', '#fff2ae',
    '#f1e2cc', '#cccccc', '#e5d0e0', '#b3d9d9', '#fad1b3',
    '#d5b8d5', '#b8d5b8', '#d5d5b8', '#f0d0d0', '#c0e0d0',
    '#d0c0e0', '#e0d0c0', '#c0d0e0', '#e0c0d0', '#d0e0c0',
]

PALETTE_BOLD = [
    '#FF0018', '#00A800', '#0057FF', '#FFA500', '#9400D3',
    '#FF69B4', '#00CED1', '#FFD700', '#32CD32', '#FF4500',
    '#4169E1', '#8B008B', '#00FA9A', '#FF6347', '#1E90FF',
    '#ADFF2F', '#FF1493', '#7CFC00', '#00BFFF', '#FF00FF',
    '#20B2AA', '#F0E68C', '#6A5ACD', '#FF8C00', '#00FF7F',
    '#DC143C', '#0000FF', '#8FBC8F', '#FFDAB9', '#00FFFF',
]

PALETTE_NATURE = [
    '#3B4992', '#EE0000', '#008B45', '#631879', '#008280',
    '#BB0021', '#5F559B', '#A20056', '#808080', '#1B809E',
    '#E68A00', '#006837', '#C51B7D', '#7F3C8D', '#001F5B',
    '#E41A1C', '#377EB8', '#4DAF4A', '#984EA3', '#FF7F00',
]

PALETTE_TAB10 = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]

CATEGORICAL_PALETTE_MAP = {
    'default': PALETTE_DEFAULT,
    'pastel':  PALETTE_PASTEL,
    'bold':    PALETTE_BOLD,
    'nature':  PALETTE_NATURE,
    'tab10':   PALETTE_TAB10,
}

# Condition color palettes
COND_PALETTES = {
    'default': {
        'control': '#3b82f6',
        'disease': ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#a65628', '#f781bf', '#999999'],
    },
    'pastel': {
        'control': '#89CFF0',
        'disease': ['#fbb4ae', '#b3cde3', '#ccebc5', '#decbe4', '#fed9a6', '#ffffcc', '#fddaec', '#e5d8bd'],
    },
    'bold': {
        'control': '#0057FF',
        'disease': ['#FF0018', '#00A800', '#FFA500', '#9400D3', '#FF69B4', '#00CED1', '#FFD700', '#32CD32'],
    },
    'nature': {
        'control': '#008280',
        'disease': ['#EE0000', '#3B4992', '#008B45', '#631879', '#BB0021', '#5F559B', '#A20056', '#1B809E'],
    },
    'tab10': {
        'control': '#1f77b4',
        'disease': ['#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22'],
    },
}


def get_palette(name: str = 'default'):
    """Return (categorical_colors, condition_palette_config) for given name."""
    cat = CATEGORICAL_PALETTE_MAP.get(name, PALETTE_DEFAULT)
    cond = COND_PALETTES.get(name, COND_PALETTES['default'])
    return cat, cond


def build_cond_palette(conditions: list[str], palette_name: str = 'default') -> dict[str, str]:
    """Assign distinct colors to conditions sequentially."""
    _, cond = get_palette(palette_name)
    palette = {}
    idx = 0
    for c in conditions:
        if any(k in c.lower() for k in ('control', 'normal', 'healthy')):
            palette[c] = cond['control']
        else:
            palette[c] = cond['disease'][idx % len(cond['disease'])]
            idx += 1
    return palette


def resolve_gene_indices(var_names, genes: list[str]) -> list[tuple[int, str]]:
    """Unified gene name resolution: exact match first, then partial.

    Returns list of (index, actual_name) tuples. Invalid genes get index -1.
    """
    results = []
    for g in genes:
        idx = -1
        actual = g
        # Exact match first
        for i, n in enumerate(var_names):
            if n.lower() == g.lower():
                idx = i
                actual = str(n)
                break
        if idx < 0:
            # Partial match fallback
            partial = [n for n in var_names if g.lower() in n.lower()]
            if partial:
                idx = list(var_names).index(partial[0])
                actual = str(var_names[idx])
        results.append((idx, actual))
    return results


def in_memory_matrix(X):
    """Return an X that slices on either axis without touching HDF5 again.

    `adata.X` in backed mode is a lazy `_CSRDataset`, not an array. Its fast path
    needs a *slice* on the cell axis (anndata's `is_sparse_indexing_overridden`); a
    column index is not a slice, so `X[:, i]` falls through to `to_memory()`, which
    reads the whole matrix off disk — 934 MB on a 174k-cell dataset. Reading K
    columns the naive way therefore reads that same matrix K times.

    Materialising once and slicing in memory costs nothing at K=1 (measured 1.01x)
    and wins from K=2 on. Measured on the Monkey 174k-cell dataset, 2026-09-11:
    K=2 → 1.55x, K=3 → 1.88x, K=5 → 2.23x, K=7 → 2.45x.

    Not backed (already a real matrix) → returned as-is.
    """
    return X.to_memory() if hasattr(X, 'to_memory') else X


def extract_gene_columns(X, indices) -> dict:
    """Dense 1-D expression vector per gene index, reading the matrix at most once.

    Returns {index: np.ndarray}. Keyed by index, so a gene asked for twice reads its
    column once. Negative indices (the "unresolved gene" marker) are skipped.
    """
    wanted = sorted({int(i) for i in indices if i is not None and i >= 0})
    if not wanted:
        return {}
    source = in_memory_matrix(X)
    out = {}
    for gi in wanted:
        col = source[:, gi]
        out[gi] = col.toarray().flatten() if hasattr(col, 'toarray') else np.array(col).flatten()
    return out


def normalize_gene2_op(op: str | None) -> str:
    """Normalise a Merge-gene combine operator to 'or' (union) or 'and' (intersection).

    Anything unrecognised — None, empty, 'AND ' — falls back to 'or', preserving
    the historical union behaviour for old clients that never send the param.
    """
    return 'and' if str(op or '').strip().lower() == 'and' else 'or'


def merge_op_separator(op: str | None) -> str:
    """Label separator for a merge set — '&' for intersection, '|' for union.

    Single source of truth so a label separator can never drift from the operator
    that actually produced the mask.
    """
    return '&' if normalize_gene2_op(op) == 'and' else '|'


def reduce_bool_masks(masks: list, op: str = 'or') -> np.ndarray | None:
    """Combine per-member boolean masks into the synthetic merge gene 'M'.

    'or'  → union: M=1 when ANY member is positive (historical behaviour).
    'and' → intersection: M=1 only when EVERY member is positive.
    Returns None when nothing resolved, so callers can tell 'no members' from
    'members but none positive'.

    `op` is normalised here so the helper is safe to call directly with a raw
    query value rather than only via `normalize_gene2_op`. The result is always a
    fresh array — callers never receive (and cannot mutate) one of their inputs.
    """
    if not masks:
        return None
    op = normalize_gene2_op(op)
    acc = masks[0]
    for m in masks[1:]:
        acc = (acc & m) if op == 'and' else (acc | m)
    return acc.copy()


def resolve_group_column(adata, group_col: str = 'Group') -> str:
    """Fallback chain: Group -> Disease -> Condition -> Diagnosis."""
    if group_col and group_col in adata.obs.columns:
        return group_col
    for c in ('Group', 'Disease', 'Condition', 'Diagnosis'):
        if c in adata.obs.columns:
            return c
    return ''


def cond_sort_key(name: str) -> tuple:
    """Sort: non-control first, control last. Secondary: alphabetically."""
    ln = name.lower()
    is_ctrl = any(k in ln for k in ('control', 'normal', 'healthy'))
    return (1 if is_ctrl else 0, name)
