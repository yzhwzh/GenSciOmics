#!/usr/bin/env python3
"""Filesystem scanner for .h5ad datasets."""

import json
import os
import sys
import time
import threading
from pathlib import Path

import anndata

from config import (
    DATA_DIRS, SCAN_INTERVAL, OBS_COLUMNS, PROJECT_ROOT, SCANNER_CACHE_FILE,
    BULK_CACHE_DIR_NAME,
)
from bulk_import import import_bulk_table
from caches import LRUCache
from events import log_event


# ─── Path convention constants ────────────────────────────────
FLAT_TISSUES = {'Multi-organ'}  # tissues without a disease subdirectory
OMICS_TYPES = {'scRNA', 'BulkRNA', 'Protein', 'Metabolism', 'spatial'}
BULK_EXTENSIONS = {'.txt', '.tsv', '.csv', '.xlsx'}

# Raw bulk tables currently being imported (key = cache h5ad path string).
_importing: set[str] = set()
_importing_lock = threading.Lock()


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
    """Load annotation sources from JSON, re-read only if mtime changed.
    Returns {PMID: {Source, Major?}} dict (v2 format with marker genes)."""
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


def _get_annotation_info(pmid: str) -> tuple[str, dict | None]:
    """Return (source_label, marker_major_dict_or_None) for a given PMID.
    Handles both v1 (string values) and v2 (dict values) JSON formats."""
    entry = _load_annotation_sources().get(pmid, 'Paper')
    if isinstance(entry, str):
        return (entry, None)  # v1 legacy format
    return (entry.get('Source', 'Paper'), entry.get('Major'))


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
        # Disease count (bulk RNA uses Disease as the cancer-type column)
        stats['disease_count'] = int(adata.obs['Disease'].nunique()) if 'Disease' in adata.obs.columns else 0
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


def _extract_data_type(fname: str) -> str:
    """Extract bulk-table data type (count/TPM/Intensity) from a filename stem.

    fname is the stem without extension (e.g. '29625048.TCGA.TPM').
    Convention: <PMID>.<source>.<type> — type is the 3rd dot-separated segment.
    """
    for tok in fname.split('.')[2:]:
        t = tok.lower()
        if 'intensity' in t or 'signal' in t:
            return 'Intensity'
        if 'count' in t:
            return 'count'
        if 'tpm' in t or 'fpkm' in t or 'rpkm' in t:
            return 'TPM'
    return ''


def _extract_path_fields(path: Path) -> dict:
    """Extract species/tissue/disease/omics_type/pmid from a Data/ path."""
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
    if tissue in FLAT_TISSUES:
        disease = tissue
        omics_type = parts[idx + 1] if len(parts) > idx + 1 and parts[idx + 1] in OMICS_TYPES else 'scRNA'
    else:
        disease = parts[idx + 1] if len(parts) > idx + 1 else 'unknown'
        omics_type = 'scRNA'
        if len(parts) > idx + 2 and parts[idx + 2] in OMICS_TYPES:
            omics_type = parts[idx + 2]

    fname = path.stem
    pmid = fname.split('.')[0].split('_')[0] if '_' in fname else fname.split('.')[0]

    return {
        'species': species,
        'tissue': tissue,
        'disease': disease,
        'omics_type': omics_type,
        'pmid': pmid,
        'data_type': _extract_data_type(fname),
    }


def _bulk_cache_path(path: Path) -> Path:
    """Return the cache .h5ad path for a raw bulk table."""
    return path.parent / BULK_CACHE_DIR_NAME / f'{path.stem}.h5ad'


def _start_import(src: Path, dst: Path, omics_type: str = 'BulkRNA') -> None:
    """Kick off a background import thread (idempotent per cache target)."""
    key = str(dst)
    with _importing_lock:
        if key in _importing:
            return
        _importing.add(key)

    def _worker() -> None:
        try:
            import_bulk_table(src, dst, omics_type)
            label = 'Protein' if omics_type == 'Protein' else 'Bulk RNA'
            log_event('bulk_imported', f'Imported {label.lower()} table {src.name}',
                      f'{src.name} → {dst.name}',
                      ui_message=f'{label} imported: {src.name}')
        except Exception as e:
            print(f'[GenSci] bulk import failed for {src}: {e}', file=sys.stderr)
        finally:
            with _importing_lock:
                _importing.discard(key)

    threading.Thread(target=_worker, daemon=True, name=f'bulk-import-{src.stem}').start()


def resolve_bulk_table(path: Path, cache: dict | None = None) -> dict | None:
    """Resolve a raw bulk table (txt/csv/tsv/xlsx) into a dataset entry.

    If the .h5ad cache is fresh, returns a full entry pointing real_path at the
    cache; otherwise starts a background import and returns status='importing'.
    """
    if not path.exists():
        return None
    real = path.resolve()
    if not real.is_file():
        return None
    stat = real.stat()
    if stat.st_size == 0:
        return None

    dst = _bulk_cache_path(path)
    meta = _extract_path_fields(path)
    pmid = meta['pmid']
    size_mb = round(stat.st_size / (1024 * 1024), 1)

    if not (dst.exists() and dst.stat().st_mtime >= stat.st_mtime):
        _start_import(path, dst, meta['omics_type'])
        return {
            'species': meta['species'],
            'tissue': meta['tissue'],
            'disease': meta['disease'],
            'pmid': pmid,
            'omics_type': meta['omics_type'],
            'data_type': meta['data_type'],
            'filename': path.name,
            'path': str(path),
            'real_path': str(dst),
            'size_mb': size_mb,
            'status': 'importing',
            'patient_count': 0,
            'sample_count': 0,
            'celltype_count': 0,
            'celltype_names': [],
            'n_obs': 0,
            'n_vars': 0,
            'disease_count': 0,
            'group_dist': '',
            'tissue_obs': '',
            'annotation_source': _get_annotation_info(pmid)[0],
            'marker_major': _get_annotation_info(pmid)[1],
            'sample_names': [],
            'group_names': [],
            'obs_columns': [],
        }

    # Cache fresh — read stats from cache h5ad, point real_path at it.
    obs_stats = _read_obs_stats(dst, dst.stat().st_mtime)
    result = {
        'species': meta['species'],
        'tissue': meta['tissue'],
        'disease': meta['disease'],
        'pmid': pmid,
        'omics_type': meta['omics_type'],
        'data_type': meta['data_type'],
        'filename': path.name,
        'path': str(path),
        'real_path': str(dst),
        'size_mb': size_mb,
        'status': 'ready',
        'annotation_source': _get_annotation_info(pmid)[0],
        'marker_major': _get_annotation_info(pmid)[1],
        **obs_stats,
    }
    if cache is not None:
        with _cache_lock:
            cache[str(path)] = {
                'mtime': stat.st_mtime,
                'filename': path.name,
                'species': meta['species'],
                'tissue': meta['tissue'],
                'disease': meta['disease'],
                'pmid': pmid,
                'omics_type': meta['omics_type'],
                'data_type': meta['data_type'],
                'size_mb': size_mb,
                'patient_count': obs_stats.get('patient_count', 0),
                'sample_count': obs_stats.get('sample_count', 0),
                'celltype_count': obs_stats.get('celltype_count', 0),
                'celltype_names': obs_stats.get('celltype_names', []),
                'n_obs': obs_stats.get('n_obs', 0),
                'n_vars': obs_stats.get('n_vars', 0),
                'disease_count': obs_stats.get('disease_count', 0),
                'group_dist': obs_stats.get('group_dist', ''),
                'tissue_obs': obs_stats.get('tissue_obs', ''),
                'sample_names': obs_stats.get('sample_names', []),
                'group_names': obs_stats.get('group_names', []),
                'obs_columns': obs_stats.get('obs_columns', []),
            }
    return result


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
                'disease_count': cached.get('disease_count', 0),
                'group_dist': cached.get('group_dist', ''),
                'tissue_obs': cached.get('tissue_obs', ''),
                'annotation_source': _get_annotation_info(cached.get('pmid', ''))[0],
                'marker_major': _get_annotation_info(cached.get('pmid', ''))[1],
                'sample_names': cached.get('sample_names', []),
                'group_names': cached.get('group_names', []),
                'obs_columns': cached.get('obs_columns', []),
            }

    # Extract info from path structure: Data/<Species>/<Tissue>/<Disease>/<pmid>.<disease>.h5ad
    meta = _extract_path_fields(path)
    species = meta['species']
    tissue = meta['tissue']
    disease = meta['disease']
    pmid = meta['pmid']
    omics_type = meta['omics_type']

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
        'annotation_source': _get_annotation_info(pmid)[0],
        'marker_major': _get_annotation_info(pmid)[1],
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
                'disease_count': obs_stats.get('disease_count', 0),
                'group_dist': obs_stats.get('group_dist', ''),
                'tissue_obs': obs_stats.get('tissue_obs', ''),
                'annotation_source': _get_annotation_info(pmid)[0],
                'marker_major': _get_annotation_info(pmid)[1],
                'sample_names': obs_stats.get('sample_names', []),
                'group_names': obs_stats.get('group_names', []),
                'obs_columns': obs_stats.get('obs_columns', []),
            }
    return result


def scan_datasets():
    """Scan DATA_DIRS for .h5ad and raw bulk tables, build the dataset list.

    Uses persistent JSON cache to avoid re-reading unchanged files. Raw bulk
    tables (txt/csv/tsv/xlsx) are converted to a .h5ad cache by resolve_bulk_table
    (which imports asynchronously on first sight); the generated cache files live
    under a .bulk_cache dir and are skipped by this loop.
    """
    global datasets
    cache = _load_cache()
    found = []
    for data_dir in DATA_DIRS:
        if not data_dir.is_dir():
            continue
        for f in data_dir.rglob('*'):
            if not f.is_file():
                continue
            # Import cache holds generated .h5ad handled via resolve_bulk_table
            if BULK_CACHE_DIR_NAME in f.parts:
                continue
            suffix = f.suffix.lower()
            if suffix == '.h5ad':
                info = resolve_h5ad(f, cache)
            elif suffix in BULK_EXTENSIONS:
                info = resolve_bulk_table(f, cache)
            else:
                continue
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
