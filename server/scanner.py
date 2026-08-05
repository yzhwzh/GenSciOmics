#!/usr/bin/env python3
"""Filesystem scanner for .h5ad datasets."""

import json
import os
import sys
import time
import threading
from pathlib import Path

import anndata

from config import DATA_DIRS, SCAN_INTERVAL, OBS_COLUMNS, PROJECT_ROOT, SCANNER_CACHE_FILE
from caches import LRUCache
from events import log_event


# ─── Global state ────────────────────────────────────────────
datasets: list[dict] = []
datasets_lock = threading.Lock()

# Cache for obs statistics: key = (str(real_path), mtime), value = dict of stats
_obs_cache = LRUCache(max_size=1000)


# ─── Persistent cache (survives restarts) ─────────────────────
_cache_lock = threading.Lock()


def _load_cache() -> dict:
    """Load scanner cache from disk JSON."""
    try:
        if SCANNER_CACHE_FILE.exists():
            return json.loads(SCANNER_CACHE_FILE.read_text())
    except Exception as e:
        print(f'[GenSci] Failed to load scanner cache: {e}', file=sys.stderr)
    return {}


def _save_cache(cache: dict):
    """Write scanner cache to disk JSON (atomic write)."""
    try:
        tmp = str(SCANNER_CACHE_FILE) + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(cache, f, indent=2)
        os.replace(tmp, str(SCANNER_CACHE_FILE))
    except Exception as e:
        print(f'[GenSci] Failed to save scanner cache: {e}', file=sys.stderr)


# ─── Annotation sources (hot-reload from JSON) ─────────────────

_annotation_sources_cache: tuple[float, dict] | None = None
_ANNOTATION_SOURCES_FILE = PROJECT_ROOT / 'server' / 'annotation_sources.json'


def _load_annotation_sources() -> dict:
    """Load annotation sources from JSON, re-read only if mtime changed."""
    global _annotation_sources_cache
    try:
        mtime = _ANNOTATION_SOURCES_FILE.stat().st_mtime
        if _annotation_sources_cache is not None and _annotation_sources_cache[0] == mtime:
            return _annotation_sources_cache[1]
        data = json.loads(_ANNOTATION_SOURCES_FILE.read_text())
        _annotation_sources_cache = (mtime, data)
        return data
    except Exception:
        if _annotation_sources_cache is not None:
            return _annotation_sources_cache[1]
        return {}  # file missing on first load → empty, all default to 'Paper'


def _read_obs_stats(real_path: Path, mtime: float) -> dict:
    """Read and cache obs column statistics from an .h5ad file."""
    key = (str(real_path), mtime)
    cached = _obs_cache.get(key)
    if cached is not None:
        return cached

    try:
        adata = anndata.read_h5ad(str(real_path), backed='r')
        stats = {'n_obs': adata.n_obs, 'n_vars': adata.n_vars}
        for col in OBS_COLUMNS:
            if col not in adata.obs.columns:
                stats[f'{col.lower()}_count'] = 0
                stats[f'{col.lower()}_dist'] = ''
                continue
            vals = adata.obs[col].dropna()
            unique = vals.unique()
            stats[f'{col.lower()}_count'] = len(unique)
            # For Group & Tissue, provide the distribution/value
            if col == 'Group':
                counts = vals.value_counts()
                if 'Sample' in adata.obs.columns:
                    grp_samples = adata.obs.groupby('Group', observed=True)['Sample'].nunique()
                    stats['group_dist'] = ', '.join(
                        f'{g} {int(grp_samples.get(g, 0))} / {int(counts.get(g, 0))}'
                        for g in counts.index
                    )
                else:
                    stats['group_dist'] = ', '.join(f'{g} {int(c)}c' for g, c in counts.items())
            elif col == 'Tissue':
                stats['tissue_obs'] = unique[0] if len(unique) == 1 else ', '.join(str(u) for u in unique)
            elif col == 'CellType':
                stats['celltype_names'] = [str(v) for v in unique]
            else:
                stats[f'{col.lower()}_dist'] = ''
        # Static metadata for analysis-info (no h5ad read needed)
        stats['sample_names'] = [str(s) for s in adata.obs['Sample'].unique()] if 'Sample' in adata.obs.columns else []
        stats['group_names'] = [str(g) for g in adata.obs['Group'].unique()] if 'Group' in adata.obs.columns else []
        stats['obs_columns'] = list(adata.obs.columns)
        adata.file.close()
        _obs_cache.set(key, stats)
        return stats
    except Exception as e:
        print(f'[GenSci] Error reading obs stats from {real_path}: {e}', file=sys.stderr)
        return {f'{c.lower()}_count': 0 for c in OBS_COLUMNS} | {'group_dist': '', 'tissue_obs': ''}


def resolve_h5ad(path: Path, cache: dict | None = None) -> dict | None:
    """Validate an h5ad path and return metadata, or None if invalid.

    If cache dict is provided and the file's resolved_path+mtime is found,
    return cached data without opening the h5ad file.
    """
    if not path.exists():
        return None

    # Follow symlinks
    real = path.resolve()
    if not real.is_file():
        return None

    stat = real.stat()
    size_mb = stat.st_size / (1024 * 1024)
    age_s = time.time() - stat.st_mtime

    # Check if file is empty
    if stat.st_size == 0:
        return None

    # Check if file is currently being written (modified within last 60s and growing)
    # A simple heuristic: if modified very recently, it might still be uploading
    status = 'ready'
    if age_s < 60:
        pass

    # ─── Persistent cache check ──────────────────────────────
    cache_key = str(path)  # use symlink path (not resolved), so different symlinks -> different cache entries
    cache_mtime = stat.st_mtime
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None and cached.get('mtime') == cache_mtime:
            # Return cached entry (add path fields that aren't stored in cache)
            return {
                'species': cached['species'],
                'tissue': cached['tissue'],
                'disease': cached['disease'],
                'pmid': cached['pmid'],
                'omics_type': cached.get('omics_type', 'scRNA'),
                'filename': cached['filename'],
                'path': str(path),
                'real_path': str(path),
                'size_mb': cached['size_mb'],
                'status': 'ready',
                'patient_count': cached.get('patient_count', 0),
                'sample_count': cached.get('sample_count', 0),
                'celltype_count': cached.get('celltype_count', 0),
                'celltype_names': cached.get('celltype_names', []),
                'n_obs': cached.get('n_obs', 0),
                'n_vars': cached.get('n_vars', 0),
                'group_dist': cached.get('group_dist', ''),
                'tissue_obs': cached.get('tissue_obs', ''),
                'annotation_source': _load_annotation_sources().get(cached.get('pmid', ''), 'Paper'),
                'sample_names': cached.get('sample_names', []),
                'group_names': cached.get('group_names', []),
                'obs_columns': cached.get('obs_columns', []),
            }

    # Extract info from path structure: Data/<Species>/<Tissue>/<Disease>/<pmid>.<disease>.h5ad
    # Make path relative to DATA_DIR so parts start with species name
    rel = None
    for dd in DATA_DIRS:
        try:
            rel = path.relative_to(dd)
            break
        except ValueError:
            continue
    if rel is None:
        rel = path.relative_to(PROJECT_ROOT)
    parts = rel.parts  # e.g. ('Human', 'Lung', 'COPD', '39121212.COPD.h5ad')

    species_keywords = {'human', 'mouse', 'monkey', 'rat'}
    species = 'Human'
    idx = 0
    if parts and parts[0].lower() in species_keywords:
        species = parts[0]
        idx = 1

    tissue = parts[idx] if len(parts) > idx else 'unknown'
    disease = parts[idx + 1] if len(parts) > idx + 1 else 'unknown'
    omics_type = 'scRNA'  # default for legacy single-cell data
    OMICS_TYPES = {'scRNA', 'BulkRNA', 'Protein', 'Metabolism', 'spatial'}
    if len(parts) > idx + 2 and parts[idx + 2] in OMICS_TYPES:
        omics_type = parts[idx + 2]

    fname = path.stem  # e.g. '39121212.COPD' or '39121212_IPF'
    pmid = fname.split('.')[0].split('_')[0] if '_' in fname else fname.split('.')[0]

    # Read obs stats from the .h5ad file (cached by mtime for performance)
    obs_stats = _read_obs_stats(real, stat.st_mtime)

    # Build result and update persistent cache
    result = {
        'species': species,
        'tissue': tissue,
        'disease': disease,
        'pmid': pmid,
        'omics_type': omics_type,
        'filename': path.name,
        'path': str(path),
        'real_path': str(path),  # symlink path inside Data/ (not resolved target)
        'size_mb': round(size_mb, 1),
        'status': status,
        'annotation_source': _load_annotation_sources().get(pmid, 'Paper'),
        **obs_stats,
    }
    if cache is not None:
        with _cache_lock:
            cache[cache_key] = {
                'mtime': cache_mtime,
                'filename': path.name,
                'species': species,
                'tissue': tissue,
                'disease': disease,
                'pmid': pmid,
                'omics_type': omics_type,
                'size_mb': round(size_mb, 1),
                'patient_count': obs_stats.get('patient_count', 0),
                'sample_count': obs_stats.get('sample_count', 0),
                'celltype_count': obs_stats.get('celltype_count', 0),
                'celltype_names': obs_stats.get('celltype_names', []),
                'n_obs': obs_stats.get('n_obs', 0),
                'n_vars': obs_stats.get('n_vars', 0),
                'group_dist': obs_stats.get('group_dist', ''),
                'tissue_obs': obs_stats.get('tissue_obs', ''),
                'annotation_source': _load_annotation_sources().get(pmid, 'Paper'),
                'sample_names': obs_stats.get('sample_names', []),
                'group_names': obs_stats.get('group_names', []),
                'obs_columns': obs_stats.get('obs_columns', []),
            }
    return result


def scan_datasets():
    """Scan DATA_DIRS for .h5ad files and build dataset list.

    Uses persistent JSON cache to avoid re-reading unchanged files.
    """
    global datasets
    cache = _load_cache()
    found = []
    for data_dir in DATA_DIRS:
        if not data_dir.is_dir():
            continue
        for f in data_dir.rglob('*.h5ad'):
            info = resolve_h5ad(f, cache)
            if info:
                found.append(info)
    _save_cache(cache)
    with datasets_lock:
        # Detect changes for logging
        old_keys = {(d['tissue'], d['disease'], d['pmid']) for d in datasets}
        new_keys = {(d['tissue'], d['disease'], d['pmid']) for d in found}
        added = new_keys - old_keys
        removed = old_keys - new_keys
        for tissue, disease, pmid in added:
            log_event('dataset_added', f'New dataset: {tissue}/{disease} (PMID:{pmid})',
                      f'{tissue}/{disease} | PMID:{pmid} | {disease}',
                      ui_message=f'New dataset: {disease}')
        for tissue, disease, pmid in removed:
            log_event('dataset_removed', f'Removed dataset: {tissue}/{disease} (PMID:{pmid})',
                      f'{tissue}/{disease} | PMID:{pmid}',
                      ui_message=f'Removed: {disease}')
        # Invalidate search result cache when datasets change
        if added or removed:
            try:
                from search import _clear_search_cache
                _clear_search_cache()
            except ImportError:
                pass
        datasets.clear()
        datasets.extend(found)


def scanner_loop():
    """Background thread that periodically rescans the filesystem."""
    time.sleep(SCAN_INTERVAL)  # Wait first cycle — initial scan already ran synchronously
    while True:
        try:
            scan_datasets()
        except Exception as e:
            print(f'[GenSci Scanner] Error: {e}', file=sys.stderr)
            import traceback
            traceback.print_exc()
        time.sleep(SCAN_INTERVAL)
