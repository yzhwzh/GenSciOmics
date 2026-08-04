"""Co-expression analysis: single gene correlation table OR multi-gene Venn/UpSet.
Usage: python3 find_related_genes.py <h5ad_path> <gene(s)> [method] [n_top] [outdir] [celltype]
  Single gene: find top correlated genes
  2-3 genes: Venn diagram
  4+ genes: UpSet plot
"""
import sys, os, time, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import pearsonr, spearmanr

_TS = str(int(time.time()))[-6:]  # unique suffix per run


def _resolve_via_mygene(gene_names: list[str], species: str = 'human') -> dict[str, str]:
    """Query mygene.info API to resolve gene aliases to official symbols.
    Returns dict of {original_name: resolved_symbol} for resolved genes.
    硬编码禁令: 基因别名必须通过 API 查询，不能硬编码。
    """
    import urllib.request, json, urllib.parse
    resolved = {}
    unresolved = []
    for g in gene_names:
        q = urllib.parse.quote(g)
        url = f'https://mygene.info/v3/query?q={q}&fields=symbol,alias&species={species}&size=3'
        try:
            resp = urllib.request.urlopen(url, timeout=10)
            hits = json.loads(resp.read()).get('hits', [])
            for hit in hits:
                sym = hit.get('symbol', '')
                if sym and sym.lower() == g.lower():
                    resolved[g] = sym
                    break
                aliases = hit.get('alias', [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                if g in aliases or g.lower() in [a.lower() for a in aliases]:
                    resolved[g] = sym
                    break
            if g not in resolved:
                unresolved.append(g)
        except Exception:
            unresolved.append(g)
    if resolved:
        print(f'Alias resolution (mygene.info):')
        for orig, sym in resolved.items():
            print(f'  {orig} → {sym}')
    return resolved


def _fuzzy_match(name: str, candidates: list[str]) -> list[str]:
    """Find close matches for a gene name — case-insensitive, prefix, substring."""
    name_l = name.lower()
    exact = [c for c in candidates if c.lower() == name_l]
    if exact: return exact
    prefix = [c for c in candidates if c.lower().startswith(name_l) or name_l.startswith(c.lower())]
    if prefix: return prefix[:5]
    substr = [c for c in candidates if name_l in c.lower() or c.lower() in name_l]
    return substr[:5]


def main():
    h5ad_path = sys.argv[1]
    genes = [g.strip() for g in sys.argv[2].split(',')]
    # Smart parameter detection (position-independent)
    method = 'pearson'; n_top = 20; outdir = '/tmp/gensci_results'; celltype = ''
    for a in sys.argv[3:]:
        if a in ('pearson', 'spearman'): method = a
        elif a.isdigit(): n_top = int(a)
        elif a.startswith('/'): outdir = a
        elif a: celltype = a
    os.makedirs(outdir, exist_ok=True)

    import scanpy as sc
    # ── 预验证基因名（只读 var/_index，不加载完整 h5ad） ──
    import h5py
    try:
        with h5py.File(h5ad_path, 'r') as f:
            var_names = [n.decode() if isinstance(n, bytes) else n for n in f['var']['_index'][:]]
    except Exception:
        adata_t = sc.read_h5ad(h5ad_path, backed='r')
        var_names = list(adata_t.var_names)
        adata_t.file.close()

    # Step 1: 找缺失的基因名
    missing = [g for g in genes if g not in var_names]
    valid = [g for g in genes if g in var_names]

    # Step 2: 通过 mygene.info API 解析别名（禁止硬编码）
    if missing:
        print(f'Genes not found in dataset: {", ".join(missing)}')
        alias_map = _resolve_via_mygene(missing)
        for orig, sym in alias_map.items():
            if sym in var_names:
                valid.append(sym)
                missing.remove(orig)
                print(f'  Resolved: {orig} → {sym} (found in dataset)')
            else:
                print(f'  Resolved: {orig} → {sym} (not in dataset)')
        # Step 3: 模糊匹配建议
        still_missing = [g for g in missing if g not in alias_map]
        for g in still_missing:
            hints = _fuzzy_match(g, var_names)
            if hints:
                print(f'  Did you mean `{g}` → {", ".join(hints[:3])}?')
        if not valid:
            print('Error: no valid genes to analyze'); sys.exit(1)
        print(f'Proceeding with: {", ".join(valid)}')
    genes = valid

    adata = sc.read_h5ad(h5ad_path)
    celltype_label = 'Total'
    if celltype:
        ct_col = next((c for c in ['CellType', 'broad_cell_class', 'cell_type'] if c in adata.obs.columns), 'CellType')
        cts = adata.obs[ct_col].unique()
        match = [c for c in cts if celltype.lower() in c.lower()]
        if match:
            celltype = match[0]
        adata = adata[adata.obs[ct_col] == celltype].copy()
        celltype_label = celltype
        print(f'Filtered to {celltype}: {adata.n_obs} cells')
    expr = pd.DataFrame(adata[:, genes].X.toarray() if hasattr(adata[:, genes].X, 'toarray') else np.array(adata[:, genes].X), columns=genes, index=adata.obs_names)
    detected = expr > 0

    # Single gene mode: find top correlated genes (use HVG for speed + quality)
    if len(genes) == 1:
        g = genes[0]
        import scanpy as sc
        hvg = adata.copy()
        sc.pp.highly_variable_genes(hvg, n_top_genes=2000, flavor='seurat', inplace=False)
        hvg_mask = hvg.var['highly_variable'].values
        hvg_mask[list(adata.var_names).index(g)] = True
        idx = np.where(hvg_mask)[0]
        all_expr = adata[:, idx].X.toarray() if hasattr(adata.X, 'toarray') else np.array(adata[:, idx].X)
        cors = []
        for i in range(all_expr.shape[1]):
            r, _ = (pearsonr if method == 'pearson' else spearmanr)(all_expr[:, i], expr[g].values)
            if not np.isnan(r):
                cors.append((abs(r), r, str(adata.var_names[idx[i]])))
        cors.sort(key=lambda x: -x[0])
        print(f'Top {n_top} genes correlated with {g}:')
        for _, r, name in cors[:n_top]:
            print(f'  {name}: r={r:.4f}')
        return

    # Multi-gene: Venn/UpSet only (no correlation table)

    if len(genes) == 2:
        from matplotlib_venn import venn2
        fig, ax = plt.subplots(figsize=(7, 6))
        venn2([set(expr[detected[g]].index) for g in genes], set_labels=genes, ax=ax)
        ax.set_title(f'{celltype_label} (n={adata.n_obs})', fontsize=14, pad=20, fontweight='bold')
        fig.tight_layout()
        fig.savefig(f'{outdir}/venn_{_TS}.png', dpi=200, bbox_inches='tight')
        plt.close()
        fn = f'venn_{_TS}.png'
        print(f'![Venn](/api/results?file={fn})')
        print(f'[Download](/api/results?file={fn})')

    elif len(genes) == 3:
        from matplotlib_venn import venn3
        fig, ax = plt.subplots(figsize=(7.5, 6.5))
        venn3([set(expr[detected[g]].index) for g in genes], set_labels=genes, ax=ax)
        ax.set_title(f'{celltype_label} (n={adata.n_obs})', fontsize=14, pad=20, fontweight='bold')
        fig.tight_layout()
        fig.savefig(f'{outdir}/venn_{_TS}.png', dpi=200, bbox_inches='tight')
        plt.close()
        fn = f'venn_{_TS}.png'
        print(f'![Venn](/api/results?file={fn})')
        print(f'[Download PNG](/api/results?file={fn})')
        for i, g1 in enumerate(genes):
            for g2 in genes[i+1:]:
                print(f'  {g1}+{g2}: {(detected[g1] & detected[g2]).sum()} cells')
        print(f'  All three: {(detected[genes[0]] & detected[genes[1]] & detected[genes[2]]).sum()} cells')

    else:
        try:
            from upsetplot import UpSet, from_memberships
            data = from_memberships([[g for g in genes if detected.loc[i, g]] for i in detected.index])
            if len(data) > 0:
                upset = UpSet(data, subset_size='count', sort_by='cardinality', show_counts=True)
                upset.plot()
                plt.savefig(f'{outdir}/upset_{_TS}.png', dpi=200, bbox_inches='tight')
                plt.close()
                print(f'![UpSet](//api/results?file=upset_{_TS}.png)')
        except ImportError:
            print('Install upsetplot: pip install upsetplot')

    for g in genes:
        n = detected[g].sum()
        print(f'{g}: {n}/{len(expr)} ({100*n/len(expr):.1f}%)')

if __name__ == '__main__':
    main()
