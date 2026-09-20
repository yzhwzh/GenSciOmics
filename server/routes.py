#!/usr/bin/env python3
"""Route table definition and handler functions."""

import json
import os
import sys
import time
import mimetypes
from pathlib import Path
from collections import Counter

from config import DATA_DIRS, RESULTS_DIR

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
from pubmed import _fetch_abstract, cached_abstract
from supplementary import extract_table, is_valid_lookup
from analysis.umap import _get_umap_data
from analysis.expression import _get_expression_stats
from analysis.stats import _get_per_sample_table, _get_per_sample_mutest, _get_aggregate_table, _get_raw_expression
from analysis.plots import _generate_plot, _generate_cell_ratio_plot, _generate_umap_ratio_plots, _generate_celltype_composition, _generate_marker_dotplot
from analysis.utils import CATEGORICAL_PALETTE_MAP, normalize_gene2_op
from analysis.bulk import bulk_boxplot, bulk_de, bulk_diseases, bulk_groups, bulk_volcano
from search import _get_genes, rank_gene_matches
from llm_proxy import process_chat, process_chat_streaming, process_literature_chat_streaming, process_drug_pipeline_streaming
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
    except Exception as e:
        # 不吞：以前这里静默 return None，上层只会回一句笼统的 400
        # "Invalid file path"，于是「路径越界」和「符号链接断了」「路径格式
        # 不合法」在现场完全无法区分。B35 把同一函数链上另一处 except 打开后，
        # 直接揪出了 scanner 快路径从未生效——教训是同一个。
        print(f'[GenSci] validate_real_path failed for {path_str!r}: {type(e).__name__}: {e}',
              file=sys.stderr)
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
    # strip 与 /api/abstract 保持一致 —— 否则 '12345 ' 在一边是缓存键、
    # 在另一边是另一个缓存键，两个端点会各查各的。
    pmid = q.get('pmid', '').strip()
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    cache_key = f'ai:{real_path_str}:{pmid}'
    cached = _analysis_info_cache.get(cache_key)
    if cached:
        # 摘要可能是在这条 _analysis_info_cache 条目**之后**才被抓进来的
        # （/api/abstract 先跑完了）。每次出栈都跟摘要缓存对一次：
        # 否则这里会一直对外报 abstract_ready=False，前端每次访问都得再问一遍。
        ready = cached_abstract(pmid)
        if ready is not None and cached.get('abstract_ready') is not True:
            cached = {**cached, 'abstract': ready, 'abstract_ready': True}
            _analysis_info_cache.set(cache_key, cached)
        handler._json(cached)
        return
    # 摘要只读进程内缓存，**绝不在这里发网络**（BUG_LOG B35）。
    # 这里以前是同步的 _fetch_abstract(pmid)：冷缓存时要经公司代理发 3 次外部
    # HTTP，实测有一次拖到 125s。前端 apiFetch 60s 就 abort，页面于是显示
    # "Failed to load info"，而服务端还在那儿等代理。
    # 现在 stats 立刻返回，摘要由 /api/abstract 另发一次、到了再补。
    # `abstract_ready` 告诉前端「这次带回来的摘要是不是全的」：
    # False 不代表失败，只代表要再问一次 /api/abstract。
    abstract_info = cached_abstract(pmid)
    # Try scanner cache first (fast, no h5ad read)
    stats = None
    try:
        from config import SCANNER_CACHE_FILE
        if SCANNER_CACHE_FILE.exists():
            sc = json.loads(SCANNER_CACHE_FILE.read_text())
            for k, v in sc.items():
                if str(real_path) in k or k.endswith(real_path.name):
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
    except Exception as e:
        # 不吞：scanner 缓存坏了要留痕，否则只是静默退化成读 h5ad，
        # 现场什么都看不到。（CLAUDE.md 设计决策 #4：No silent error swallowing）
        print(f'[GenSci] scanner cache lookup failed for {real_path_str}: {e}', file=sys.stderr)
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
    result = {'pmid': pmid, 'abstract': abstract_info,
              'abstract_ready': abstract_info is not None, 'stats': stats}
    _analysis_info_cache.set(cache_key, result)
    handler._json(result)


def handle_abstract(handler, q):
    """按需抓摘要 —— 全项目**唯一**会为摘要发外部请求的端点。

    与 /api/analysis-info 分开，是因为这两件事的时延差了三个数量级：
    stats 是本地 scanner 缓存（毫秒），摘要要过公司代理发 3 次外部 HTTP
    （实测 4s ~ 125s）。挤在同一个响应里，慢的那一头会把整个页面拖垮，
    而这正是 B35 的成因。
    """
    # 前导/尾随空白必须先去掉再往下走：pmid 会被拼进 URL 也会当缓存键，
    # 没 strip 的话 '12345 ' 是一个「合法」但永远查不到的键 —— 一个输入问题
    # 伪装成网络问题。非数字 ID（PKU/BALF 之类）这里也放行，它们本来就
    # 查不到摘要，_fetch_abstract 会立刻返回空记录。
    pmid = q.get('pmid', '').strip()
    if not pmid:
        handler._send_error('Missing pmid')
        return
    try:
        _fetch_abstract(pmid)   # 总时限 config.ABSTRACT_DEADLINE_S
    except Exception as e:
        # 外部抓取失败不该是 500 —— 页面其余部分（stats）是好的，
        # 摘要退化成「暂时取不到」，且这里必须留痕。
        print(f'[GenSci] abstract fetch failed for {pmid}: {e}', file=sys.stderr)
        handler._json({'pmid': pmid, 'abstract': cached_abstract(pmid), 'abstract_ready': False})
        return
    # abstract_ready 的判据**只有这一个**：记录在不在摘要缓存里。
    # _fetch_abstract 只在记录完整时才写缓存（B26 + 预算跳过），所以
    # 「在缓存里」== 「服务器认为这就是最终答案了，别再问了」。
    # 以前这里另算一遍 `bool(title or abstract or pmcid)`，与
    # /api/analysis-info 的 `cached_abstract(pmid) is not None` 是两个不同的
    # 定义：全文因预算被跳过时，一个说 ready、另一个说 not ready，
    # 前端于是拿着 ready=true 永远不再重取，Methods 与补充材料清单永久缺失。
    ready_info = cached_abstract(pmid)
    handler._json({'pmid': pmid, 'abstract': ready_info, 'abstract_ready': ready_info is not None})


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
    # Exact match first, then the 100-item cap — see rank_gene_matches: the
    # reverse order drops short gene names out of their own result.
    handler._json({'genes': rank_gene_matches(all_genes, query)})


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
    gene2 = q.get('gene2', '') or None
    gene2_label = q.get('gene2_label', '') or None
    # Normalise before the cache key: 'AND' / 'and' / 'and ' must not each mint an entry.
    gene2_op = normalize_gene2_op(q.get('gene2_op', ''))
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not genes_str:
        handler._send_error('genes parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    eff_group = group_col if group_col and group_col != 'None' else ''
    cache_key = f'aggtbl:{real_path_str}:{mtime}:{genes_str}:{eff_group}:{celltype_col}:{gene2 or ""}:{gene2_label or ""}:{gene2_op}'
    cached = _table_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    # When condition is None/empty, pass empty group_col to backend
    result = _get_aggregate_table(str(real_path), genes_str, eff_group, celltype_col,
                                  gene2 or '', gene2_label or '', gene2_op)
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
    gene2_label = q.get('gene2_label', '')
    gene2_op = normalize_gene2_op(q.get('gene2_op', ''))
    palette = get_palette_name(q)
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'comp:{real_path_str}:{mtime}:{gene}:{gene2}:{gene2_label}:{gene2_op}:{palette}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = _generate_celltype_composition(str(real_path), gene, palette, gene2, gene2_label, gene2_op)
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
    target_group = q.get('target_group', '') or None
    # Show-groups subset: optional CSV of Group names to plot (group mode only).
    groups_list = None
    raw_groups = q.get('groups', '')
    if raw_groups.strip():
        groups_list = [g.strip() for g in raw_groups.split(',') if g.strip()] or None
    # Panel x-axis factor: 'Disease' (default) or another obs column like 'Tissue'.
    x_factor = q.get('x_factor', '') or None
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    if not gene:
        handler._send_error('gene parameter required')
        return
    mtime = real_path.stat().st_mtime if real_path.exists() else 0
    cache_key = f'bulkbox:{real_path_str}:{mtime}:{gene}:{disease}:{palette}:{target_group}:{groups_list}:{x_factor}'
    cached = _plot_cache.get(cache_key)
    if cached:
        handler._json(cached)
        return
    result = bulk_boxplot(str(real_path), gene, disease, palette, target_group,
                          groups_list, x_factor)
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


def handle_bulk_groups(handler, q):
    real_path_str = q.get('real_path', '')
    real_path = validate_real_path(real_path_str)
    if not real_path or not real_path.is_file():
        handler._send_error('Invalid file path')
        return
    handler._json(bulk_groups(str(real_path)))




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
    user_id = data.get('user_id', '')

    if not messages:
        handler._send_error('messages required')
        return
    if not real_path:
        handler._send_error('real_path required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    result = process_chat(messages, real_path, api_key, model, base_url, temperature, user_id=user_id)
    handler._json(result)


def _stream_sse_response(handler, events, *, heartbeat_secs: int = 15) -> None:
    """把一个事件迭代器写成 SSE 响应。

    三个流式端点（chat / literature / drug pipeline）共用。它们的响应头、心跳、
    断线处理、异常兜底**逐字相同**，只有产出事件的函数不同 —— 之前是两份 45 行的
    复制粘贴，加到第三份就会开始漂移。

    调用方必须**先把入参校验收完**再调这里：一旦 send_response(200) 发出去了，
    就没法再改成 JSON 错误响应。
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'close')
    handler.send_header('X-Accel-Buffering', 'no')
    origin = handler.headers.get('Origin', '')
    allowed = getattr(handler, '_allowed_origins', [])
    handler.send_header('Access-Control-Allow-Origin', origin if origin in allowed else '')
    handler.end_headers()

    # Heartbeat: send SSE comment every N seconds to keep proxy alive during tool execution
    _hb_stop = _threading.Event()

    def _heartbeat():
        while not _hb_stop.is_set():
            _hb_stop.wait(heartbeat_secs)
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
        for event in events:
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


def handle_llm_chat_stream(handler, data):
    """POST /api/llm/chat/stream — process chat with streaming SSE response."""
    messages = data.get('messages', [])
    real_path = data.get('real_path', '')
    api_key = data.get('api_key', '')
    model = data.get('model', 'deepseek-chat')
    base_url = data.get('base_url', 'https://api.deepseek.com')
    temperature = float(data.get('temperature', 0.7))
    omics_type = data.get('omics_type', '')
    user_id = data.get('user_id', '')

    if not messages:
        handler._send_error('messages required')
        return
    if not real_path:
        handler._send_error('real_path required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    _stream_sse_response(handler, process_chat_streaming(
        messages, real_path, api_key, model, base_url, temperature, omics_type, user_id=user_id))


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
    user_id = data.get('user_id', '')

    if not messages:
        handler._send_error('messages required')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    _stream_sse_response(handler, process_literature_chat_streaming(
        messages, api_key, context=context,
        model=model, base_url=base_url, temperature=temperature,
        user_id=user_id,
    ))


def handle_drug_stages(handler, q):
    """GET /api/drug/stages — 药物流水线的阶段注册表。

    前端据此渲染阶段卡片。返回的是 server/drug_stages.py 里的同一份数据，
    所以加阶段只改那一个文件，前端不用动。
    """
    from drug_stages import stages_payload
    handler._json(stages_payload())


def handle_drug_pipeline_stream(handler, data):
    """POST /api/drug/pipeline/stream — 药物发现流水线（SSE）。

    **不要求 real_path** —— 这是它区别于 /api/llm/chat/stream 的唯一原因：
    药物页默认不挂数据集（直接查靶点/化合物）。agent 侧本来就不需要它
    （prompt.py:270 有 `if real_path:` 守卫）。这里不去放开原端点的校验，
    因为那条校验是给分析页用的，放开会波及 Free Analysis。

    事件：stage_start / message / tool_call / tool_result / status /
          stage_done / error / done（每个事件都带 stage_id）。
    """
    query = data.get('query', '')
    stage_ids = data.get('stage_ids', [])
    api_key = data.get('api_key', '')
    model = data.get('model', 'deepseek-chat')
    base_url = data.get('base_url', 'https://api.deepseek.com')
    temperature = float(data.get('temperature', 0.7))
    real_path = data.get('real_path', '')  # 可选：挂了数据集才有
    user_id = data.get('user_id', '')

    if not (query or '').strip():
        handler._send_error('query required')
        return
    if not isinstance(stage_ids, list) or not stage_ids:
        handler._send_error('stage_ids required (non-empty list)')
        return
    if not api_key and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        handler._send_error('api_key required')
        return

    _stream_sse_response(handler, process_drug_pipeline_streaming(
        query, stage_ids, api_key,
        model=model, base_url=base_url, temperature=temperature,
        real_path=real_path, user_id=user_id,
    ))


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
# 产出目录里允许被 /api/results 直接读走的后缀。列表端点只展示前四个，
# 其余是给「下载报告/表格/导出件」用的。
RESULT_FILE_SUFFIXES = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.csv', '.tsv', '.txt', '.md', '.json',
    '.pdf', '.xlsx', '.xls', '.docx', '.pptx', '.zip', '.html',
})


def _safe_results_path(fn) -> Path | None:
    """把用户传来的 file 参数收敛成产出目录内的真实文件路径，不合法则 None。

    这是安全边界：`RESULTS_DIR / fn` 里的 fn 完全由用户控制，
    `RESULTS_DIR / '../../../etc/passwd'` 会解析到产出目录之外 —— 实测可读
    任意可读文件。所以先 resolve 再断言落在 RESULTS_DIR.resolve() 之内，
    顺带挡住符号链接逃逸；结构上不给穿越留口子，而不是黑名单匹配攻击串。
    """
    if not isinstance(fn, str) or not fn or '\x00' in fn:
        return None
    root = RESULTS_DIR.resolve()
    try:
        p = (root / fn).resolve()
    except (OSError, RuntimeError):
        return None  # 坏路径 / 软链环
    if not p.is_relative_to(root):
        return None
    if not p.is_file():
        return None
    if p.suffix.lower() not in RESULT_FILE_SUFFIXES:
        return None
    return p


def handle_results_list(handler, q):
    """List and serve result files (Venn diagrams, plots, etc.)"""
    fn = q.get('file', '') if isinstance(q, dict) else (q.strip('/') if q else '')
    if fn:
        fp = _safe_results_path(fn)
        if fp is None:
            # 越界与不存在返回同一个响应，不区分，免得这个端点变成探测工具
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


def handle_supplementary_table(handler, q):
    """取出某篇文献补充材料包里的一个附件并解析成表格。

    这是整个功能里**唯一会下载 25–37 MB** 的入口。附件清单走
    /api/analysis-info 免费拿（复用为提取 Methods 已下载的全文 XML），
    只有用户真的点「查看」才走到这里。下过一次就落盘在 .supp_cache/，
    之后同一篇的任意附件都是读磁盘。

    为什么 GET 而不是 POST：无副作用、结果可缓存，且不需要登记
    post_route_delivers_json_body()（上一轮 POST 踩过的坑）。
    """
    pmcid = q.get('pmcid', '').strip()
    name = q.get('name', '').strip()

    # 非法输入回 400，与「下载/解析失败」区分开 —— 后者是正常业务流程
    # （限流、坏文件），用 200 + error 字段让前端统一渲染。
    if not is_valid_lookup(pmcid, name):
        handler._send_error('非法的 pmcid 或附件名')
        return

    handler._json(extract_table(pmcid, name))


ROUTES = {
    ('POST', '/api/heartbeat'): handle_heartbeat,
    ('GET', '/api/online-count'): handle_online_count,
    ('GET', '/api/datasets'): handle_datasets,
    ('GET', '/api/search'): handle_search,
    ('GET', '/api/tissues'): handle_tissues,
    ('GET', '/api/stats'): handle_stats,
    ('GET', '/api/log'): handle_log,
    ('GET', '/api/analysis-info'): handle_analysis_info,
    ('GET', '/api/abstract'): handle_abstract,
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
    ('GET', '/api/drug/stages'): handle_drug_stages,
    ('POST', '/api/drug/pipeline/stream'): handle_drug_pipeline_stream,
    ('POST', '/api/milestone'): handle_milestone,
    ('GET', '/api/skill-plot'): handle_get_skill_plot,
    ('GET', '/api/results'): handle_results_list,
    ('POST', '/api/raw-expression'): handle_raw_expression,
    ('GET', '/api/cell-types'): handle_cell_types,
    ('GET', '/api/bulk-boxplot'): handle_bulk_boxplot,
    ('GET', '/api/bulk-de'): handle_bulk_de,
    ('GET', '/api/bulk-diseases'): handle_bulk_diseases,
    ('GET', '/api/bulk-groups'): handle_bulk_groups,
    ('GET', '/api/bulk-volcano'): handle_bulk_volcano,
    ('GET', '/api/supplementary-table'): handle_supplementary_table,
}
