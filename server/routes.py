#!/usr/bin/env python3
"""Route table definition and handler functions."""

import json
import os
import sys
import time
import mimetypes
from pathlib import Path
from collections import Counter

from config import DATA_DIRS

RESULTS_DIR = Path('/tmp/gensci_results')
from scanner import datasets, datasets_lock
from caches import LRUCache
from core.adata_cache import get_adata

# Caches for expensive .h5ad reads
_analysis_info_cache = LRUCache(max_size=500)
_umap_cache = LRUCache(max_size=200)
_plot_cache = LRUCache(max_size=500)
_table_cache = LRUCache(max_size=500)
from events import log_event, event_log, event_log_lock, MILESTONES, milestones_lock, MILESTONE_FILE
from search import _search_datasets
from pubmed import _fetch_abstract
from analysis.umap import _get_umap_data
from analysis.expression import _get_expression_stats
from analysis.stats import _get_per_sample_table, _get_per_sample_mutest, _get_aggregate_table, _get_raw_expression
from analysis.plots import _generate_plot, _generate_cell_ratio_plot, _generate_umap_ratio_plots, _generate_celltype_composition, _generate_marker_dotplot
from analysis.utils import CATEGORICAL_PALETTE_MAP
from analysis.bulk import bulk_boxplot, bulk_de, bulk_diseases, bulk_volcano
from search import _get_genes
from llm_proxy import process_chat, process_chat_streaming, process_literature_chat_streaming
from skills import list_skills, get_skill_content
from online import heartbeat, count_online

# ── Plot storage (skills put PNGs here, frontend fetches by ID) ──
import socket as _socket, uuid as _uuid, base64 as _b64, threading as _threading
_plots: dict[str, bytes] = {}
_plots_lock = _threading.Lock()

def store_plot(png_bytes: bytes) -> str:
    pid = _uuid.uuid4().hex[:12]
    with _plots_lock:
        _plots[pid] = png_bytes
    return pid

def handle_get_skill_plot(handler, q):
    pid = q.get('id', '')
    with _plots_lock:
        data = _plots.get(pid)
    if data is None:
        handler._send_error('Plot not found')
        return
    handler._send_bytes(data, 'image/png')


VALID_PALETTES = set(CATEGORICAL_PALETTE_MAP.keys())

def get_palette_name(q: dict) -> str:
    """Extract and validate palette name from query dict."""
    name = q.get('palette', 'default')
    if name not in VALID_PALETTES:
        name = 'default'
    return name

# ─── Path validation helper ───────────────────────────────────
def validate_real_path(path_str: str):
    """Validate path is within DATA_DIRS (path traversal protection).
    Checks the original path (not resolved symlink target) so that
    symlinks inside DATA_DIRS pointing to external storage are allowed.
    Returns the original Path if valid, None otherwise."""
    if not path_str:
        return None
    try:
        p = Path(path_str).resolve()  # follow symlinks for normalization
        # Check that the path resolves to a real file
        if not p.is_file():
            return None
        # But validate the ORIGINAL (unresolved) path is within DATA_DIRS
        # This allows symlinks inside DATA_DIRS pointing to external storage
        original = Path(path_str)
        allowed = any(original.is_relative_to(d) for d in DATA_DIRS)
        return original if allowed else None
    except Exception:
        return None


# ─── Handler function type: (handler_instance, query_dict) -> None
# Each handler calls handler._json() or handler._send_error()


def handle_datasets(handler, q):
    with datasets_lock:
        result = datasets[:]
    tissue_filter = q.get('tissue', '').lower()
    if tissue_filter:
        result = [d for d in result if d['tissue'].lower() == tissue_filter]
    handler._json(result)


def handle_search(handler, q):
    query = q.get('q', '')
    if not query:
        handler._json({'query': query, 'results': []})
        return
    results = _search_datasets(query)
    handler._json({'query': query, 'results': results})


def handle_tissues(handler, q):
    with datasets_lock:
        tissues = sorted(set(d['tissue'] for d in datasets))
    handler._json(tissues)


def handle_stats(handler, q):
    with datasets_lock:
        all_ds = [d for d in datasets if d['tissue'] not in ('Health', 'Multi-organ')]
    species_set = sorted(set(d['species'] for d in all_ds))
    tissue_set = sorted(set(d['tissue'] for d in all_ds))
    rows = {}
    # Count unique PMIDs per species ("套数", not file count)
    species_pmids: dict[str, set] = {}
    for d in all_ds:
        species_pmids.setdefault(d['species'], set()).add(d['pmid'])
    for tis in tissue_set:
        row = {}
        for sp in species_set:
            ds_list = [d for d in all_ds if d['tissue'] == tis and d['species'] == sp]
            dis_counts: dict[str, int] = {}
            for d in ds_list:
                dis_counts[d['disease']] = dis_counts.get(d['disease'], 0) + 1
            diseases = sorted(dis_counts.items())
            row[sp] = {
                'total_datasets': sum(dis_counts.values()),
                'diseases': [{'name': k, 'count': v} for k, v in diseases],
            }
        rows[tis] = row
    # Count Health vs Disease PMIDs per species
    species_health: dict[str, set] = {}
    species_disease: dict[str, set] = {}
    for d in datasets:
        sp = d['species']
        pmid = d['pmid']
        is_health = d.get('disease', '').lower() == 'health' or d.get('tissue', '').lower() == 'health'
        if is_health:
            species_health.setdefault(sp, set()).add(pmid)
        else:
            species_disease.setdefault(sp, set()).add(pmid)
    handler._json({
        'species': species_set,
        'tissues': tissue_set,
        'rows': rows,
        'species_dataset_counts': {sp: len(pmids) for sp, pmids in species_pmids.items()},
        'species_health_counts': {sp: len(pmids) for sp, pmids in species_health.items()},
        'species_disease_counts': {sp: len(pmids) for sp, pmids in species_disease.items()},
    })


def handle_log(handler, q):
    limit = min(int(q.get('limit', 50)), 100)
    with milestones_lock:
        ms = MILESTONES[:]
    with event_log_lock:
        ev = event_log[:]
    combined = ms + ev
    combined.sort(key=lambda e: e.get('time', ''), reverse=True)
    handler._json(combined[:limit])




def handle_analysis_info(handler, q):
    pmid = q.get('pmid', '')
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    cache_key = f'ai:{real_path_str}:{pmid}'
    cached = _analysis_info_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    abstract_info = _fetch_abstract(pmid)
    # Try scanner cache first (fast, no h5ad read)
    stats = None
    try:
        from config import SCANNER_CACHE_FILE
        if SCANNER_CACHE_FILE.exists():
            sc = json.loads(SCANNER_CACHE_FILE.read_text())
            for k, v in sc.items():
                if str(real_path) in k or k.endswith(str(real_path).name):
                    if v.get('pmid') == pmid:
                        stats = {
                            'cells': v.get('n_obs') or 0,
                            'genes': v.get('n_vars') or 0,
                            'patient_count': v.get('patient_count', 0),
                            'sample_count': v.get('sample_count', 0),
                            'celltype_count': v.get('celltype_count', 0),
                            'cell_type_names': v.get('celltype_names', []),
                            'sample_names': v.get('sample_names', []),
                            'group_names': v.get('group_names', []),
                            'obs_columns': v.get('obs_columns', []),
                            'disease_count': v.get('disease_count', 0),
                            'group_dist': v.get('group_dist', ''),
                        }
                        break
    except Exception:
        pass
    # Fallback: read h5ad directly (slow, for cold cache)
    if stats is None:
        try:
            import anndata
            from core.adata_cache import get_adata
            adata = get_adata(str(real_path))
            stats = {'cells': adata.n_obs, 'genes': adata.n_vars}
            for col in ['Patient', 'Sample', 'CellType']:
                if col in adata.obs.columns:
                    stats[f'{col.lower()}_count'] = int(adata.obs[col].nunique())
                else:
                    stats[f'{col.lower()}_count'] = 0
            if 'CellType' in adata.obs.columns:
                stats['cell_type_names'] = [str(x) for x in adata.obs['CellType'].cat.categories] \
                    if hasattr(adata.obs['CellType'], 'cat') else [str(x) for x in adata.obs['CellType'].unique()]
            else:
                stats['cell_type_names'] = []
            stats['disease_count'] = int(adata.obs['Disease'].nunique()) if 'Disease' in adata.obs.columns else 0
            stats['sample_names'] = [str(s) for s in adata.obs['Sample'].unique()] if 'Sample' in adata.obs.columns else []
            stats['group_names'] = [str(g) for g in adata.obs['Group'].unique()] if 'Group' in adata.obs.columns else []
            if 'Group' in adata.obs.columns:
                counts = adata.obs['Group'].value_counts()
                stats['group_dist'] = ', '.join(f'{g} {int(c)}' for g, c in counts.items())
            else:
                stats['group_dist'] = ''
        except Exception as e:
            stats = {'cells': 0, 'genes': 0, 'patient_count': 0, 'sample_count': 0,
                     'celltype_count': 0, 'cell_type_names': [], 'error': str(e)}
    result = {'pmid': pmid, 'abstract': abstract_info, 'stats': stats}
    _analysis_info_cache.set(cache_key, result)
    handler._json(result)


def handle_umap_data(handler, q):
    real_path_str = q.get('real_path', '')
    color_by = q.get('color_by', 'CellType')
    max_points = int(q.get('max_points', 50000))
    gene = q.get('gene', '')
    gene2 = q.get('gene2', '')
    palette = get_palette_name(q)
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    cache_key = f'umap:{real_path_str}:{color_by}:{max_points}:{gene}:{gene2}:{palette}'
    cached = _umap_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    data = _get_umap_data(real_path, color_by, max_points, gene, palette, gene2)
    _umap_cache.set(cache_key, data)
    handler._json(data)


def handle_search_genes(handler, q):
    real_path_str = q.get('real_path', '')
    query = q.get('q', '').strip().lower()
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if len(query) < 1:
        handler._json({'genes': []})
        return
    mtime = os.path.getmtime(real_path_str)
    all_genes = _get_genes(real_path, mtime)
    matched = sorted(g for g in all_genes if query in g.lower())
    handler._json({'genes': matched[:100]})


def handle_expression_stats(handler, q):
    real_path_str = q.get('real_path', '')
    genes_str = q.get('genes', '')
    group_by = q.get('group_by', 'Sample')
    cell_type = q.get('cell_type', 'All')
    condition_col = q.get('condition_col', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not genes_str:
        handler._send_error('genes parameter required')
        return
    data = _get_expression_stats(real_path, genes_str, group_by, cell_type, condition_col)
    handler._json(data)


def handle_per_sample_table(handler, q):
    real_path_str = q.get('real_path', '')
    genes_str = q.get('genes', '')
    group_col = q.get('group_col', 'Group')
    celltype_col = q.get('celltype_col', 'CellType')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not genes_str:
        handler._send_error('genes parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'pstable:{real_path_str}:{mtime}:{genes_str}:{group_col}:{celltype_col}'
    cached = _table_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _get_per_sample_table(str(real_path), genes_str, group_col, celltype_col)
    _table_cache.set(cache_key, result)
    handler._json(result)


def handle_per_sample_mutest(handler, q):
    real_path_str = q.get('real_path', '')
    genes_str = q.get('genes', '')
    group_col = q.get('group_col', 'Group')
    celltype_col = q.get('celltype_col', 'CellType')
    min_cells = int(q.get('min_cells', '2'))
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not genes_str:
        handler._send_error('genes parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'mutest:{real_path_str}:{mtime}:{genes_str}:{group_col}:{celltype_col}:{min_cells}'
    cached = _table_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _get_per_sample_mutest(str(real_path), genes_str, group_col, celltype_col, min_cells)
    _table_cache.set(cache_key, result)
    handler._json(result)


def handle_aggregate_table(handler, q):
    real_path_str = q.get('real_path', '')
    genes_str = q.get('genes', '')
    group_col = q.get('group_col', '')
    celltype_col = q.get('celltype_col', 'CellType')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not genes_str:
        handler._send_error('genes parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    eff_group = group_col if group_col and group_col != 'None' else ''
    cache_key = f'aggtbl:{real_path_str}:{mtime}:{genes_str}:{eff_group}:{celltype_col}'
    cached = _table_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    # When condition is None/empty, pass empty group_col to backend
    result = _get_aggregate_table(str(real_path), genes_str, eff_group, celltype_col)
    _table_cache.set(cache_key, result)
    handler._json(result)


def handle_plot(handler, q):
    real_path_str = q.get('real_path', '')
    gene = q.get('gene', '')
    condition_col = q.get('condition_col', '')
    metric = q.get('metric', 'expression_pct')
    plot_type = q.get('plot_type', 'boxplot')
    min_cells = int(q.get('min_cells', '2'))
    palette = get_palette_name(q)
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not gene:
        handler._send_error('gene parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'plot:{real_path_str}:{mtime}:{gene}:{condition_col}:{metric}:{plot_type}:{palette}:{min_cells}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _generate_plot(str(real_path), gene, condition_col, metric, plot_type, min_cells, palette)
    _plot_cache.set(cache_key, result)
    handler._json(result)


def handle_cell_ratio_plot(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    condition_col = q.get('condition_col', '')
    palette = get_palette_name(q)
    result = _generate_cell_ratio_plot(str(real_path), condition_col, palette)
    handler._json(result)


def handle_marker_dotplot(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    palette = get_palette_name(q)
    group_filter = q.get('group_filter', '')
    genes = q.get('genes', '')
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'mkrdot:{real_path_str}:{mtime}:{palette}:{group_filter}:{genes}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _generate_marker_dotplot(str(real_path), palette, group_filter, genes)
    _plot_cache.set(cache_key, result)
    handler._json(result)


def handle_composition_plot(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    gene = q.get('gene', '')
    gene2 = q.get('gene2', '')
    palette = get_palette_name(q)
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'comp:{real_path_str}:{mtime}:{gene}:{gene2}:{palette}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _generate_celltype_composition(str(real_path), gene, palette, gene2)
    _plot_cache.set(cache_key, result)
    handler._json(result)


def handle_umap_ratio_plots(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    group_var = q.get('group_var', '')
    palette = get_palette_name(q)
    result = _generate_umap_ratio_plots(str(real_path), group_var, palette)
    handler._json(result)


def handle_bulk_boxplot(handler, q):
    real_path_str = q.get('real_path', '')
    gene = q.get('gene', '')
    disease = q.get('disease', '') or None
    palette = get_palette_name(q)
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not gene:
        handler._send_error('gene parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'bulkbox:{real_path_str}:{mtime}:{gene}:{disease}:{palette}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = bulk_boxplot(str(real_path), gene, disease, palette)
    _plot_cache.set(cache_key, result)
    handler._json(result)


def handle_bulk_de(handler, q):
    real_path_str = q.get('real_path', '')
    disease = q.get('disease', '') or None
    top_n = int(q.get('top_n', 100))
    case_group = q.get('case_group', '') or None
    control_group = q.get('control_group', '') or None
    if top_n > 500:
        top_n = 500
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'bulkde:{real_path_str}:{mtime}:{disease}:{top_n}:{case_group}:{control_group}'
    # top_n <= 0 requests the full gene table (CSV download) — too large to cache
    if top_n > 0:
        cached = _table_cache.get(cache_key)
        if cached:
            handler._json(cached)
            return
    result = bulk_de(str(real_path), disease, top_n, case_group, control_group)
    if top_n > 0:
        _table_cache.set(cache_key, result)
    handler._json(result)


def handle_bulk_volcano(handler, q):
    real_path_str = q.get('real_path', '')
    disease = q.get('disease', '') or None
    fc_thresh = float(q.get('fc', 1.0))
    alpha = float(q.get('alpha', 0.05))
    case_group = q.get('case_group', '') or None
    control_group = q.get('control_group', '') or None
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'bulkvol:{real_path_str}:{mtime}:{disease}:{fc_thresh}:{alpha}:{case_group}:{control_group}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = bulk_volcano(str(real_path), disease, fc_thresh, alpha, case_group, control_group)
    _plot_cache.set(cache_key, result)
    handler._json(result)


def handle_bulk_diseases(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    handler._json(bulk_diseases(str(real_path)))




def handle_milestone(handler, data):
    msg = data.get('message', '')
    detail = data.get('detail', '')
    if not msg:
        handler._send_error('message required')
        return
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    entry = {'time': now, 'type': 'milestone', 'message': msg, 'detail': detail}
    with milestones_lock:
        MILESTONES.append(entry)
        try:
            with open(MILESTONE_FILE, 'w') as f:
                json.dump(MILESTONES, f, indent=2)
        except Exception:
            pass
    handler._json(entry)


def handle_skills_list(handler, q):
    """GET /api/skills — list available skills with their tool definitions."""
    skills = list_skills()
    handler._json([{
        'name': s.name,
        'description': s.description,
        'has_tool': s.func is not None,
        'has_skill_md': get_skill_content(s.name) is not None,
        'parameters': s.to_openai_tool()['function']['parameters'] if s.to_openai_tool() else None,
    } for s in skills])


def handle_skill_content(handler, q):
    name = q.get('name', '')
    if not name:
        handler._send_error('name parameter required'); return
    if '/' in name or '\\' in name or '..' in name:
        handler._send_error('Invalid skill name', 400); return
    from skills import SKILL_REGISTRY
    if name not in SKILL_REGISTRY:
        handler._send_error('Skill not found', 404); return
    content = get_skill_content(name)
    if content is None:
        handler._send_error('Skill not found or has no SKILL.md')
        return
    handler._json({'name': name, 'content': content})


def handle_llm_chat(handler, data):
    """POST /api/llm/chat — process chat with tool calling (synchronous)."""
    messages = data.get('messages', [])
    real_path = data.get('real_path', '')
    api_key = data.get('api_key', '')
    model = data.get('model', 'deepseek-chat')
    base_url = data.get('base_url', 'https://api.deepseek.com')
    temperature = float(data.get('temperature', 0.7))

    if not messages:
        handler._send_error('messages required')
        return
    if not real_path:
        handler._send_error('real_path required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    result = process_chat(messages, real_path, api_key, model, base_url, temperature)
    handler._json(result)


def handle_llm_chat_stream(handler, data):
    """POST /api/llm/chat/stream — process chat with streaming SSE response."""
    messages = data.get('messages', [])
    real_path = data.get('real_path', '')
    api_key = data.get('api_key', '')
    model = data.get('model', 'deepseek-chat')
    base_url = data.get('base_url', 'https://api.deepseek.com')
    temperature = float(data.get('temperature', 0.7))
    omics_type = data.get('omics_type', '')

    if not messages:
        handler._send_error('messages required')
        return
    if not real_path:
        handler._send_error('real_path required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    # Send SSE headers
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'close')
    handler.send_header('X-Accel-Buffering', 'no')
    origin = handler.headers.get('Origin', '')
    allowed = getattr(handler, '_allowed_origins', [])
    handler.send_header('Access-Control-Allow-Origin', origin if origin in allowed else '')
    handler.end_headers()

    # Heartbeat: send SSE comment every 15s to keep proxy alive during tool execution
    _hb_stop = _threading.Event()

    def _heartbeat():
        while not _hb_stop.is_set():
            _hb_stop.wait(15)
            if _hb_stop.is_set():
                break
            try:
                handler.wfile.write(b': heartbeat\n\n')
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break

    _hb_thread = _threading.Thread(target=_heartbeat, daemon=True)
    _hb_thread.start()

    try:
        for event in process_chat_streaming(messages, real_path, api_key, model, base_url, temperature, omics_type):
            # Check if client disconnected
            if _hb_stop.is_set():
                break
            ev_name = event.get('event', '')
            ev_data = event.get('data', '')
            try:
                handler.wfile.write(f"event: {ev_name}\ndata: {ev_data}\n\n".encode())
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break  # client disconnected
    except Exception as e:
        try:
            handler.wfile.write(f"event: error\ndata: {json.dumps({'error': str(e)[:200]})}\n\n".encode())
        except Exception:
            pass
    finally:
        _hb_stop.set()
        _hb_thread.join(timeout=3)
        try:
            handler.connection.shutdown(_socket.SHUT_WR)
        except (OSError, AttributeError):
            try:
                handler.connection.close()
            except (OSError, AttributeError):
                pass


def handle_llm_literature_stream(handler, data):
    """POST /api/llm/literature/stream — literature research chat with streaming SSE.

    Unlike the general LLM chat, literature mode:
    - Only exposes search + gene_info tools
    - Uses a specialized system prompt focused on literature research
    - Does NOT require real_path (literature search is dataset-independent)
    - Connects to the memory system
    """
    messages = data.get('messages', [])
    api_key = data.get('api_key', '')
    model = data.get('model', 'deepseek-chat')
    base_url = data.get('base_url', 'https://api.deepseek.com')
    temperature = float(data.get('temperature', 0.7))
    context = data.get('context', '')  # tissue/disease context from the page

    if not messages:
        handler._send_error('messages required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    # Send SSE headers
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'close')
    handler.send_header('X-Accel-Buffering', 'no')
    origin = handler.headers.get('Origin', '')
    allowed = getattr(handler, '_allowed_origins', [])
    handler.send_header('Access-Control-Allow-Origin', origin if origin in allowed else '')
    handler.end_headers()

    # Heartbeat: send SSE comment every 15s to keep proxy alive
    _lit_hb_stop = _threading.Event()

    def _lit_heartbeat():
        while not _lit_hb_stop.is_set():
            _lit_hb_stop.wait(15)
            if _lit_hb_stop.is_set():
                break
            try:
                handler.wfile.write(b': heartbeat\n\n')
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break

    _lit_hb_thread = _threading.Thread(target=_lit_heartbeat, daemon=True)
    _lit_hb_thread.start()

    try:
        for event in process_literature_chat_streaming(
            messages, api_key, context=context,
            model=model, base_url=base_url, temperature=temperature,
        ):
            if _lit_hb_stop.is_set():
                break
            ev_name = event.get('event', '')
            ev_data = event.get('data', '')
            try:
                handler.wfile.write(f"event: {ev_name}\ndata: {ev_data}\n\n".encode())
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
    except Exception as e:
        try:
            handler.wfile.write(f"event: error\ndata: {json.dumps({'error': str(e)[:200]})}\n\n".encode())
        except Exception:
            pass
    finally:
        _lit_hb_stop.set()
        _lit_hb_thread.join(timeout=3)
        try:
            handler.connection.shutdown(_socket.SHUT_WR)
        except (OSError, AttributeError):
            try:
                handler.connection.close()
            except (OSError, AttributeError):
                pass


def handle_fetch_llm_models(handler, data):
    """POST /api/llm/fetch-models — fetch available models from provider."""
    import subprocess as _sp, json as _json
    bu = (data.get('base_url') or '').rstrip('/')
    ak = data.get('api_key', '')
    models = []

    try:
        if 'localhost' in bu or '127.0.0.1' in bu:
            # Use subprocess to isolate from any server env proxy issues
            raw = _sp.check_output(
                ['python3', '-c',
                 'import urllib.request,json,os;'
                 'os.environ.pop("http_proxy",None);os.environ.pop("https_proxy",None);'
                 'r=urllib.request.urlopen("http://localhost:11434/api/tags",timeout=5);'
                 'd=json.loads(r.read());print(json.dumps(d))'],
                timeout=10, stderr=_sp.DEVNULL)
            raw_data = _json.loads(raw.decode())
            for m in raw_data.get('models', []):
                n = m['name']
                if any(x in n for x in ('embedding', 'embed', 'mxbai')):
                    continue
                models.append({'name': n, 'size_gb': round(m['size']/1024/1024/1024, 1)})
        elif ak:
            import urllib.request as _ur
            is_ant = 'anthropic' in bu
            url = f'{bu}/v1/models' if is_ant else f'{bu}/models'
            hdrs = {'x-api-key': ak} if is_ant else {'Authorization': f'Bearer {ak}'}
            r = _ur.urlopen(_ur.Request(url, headers=hdrs), timeout=10)
            raw = _json.loads(r.read())
            for m in raw.get('data', []):
                models.append({'name': m.get('id', m.get('name', '?'))})
    except Exception as e:
        print(f'[fetch-models] {e}')
    handler._json({'models': models})


# ─── Results file serving ─────────────────────────────────────
def handle_results_list(handler, q):
    """List and serve result files (Venn diagrams, plots, etc.)"""
    fn = q.get('file', '') if isinstance(q, dict) else (q.strip('/') if q else '')
    if fn:
        fp = RESULTS_DIR / fn
        if not fp.is_file():
            handler._send_error('File not found')
            return
        mime = mimetypes.guess_type(str(fp))[0] or 'application/octet-stream'
        handler.send_response(200)
        handler.send_header('Content-Type', mime)
        handler.send_header('Cache-Control', 'max-age=3600')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        with open(fp, 'rb') as f:
            handler.wfile.write(f.read())
        return
    # List files
    files = []
    if RESULTS_DIR.is_dir():
        for f in sorted(RESULTS_DIR.iterdir()):
            if f.suffix in ('.png', '.jpg', '.csv', '.pdf'):
                files.append({'name': f.name, 'size': f.stat().st_size, 'url': f'/api/results/{f.name}'})
    handler._json({'files': files, 'n_files': len(files)})


# ─── Online user tracking ────────────────────────────────────

def handle_heartbeat(handler, q):
    session_id = q.get('session_id', '') if isinstance(q, dict) else str(q)
    if session_id:
        heartbeat(session_id)
    handler._json({'ok': True})


def handle_online_count(handler, q):
    handler._json({'count': count_online()})


# ─── Route table ──────────────────────────────────────────────
def handle_cell_types(handler, q):
    """Return unique CellType values for a dataset."""
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    try:
        import anndata
        adata = get_adata(str(real_path))
        ct_col = 'CellType' if 'CellType' in adata.obs.columns else (list(adata.obs.columns)[0] if len(adata.obs.columns) else '')
        if ct_col:
            types = sorted(set(str(v) for v in adata.obs[ct_col].values))
        else:
            types = []
        handler._json({'cell_types': types})
    except Exception as e:
        handler._send_error(str(e))


def handle_raw_expression(handler, data):
    """Download raw expression data as CSV.

    POST body: { real_path, genes (comma-sep), cell_types (comma-sep) }
    Returns CSV with Content-Disposition attachment.
    """
    real_path_str = (data or {}).get('real_path', '')
    genes_str = (data or {}).get('genes', '')
    cell_types_str = (data or {}).get('cell_types', '')

    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return

    csv = _get_raw_expression(str(real_path), genes_str, cell_types_str)

    if csv.startswith('error\t'):
        handler._send_error(csv[6:])
        return

    csv_bytes = csv.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/csv; charset=utf-8')
    handler.send_header('Content-Length', str(len(csv_bytes)))
    handler.send_header('Content-Disposition', 'attachment; filename="raw_expression.csv"')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(csv_bytes)


ROUTES = {
    ('POST', '/api/heartbeat'): handle_heartbeat,
    ('GET', '/api/online-count'): handle_online_count,
    ('GET', '/api/datasets'): handle_datasets,
    ('GET', '/api/search'): handle_search,
    ('GET', '/api/tissues'): handle_tissues,
    ('GET', '/api/stats'): handle_stats,
    ('GET', '/api/log'): handle_log,
    ('GET', '/api/analysis-info'): handle_analysis_info,
    ('GET', '/api/umap-data'): handle_umap_data,
    ('GET', '/api/search-genes'): handle_search_genes,
    ('GET', '/api/expression-stats'): handle_expression_stats,
    ('GET', '/api/per-sample-table'): handle_per_sample_table,
    ('GET', '/api/per-sample-mutest'): handle_per_sample_mutest,
    ('GET', '/api/aggregate-table'): handle_aggregate_table,
    ('GET', '/api/plot'): handle_plot,
    ('GET', '/api/composition-plot'): handle_composition_plot,
    ('GET', '/api/cell-ratio-plot'): handle_cell_ratio_plot,
    ('GET', '/api/umap-ratio-plots'): handle_umap_ratio_plots,
    ('GET', '/api/marker-dotplot'): handle_marker_dotplot,
    ('GET', '/api/skills'): handle_skills_list,
    ('GET', '/api/skills/content'): handle_skill_content,
    ('POST', '/api/llm/chat'): handle_llm_chat,
    ('POST', '/api/llm/chat/stream'): handle_llm_chat_stream,
    ('POST', '/api/llm/literature/stream'): handle_llm_literature_stream,
    ('POST', '/api/llm/fetch-models'): handle_fetch_llm_models,
    ('POST', '/api/milestone'): handle_milestone,
    ('GET', '/api/skill-plot'): handle_get_skill_plot,
    ('GET', '/api/results'): handle_results_list,
    ('POST', '/api/raw-expression'): handle_raw_expression,
    ('GET', '/api/cell-types'): handle_cell_types,
    ('GET', '/api/bulk-boxplot'): handle_bulk_boxplot,
    ('GET', '/api/bulk-de'): handle_bulk_de,
    ('GET', '/api/bulk-diseases'): handle_bulk_diseases,
    ('GET', '/api/bulk-volcano'): handle_bulk_volcano,
}
