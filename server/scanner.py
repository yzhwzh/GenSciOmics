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
from core.adata_cache import locked_backed_adata
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
_first_scan_done = False

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


def _collect_obs_stats(adata, tabular: bool) -> dict:
    """Build obs column statistics from an already-opened AnnData (pure, no I/O).

    tabular=True → tabular datasets (BulkRNA/Protein): group_dist shows plain
    sample counts ('G1 5') with no '/ cells' or 'c' suffix (no cell concept).
    """
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
            if tabular:
                # Tabular (BulkRNA/Protein): one row per sample, no cells —
                # group_dist is plain sample counts only.
                if 'Sample' in adata.obs.columns:
                    grp = adata.obs.groupby('Group', observed=True)['Sample'].nunique()
                    stats['group_dist'] = ', '.join(
                        f'{g} {int(grp.get(g, 0))}' for g in counts.index)
                else:
                    stats['group_dist'] = ', '.join(
                        f'{g} {int(c)}' for g, c in counts.items())
            elif 'Sample' in adata.obs.columns:
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
    return stats


def _read_obs_stats(real_path: Path, mtime: float, tabular: bool = False) -> dict:
    """Read and cache obs column statistics for an .h5ad file (mtime-keyed).

    走共享锁定 backed 句柄（core.adata_cache）——B24 教训：此处若自开第二个 h5py File，
    并发下会与 analysis 线程的共享句柄冲突（"bad heap index"）。共享句柄由 adata_cache
    管理，**不得**在本函数内 close。

    读取失败时返回带 `_read_failed: True` 的占位结果：调用方**不得**持久化（B27）。
    占位值仅供本次展示，下次扫描自动重试。
    """
    key = (str(real_path), mtime)
    cached = _obs_cache.get(key)
    if cached is not None:
        return cached

    try:
        with locked_backed_adata(str(real_path)) as adata:
            stats = _collect_obs_stats(adata, tabular)
        # B30: a read that returns no obs columns did not really succeed. HDF5
        # has no transactional read, so opening a file mid-write can return a
        # valid-looking handle over a partially written obs table — no exception,
        # just 0 rows. _is_valid_cache_entry already treats empty obs_columns as
        # unusable; the status has to agree, or that row is served as a green
        # 'ready' 0/0/0 and the poll never arms. No live dataset is affected
        # (all 102 cached entries have obs columns, min n_obs 35).
        if not stats.get('obs_columns'):
            raise ValueError('read returned no obs columns — file likely incomplete')
        _obs_cache.set(key, stats)
        return stats
    except Exception as e:
        print(f'[GenSci] Error reading obs stats from {real_path}: {e}', file=sys.stderr)
        return {
            '_read_failed': True,
            **{f'{c.lower()}_count': 0 for c in OBS_COLUMNS},
            'group_dist': '', 'tissue_obs': '',
            'n_obs': 0, 'n_vars': 0, 'disease_count': 0,
            'celltype_names': [], 'sample_names': [], 'group_names': [], 'obs_columns': [],
        }


def _strip_read_failed(stats: dict) -> dict:
    """Drop the transient `_read_failed` marker before stats leave the scanner."""
    if '_read_failed' not in stats:
        return stats
    return {k: v for k, v in stats.items() if k != '_read_failed'}


def _is_cacheable(stats: dict) -> bool:
    """True unless the stats came from a failed read (B27: 失败结果永不落盘)."""
    return not stats.get('_read_failed')


def _row_status(obs_stats: dict) -> str:
    """Row status, carrying a failed read out instead of laundering it (B30).

    A failed read returns all-zero counts. Labelling that row 'ready' made it
    indistinguishable from a dataset that genuinely holds 0 patients / 0 cells,
    and the frontend only polls while `status !== 'ready'` — so the zeros could
    never heal on their own, even though the next scan (<=30s) reads fine.
    The failure has to be its own status, not "looks like zero".
    """
    return 'error' if obs_stats.get('_read_failed') else 'ready'


def _is_valid_cache_entry(entry: dict) -> bool:
    """Reject legacy poisoned entries (B27) so they self-heal on next scan.

    A successful read always yields a non-empty `obs_columns`; the old
    zero-sentinel was persisted with an empty list, so treat that as invalid.
    """
    return bool(entry.get('obs_columns'))


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
        if 'fpkm' in t:
            return 'FPKM'
        if 'rpkm' in t:
            return 'RPKM'
        if 'tpm' in t:
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
    obs_stats = _read_obs_stats(dst, dst.stat().st_mtime, tabular=True)
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
        'status': _row_status(obs_stats),
        'annotation_source': _get_annotation_info(pmid)[0],
        'marker_major': _get_annotation_info(pmid)[1],
        **_strip_read_failed(obs_stats),
    }
    if cache is not None and _is_cacheable(obs_stats):
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

    # Check if file is empty
    if stat.st_size == 0:
        return None

    # ─── Persistent cache check ──────────────────────────────
    cache_key = str(path)  # use symlink path (not resolved), so different symlinks -> different cache entries
    cache_mtime = stat.st_mtime
    if cache is not None:
        cached = cache.get(cache_key)
        # B27: a poisoned entry (empty obs_columns from an old failed read) is
        # treated as a miss so it gets recomputed instead of served forever.
        if (cached is not None and cached.get('mtime') == cache_mtime
                and _is_valid_cache_entry(cached)):
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
    obs_stats = _read_obs_stats(real, stat.st_mtime,
                                tabular=meta['omics_type'] in ('BulkRNA', 'Protein'))

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
        'status': _row_status(obs_stats),
        'annotation_source': _get_annotation_info(pmid)[0],
        'marker_major': _get_annotation_info(pmid)[1],
        **_strip_read_failed(obs_stats),
    }
    if cache is not None and _is_cacheable(obs_stats):
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


def _report_walk_error(err: OSError) -> None:
    """Report a directory the scan could not enter (B30).

    Path.rglob() swallows this in Python 3.10 — its internals are a bare
    `except OSError: pass`, so a permission-denied directory simply contributes
    nothing and the only symptom is a few datasets quietly missing from the list.
    os.walk's onerror is the hook rglob does not offer.
    """
    print(f'[GenSci] Scan could not read {getattr(err, "filename", "?")}: {err}',
          file=sys.stderr)


def scan_datasets():
    """Scan DATA_DIRS for .h5ad and raw bulk tables, build the dataset list.

    Uses persistent JSON cache to avoid re-reading unchanged files. Raw bulk
    tables (txt/csv/tsv/xlsx) are converted to a .h5ad cache by resolve_bulk_table
    (which imports asynchronously on first sight); the generated cache files live
    under a .bulk_cache dir and are skipped by this loop.
    """
    global datasets, _first_scan_done
    cache = _load_cache()
    found = []
    for data_dir in DATA_DIRS:
        if not data_dir.is_dir():
            continue
        # os.walk rather than Path.rglob(): rglob cannot report a directory it
        # failed to enter, so a permission problem would drop data silently.
        # Traversal is otherwise identical — os.walk(followlinks=False) yields
        # the same files as rglob here (Data/ contains file symlinks only).
        for dirpath, dirnames, filenames in os.walk(data_dir, onerror=_report_walk_error):
            # Import cache holds generated .h5ad handled via resolve_bulk_table
            dirnames[:] = [d for d in dirnames if d != BULK_CACHE_DIR_NAME]
            for name in filenames:
                f = Path(dirpath) / name
                # Broken symlinks are listed by os.walk but are not files.
                if not f.is_file():
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
    # DATA_DIRS contains Data/ plus its Mouse/Monkey subdirs, so the same file
    # can be reached twice — dedupe by source path to avoid duplicate rows.
    deduped, seen = [], set()
    for info in found:
        if info['path'] in seen:
            continue
        seen.add(info['path'])
        deduped.append(info)
    found = deduped
    _save_cache(cache)
    with datasets_lock:
        # Detect changes for logging
        old_keys = {(d['tissue'], d['disease'], d['pmid']) for d in datasets}
        new_keys = {(d['tissue'], d['disease'], d['pmid']) for d in found}
        added = new_keys - old_keys
        removed = old_keys - new_keys
        # Skip diff logging on the first scan: it's a load of existing data,
        # not a discovery. Otherwise every restart spams "New dataset".
        if _first_scan_done:
            for tissue, disease, pmid in added:
                log_event('dataset_added', f'New dataset: {tissue}/{disease} (PMID:{pmid})',
                          f'{tissue}/{disease} | PMID:{pmid} | {disease}',
                          ui_message=f'New dataset: {disease}')
            for tissue, disease, pmid in removed:
                log_event('dataset_removed', f'Removed dataset: {tissue}/{disease} (PMID:{pmid})',
                          f'{tissue}/{disease} | PMID:{pmid}',
                          ui_message=f'Removed: {disease}')
        _first_scan_done = True
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
