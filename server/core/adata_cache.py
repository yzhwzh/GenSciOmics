"""Shared AnnData cache — backed='r', keyed by (path, mtime).

All analysis modules share a single adata object per dataset, avoiding
repeated HDF5 open overhead. Memory cost is ~few MB per dataset (metadata
only — backed='r' reads actual data from disk on demand).

Thread safety: a per-file lock serialises access to the shared backed AnnData,
preventing h5py concurrency errors when multiple threads slice into adata.X."""

import threading
from contextlib import contextmanager
from pathlib import Path
from collections import OrderedDict

import anndata


_cache: dict[str, 'anndata.AnnData'] = OrderedDict()
_cache_lock = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()
MAX_SIZE = 8


def _get_file_lock(path: str) -> threading.Lock:
    """Get or create a per-file lock for serialising backed access."""
    with _file_locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


@contextmanager
def locked_backed_adata(path: str) -> 'anndata.AnnData':
    """Context manager: acquire file lock, yield backed AnnData, release.

    Usage:
        with locked_backed_adata(path) as adata:
            subset = adata[mask].to_memory()
        # lock released — heavy work runs unlocked
    """
    lock = _get_file_lock(path)
    lock.acquire()
    try:
        adata = get_adata(path)
        yield adata
    finally:
        lock.release()


def get_adata(path: str) -> 'anndata.AnnData':
    """Get a cached backed='r' AnnData object. Thread-safe cache, but
    callers MUST serialise access themselves (use locked_backed_adata())."""
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
