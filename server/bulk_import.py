#!/usr/bin/env python3
"""Bulk RNA multi-format importer (txt / csv / tsv / xlsx) → cached .h5ad.

The scanner discovers raw bulk tables on disk but never parses them on the
request path. This module converts a raw table into a column-oriented AnnData
cache once, so downstream analysis (boxplot, differential expression) reads
from a fast .h5ad instead of re-parsing a multi-GB text file.

Column convention (see config.BULK_META_COLUMNS):
  - First column  → sample name (obs index + obs['Sample'])
  - Columns named Disease/Group/Patient/Label/Tumor/… → sample metadata (obs)
  - Everything else → gene expression matrix (var_names + X)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import anndata

from config import BULK_META_COLUMNS


def detect_separator(path: Path) -> str:
    """Return the delimiter for a text table (tab vs comma).

    Sniffs the first data line rather than trusting the extension, so a
    comma-delimited `.txt` still imports correctly.
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        f.readline()  # skip header
        line = f.readline()
    tabs = line.count('\t')
    commas = line.count(',')
    return '\t' if tabs >= commas else ','


def _read_frame(src: Path, sep: str) -> pd.DataFrame:
    """Read the raw table once with the first column promoted to index."""
    if src.suffix.lower() == '.xlsx':
        return pd.read_excel(src, index_col=0)
    return pd.read_csv(src, sep=sep, index_col=0, low_memory=False)


def _split_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Partition columns into metadata (obs) and gene (var) sets."""
    meta_cols = [c for c in df.columns if str(c) in BULK_META_COLUMNS]
    gene_cols = [c for c in df.columns if str(c) not in BULK_META_COLUMNS]
    return meta_cols, gene_cols


def import_bulk_table(src: Path, dst_h5ad: Path) -> dict:
    """Convert a raw bulk table into an AnnData cache at dst_h5ad.

    Returns summary metadata for the scanner to store on the dataset entry.
    Raises on failure — the caller (scanner) logs and leaves status importing.
    """
    sep = detect_separator(src)
    df = _read_frame(src, sep)
    meta_cols, gene_cols = _split_columns(df)

    if not gene_cols:
        raise ValueError(f'No gene columns detected in {src.name} '
                         f'(only metadata: {meta_cols})')

    # Sample names from the (former) first column — now the index.
    samples = [str(s) for s in df.index]
    if len(set(samples)) != len(samples):
        # De-duplicate to keep AnnData happy; keep original order.
        seen: dict[str, int] = {}
        unique: list[str] = []
        for s in samples:
            n = seen.get(s, 0)
            seen[s] = n + 1
            unique.append(s if n == 0 else f'{s}__{n}')
        samples = unique

    # Expression matrix as float32 (column-stored, ~0.9 GB for 11k×20k).
    X = df[gene_cols].to_numpy(dtype=np.float32)

    # Sample metadata (obs) — copy before assigning Sample to avoid churn.
    obs = df[meta_cols].copy() if meta_cols else pd.DataFrame(index=df.index)
    obs['Sample'] = samples
    obs.index = samples

    # Gene names (var) — de-duplicate.
    gene_names = [str(g) for g in gene_cols]
    if len(set(gene_names)) != len(gene_names):
        seen_g: dict[str, int] = {}
        unique_g: list[str] = []
        for g in gene_names:
            n = seen_g.get(g, 0)
            seen_g[g] = n + 1
            unique_g.append(g if n == 0 else f'{g}__{n}')
        gene_names = unique_g

    var = pd.DataFrame(index=gene_names)

    adata = anndata.AnnData(X=X, obs=obs, var=var)
    dst_h5ad.parent.mkdir(parents=True, exist_ok=True)
    adata.write_h5ad(str(dst_h5ad))

    # Summary for the scanner's dataset metadata.
    disease_count = 0
    if 'Disease' in obs.columns:
        disease_count = int(obs['Disease'].nunique())
    group_dist = ''
    if 'Group' in obs.columns:
        counts = obs['Group'].value_counts()
        group_dist = ', '.join(f'{g} {int(c)}' for g, c in counts.items())

    return {
        'n_obs': int(adata.n_obs),
        'n_vars': int(adata.n_vars),
        'disease_count': disease_count,
        'group_dist': group_dist,
    }


if __name__ == '__main__':
    # CLI smoke-test: python3 bulk_import.py <src> <dst.h5ad>
    src_path = Path(sys.argv[1])
    dst_path = Path(sys.argv[2])
    print(import_bulk_table(src_path, dst_path), file=sys.stderr)
