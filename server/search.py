#!/usr/bin/env python3
"""Search functionality across datasets."""

import sys
from pathlib import Path

from core.adata_cache import get_adata

from scanner import datasets, datasets_lock
from caches import LRUCache


# Cache for gene names: key = (str(real_path), mtime), value = set of gene names
# Used by routes.py handle_search_genes() for gene autocomplete
_gene_cache = LRUCache(max_size=500)

# Cache for search results: key = query string (lowercase), value = list[dict]
_search_result_cache = LRUCache(max_size=200)


def _get_genes(real_path: Path, mtime: float) -> set:
    """Read and cache gene names (var_names) from an .h5ad file.

    Uses the shared backed AnnData from adata_cache (same handle as UMAP,
    dotplot, expression) to avoid opening a second h5py File on the same .h5ad.
    """
    key = (str(real_path), mtime)
    cached = _gene_cache.get(key)
    if cached is not None:
        return cached
    try:
        adata = get_adata(str(real_path))
        genes = set(str(g) for g in adata.var_names)
        _gene_cache.set(key, genes)
        return genes
    except Exception as e:
        print(f'[GenSci] Error reading genes from {real_path}: {e}', file=sys.stderr)
        return set()


def _clear_search_cache():
    """Clear the search result cache (called by scanner when datasets change)."""
    _search_result_cache.clear()


def _search_datasets(query: str) -> list[dict]:
    """Search across all datasets for matching diseases, PMIDs, cell types, etc."""
    q = query.strip().lower()
    if not q:
        return []

    # Check result cache
    cached = _search_result_cache.get(q)
    if cached is not None:
        return cached

    with datasets_lock:
        all_ds = datasets[:]

    results = []
    seen = set()

    for ds in all_ds:
        matches = []

        # 1. Match disease (directory name)
        if q in ds.get('disease', '').lower():
            matches.append(('disease', ds['disease']))

        # 2. Match PMID
        if q in ds.get('pmid', '').lower():
            matches.append(('pmid', ds['pmid']))

        # 3. Match tissue
        if q in ds.get('tissue', '').lower():
            matches.append(('tissue', ds['tissue']))

        # 4. Match tissue_obs (sample type)
        tobs = ds.get('tissue_obs', '')
        if tobs and q in tobs.lower():
            matches.append(('sample_type', tobs))

        # 5. Match CellType names (pre-cached by scanner, no file I/O)
        cts = ds.get('celltype_names', [])
        for ct in cts:
            if q in str(ct).lower():
                matches.append(('celltype', str(ct)))
                break

        if matches:
            key = (ds['tissue'], ds['disease'], ds['pmid'])
            if key not in seen:
                seen.add(key)
                results.append({
                    **ds,
                    'search_matches': matches,
                })

    _search_result_cache.set(q, results)
    return results
