"""Co-expression analysis: single gene correlation table OR multi-gene Venn/UpSet.
Usage: python3 find_related_genes.py <h5ad_path> <gene(s)> [method] [n_top] [outdir] [celltype]
  Single gene: find top correlated genes
  2-3 genes: Venn diagram + combination table (denominator = all cells)
  4+ genes: UpSet plot + combination table (denominator = cells expressing >=1 gene,
            i.e. cells expressing none of the genes are excluded from the analysis)

组合计数口径 = **重叠**：`A + B` 是同时表达 A 和 B 的细胞数，不管该细胞还表不表达 C/D。
这与 2/3 基因分支原有的 `(detected[g1] & detected[g2]).sum()` 以及 venn2 的交集区一致。
注意 UpSet 的柱子画的是**互斥**组合（`A∩B` 柱 = 还要"非 C 且非 D"），两者口径不同，
输出里有一行说明；不要把表格的数字直接对着柱子读。
"""
import sys, os, time, warnings, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import pearsonr, spearmanr

# 必须压掉 FutureWarning：ShellTool 用 stderr=subprocess.STDOUT 把 stderr 并入 stdout，
# 再只保留**最后 5000 字符**且不留截断标记（server/tools/ShellTool/__init__.py:121-127）。
# upsetplot + pandas 2.3.3 会产生成片的 fillna 降级 / chained assignment 告警，
# 它们既吃满输出预算，又把告警文本挤进 LLM 的上下文里当噪声。
warnings.filterwarnings('ignore', category=FutureWarning)

_TS = str(int(time.time()))[-6:]  # unique suffix per run

# 组合计数表格的行数上限。输出只有 5000 字符预算，且截断不留标记；
# 6 个基因就有 57 种 >=2 的组合，20 个基因理论上百万种。超限必须显式说明，不能静默截断。
_COMBO_TABLE_LIMIT = 50

# 位编码 + 超集 zeta 变换要开一个 2^G 的计数数组。G=20 时是 8MB / 0.03s，
# 再往上内存和时间都开始失控，而 20 个基因以上的 UpSet 本来也读不出东西。
# 超过此值只跳过**表格**，UpSet 照画（它走 from_memberships，代价只与细胞数有关）。
_COMBO_MAX_GENES = 20


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


# ─────────────────────── 组合计数（重叠口径） ───────────────────────

def _overlap_counts(detected: pd.DataFrame, genes: list[str]) -> list[tuple[tuple, int]]:
    """每种 >=2 基因组合的**重叠**细胞数，只列计数 > 0 的，按细胞数降序。

    重叠 = 同时表达该组合**全部**基因的细胞数，不要求其余基因为阴。所以

        A + B  (重叠)  >=  A∩B∩¬C∩¬D  (互斥)

    直接对 `detected` 做位编码只会得到**互斥**分区计数，必须再做一次超集 zeta 变换
    才能累加成重叠数。两步都是 G 次数组运算，没有 Python 层循环：

        exact[code]    = 恰好表达 code 这份组合的细胞数   （互斥，求和 = 细胞数）
        overlap[mask]  = 恰好表达 mask 中全部基因的细胞数 （重叠 = 超集求和）

    zeta 变换在 G 维布尔格上逐维做 `z[...,0,...] += z[...,1,...]`；已与朴素
    `detected.iloc[:, cols].all(axis=1).sum()` 在 G=4..6 上逐条核对相等，
    性能上 G=20 时 0.03s（朴素双重循环要 2.47s）。
    """
    G = len(genes)
    if G > _COMBO_MAX_GENES:
        return []

    vals = detected.values.astype(np.uint64)
    codes = (vals << np.arange(G, dtype=np.uint64)).sum(axis=1)

    exact = np.zeros(1 << G, dtype=np.int64)
    for code, n in pd.Series(codes).value_counts().items():
        exact[int(code)] = int(n)

    z = exact.reshape((2,) * G)
    for i in range(G):
        lo = [slice(None)] * G; lo[i] = 0
        hi = [slice(None)] * G; hi[i] = 1
        z[tuple(lo)] += z[tuple(hi)]
    overlap = z.reshape(-1)

    pos = {g: j for j, g in enumerate(genes)}
    rows = []
    for mask in np.nonzero(overlap)[0]:
        m = int(mask)
        if m == 0:
            continue                                  # 全不表达：已被排除，不该进表
        bits = [j for j in range(G) if m >> j & 1]
        if len(bits) < 2:
            continue                                  # 单基因已由表达率行给出
        rows.append((tuple(genes[j] for j in bits), int(overlap[m])))

    # 细胞数降序；同数时短的（更一般的）组合在前，再按基因出现次序。
    rows.sort(key=lambda t: (-t[1], len(t[0]), tuple(pos[g] for g in t[0])))
    return rows


def _print_combo_table(rows: list[tuple[tuple, int]], denom: int,
                       denom_label: str, limit: int = _COMBO_TABLE_LIMIT) -> None:
    """把组合计数打印成 Markdown 表格（前端 ChatPanel 用 ReactMarkdown + remark-gfm 渲染）。"""
    if not rows:
        print('\nNo cell expresses two or more of these genes simultaneously.')
        return

    shown = rows[:limit]
    width = max(len(' + '.join(c)) for c, _ in shown)
    pct_label = f'% of {denom_label}'
    print()
    print(f'| {"Combination".ljust(width)} | Cells | {pct_label} |')
    # 分隔行宽度对齐表头单元格（含两侧各一个空格），末列用 `:` 标记右对齐
    print(f'|{"-" * (width + 2)}|------:|{"-" * (len(pct_label) + 1)}:|')
    for combo, n in shown:
        pct = (100.0 * n / denom) if denom else 0.0
        print(f'| {" + ".join(combo).ljust(width)} | {n} | {pct:.2f}% |')

    if len(rows) > limit:
        print(f'\n… and {len(rows) - limit} more combinations ({len(rows)} total).')
    print('\nCounts overlap (cells expressing all listed genes); UpSet bars show exact combinations.')


def _print_gene_rates(genes: list[str], detected: pd.DataFrame, denom: int) -> None:
    print()
    for g in genes:
        n = int(detected[g].sum())
        pct = (100.0 * n / denom) if denom else 0.0
        print(f'{g}: {n}/{denom} ({pct:.1f}%)')


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

    # ── Multi-gene: Venn/UpSet + combination table ──
    # 图片/下载链接统一放到最后：ShellTool 的截断是从**前面**砍的，放前面会被先砍掉。
    tail: list[str] = []
    denom = len(expr)          # 2/3 基因的分母＝全部细胞；4+ 分支会改写

    if len(genes) == 2:
        from matplotlib_venn import venn2
        fig, ax = plt.subplots(figsize=(7, 6))
        venn2([set(expr[detected[g]].index) for g in genes], set_labels=genes, ax=ax)
        ax.set_title(f'{celltype_label} (n={adata.n_obs})', fontsize=14, pad=20, fontweight='bold')
        fig.tight_layout()
        fig.savefig(f'{outdir}/venn_{_TS}.png', dpi=200, bbox_inches='tight')
        plt.close()
        fn = f'venn_{_TS}.png'
        _print_combo_table(_overlap_counts(detected, genes), denom, 'all cells')
        tail = [f'![Venn](/api/results?file={fn})', f'[Download](/api/results?file={fn})']

    elif len(genes) == 3:
        from matplotlib_venn import venn3
        fig, ax = plt.subplots(figsize=(7.5, 6.5))
        venn3([set(expr[detected[g]].index) for g in genes], set_labels=genes, ax=ax)
        ax.set_title(f'{celltype_label} (n={adata.n_obs})', fontsize=14, pad=20, fontweight='bold')
        fig.tight_layout()
        fig.savefig(f'{outdir}/venn_{_TS}.png', dpi=200, bbox_inches='tight')
        plt.close()
        fn = f'venn_{_TS}.png'
        _print_combo_table(_overlap_counts(detected, genes), denom, 'all cells')
        tail = [f'![Venn](/api/results?file={fn})', f'[Download PNG](/api/results?file={fn})']

    else:
        # 用户要求：4+ 基因时把"一个基因都不表达"的细胞整个剔出分析。
        # 这不是纯装饰 —— 未过滤时全 False 组合是**计数最大**的一根柱子，
        # 而 sort_by='cardinality' 升序又把它排在最左（实测 200 细胞里 63 个），
        # 真正关心的组合被压到 y 轴底部。
        keep = detected.any(axis=1)
        n_all, n_kept = len(expr), int(keep.sum())
        denom = n_kept
        pct = (100.0 * n_kept / n_all) if n_all else 0.0
        print(f'Cells expressing ≥1 of {len(genes)} genes: {n_kept}/{n_all} ({pct:.1f}%) '
              f'— excluded {n_all - n_kept} expressing none')

        if n_kept == 0:
            print(f'No cell expresses any of the {len(genes)} genes — nothing to plot. '
                  'Check the gene names, or the selected cell type.')
        else:
            detected_kept = detected[keep]

            if len(genes) <= _COMBO_MAX_GENES:
                _print_combo_table(_overlap_counts(detected_kept, genes), denom, 'expressing cells')
            else:
                print(f'\nCombination table skipped: {len(genes)} genes exceed the '
                      f'{_COMBO_MAX_GENES}-gene limit for exhaustive combination counting.')

            # from_memberships 用**实际出现的类别**建索引：过滤后只剩一个基因时
            # 索引只有一层，UpSet 的 subset_size='auto' 会 ValueError。先挡掉。
            present = [g for g in genes if bool(detected_kept[g].any())]
            if len(present) < 2:
                print(f'\nOnly {present[0] if present else "no"} gene(s) are expressed '
                      'in the kept cells — UpSet needs at least two.')
            else:
                try:
                    from upsetplot import UpSet, from_memberships
                    members = [[genes[j] for j in np.flatnonzero(row)]
                               for row in detected_kept.values]
                    data = from_memberships(members)
                    upset = UpSet(data, subset_size='count', sort_by='cardinality', show_counts=True)
                    upset.plot()
                    plt.savefig(f'{outdir}/upset_{_TS}.png', dpi=200, bbox_inches='tight')
                    plt.close()
                    # 单斜杠：`//api/results` 是协议相对 URL，浏览器会去请求主机名 `api`，
                    # 而 ChatPanel 的 markdown components 没有覆盖 img，坏 URL 不会兜底。
                    tail = [f'![UpSet](/api/results?file=upset_{_TS}.png)']
                except ImportError:
                    print('Install upsetplot: pip install upsetplot')

    _print_gene_rates(genes, detected, denom)
    for line in tail:
        print(line)


if __name__ == '__main__':
    main()
