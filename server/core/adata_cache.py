"""Shared AnnData cache — backed='r', keyed by (path, mtime).

All analysis modules share a single adata object per dataset, avoiding
repeated HDF5 open overhead. Memory cost is ~few MB per dataset (metadata
only — backed='r' reads actual data from disk on demand)."""

import threading
from pathlib import Path
from collections import OrderedDict

import anndata


_cache: dict[str, 'anndata.AnnData'] = OrderedDict()
_cache_lock = threading.Lock()
MAX_SIZE = 8


def get_adata(path: str) -> 'anndata.AnnData':
    """Get a cached backed='r' AnnData object. Thread-safe."""
    p = Path(path)
    mtime = p.stat().st_mtime if p.exists() else 0
    key = f'{path}:{mtime}'

    with _cache_lock:
        # Hit: move to end (LRU), return existing handle
        if key in _cache:
            adata = _cache.pop(key)
            _cache[key] = adata
            return adata

        # Miss: open, cache, evict oldest if needed
        while len(_cache) >= MAX_SIZE:
            old_key, old_adata = next(iter(_cache.items()))
            try:
                old_adata.file.close()
            except Exception:
                pass
            del _cache[old_key]

        adata = anndata.read_h5ad(path, backed='r')
        _cache[key] = adata
        return adata
