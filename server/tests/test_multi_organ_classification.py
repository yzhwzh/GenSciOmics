#!/usr/bin/env python3
"""Multi-organ 数据集的健康/疾病归类 —— 按 PMID 统计，不得重复计数。

起因：Dataset Statistics by Tissue 里 Monkey 显示 `1H · 1D`，Human 的 Tabula
Sapiens 同时进了健康与疾病两栏。查下来是同一个 PMID 被数了两遍：

    Data/Monkey/Lung/Health/scRNA/35831300.Monkey.Lung.h5ad   disease='Health'
    Data/Monkey/Multi-organ/scRNA/35831300.Monkey.h5ad        disease='Multi-organ'

`Multi-organ` 是**组织范围**，不是疾病标签。它之所以出现在 `disease` 字段里，
是 scanner 的 FLAT_TISSUES 分支把组织名**冒充**成了疾病名（该目录在路径里
没有疾病那一级）。而 routes.handle_stats 判健康与否只看 `disease == 'health'`，
于是 'Multi-organ' 落进疾病分支；健康与疾病是两个**独立的 PMID 集合**，同一个
PMID 便两边各算一次。

本脚本锁死两条与标签命名无关的结构性不变量：

  [1] 任何数据集的 `disease` 都不得等于它的 `tissue` —— 组织名不是疾病。
  [2] 同一物种内，一个 PMID 不得同时计入健康与疾病。
      等价说法：健康套数 + 疾病套数 == 该物种的去重 PMID 总数。

[2] 走的是**生产代码本身**（routes.handle_stats），不是复述它的规则，否则
测试只证明复述写对了。

运行：python3 server/tests/test_multi_organ_classification.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

import scanner
from config import DATA_DIRS
from scanner import BULK_CACHE_DIR_NAME, BULK_EXTENSIONS, OMICS_TYPES

PASS: list[str] = []
FAIL: list[str] = []
GAP: list[str] = []


def check(label: str, ok: bool, detail: str = '') -> None:
    (PASS if ok else FAIL).append(label)
    mark = 'PASS' if ok else 'FAIL'
    print(f'  [{mark}] {label}' + (f'\n         {detail}' if detail else ''))


def _collect_rows() -> list[dict]:
    """Path-only walk of the real Data/ tree — same traversal rules as
    scanner.scan_datasets (skip .bulk_cache, dedupe by source path) but without
    the .h5ad reads, since only the path-derived fields are under test."""
    wanted = {'.h5ad'} | set(BULK_EXTENSIONS)
    rows: list[dict] = []
    seen: set[Path] = set()
    for data_dir in DATA_DIRS:
        if not data_dir.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(data_dir):
            dirnames[:] = [d for d in dirnames if d != BULK_CACHE_DIR_NAME]
            for name in filenames:
                f = Path(dirpath) / name
                if not f.is_file() or f.suffix.lower() not in wanted:
                    continue
                if f in seen:
                    continue
                seen.add(f)
                rows.append(scanner._extract_path_fields(f))
    return rows


def main() -> int:
    rows = _collect_rows()
    if not rows:
        print('  Data/ 下没扫到任何数据集 —— 环境不对，测试无意义。')
        return 2
    print(f'\n扫描到 {len(rows)} 条数据集（仅路径字段，未读 .h5ad）\n')

    # ── [1] disease 不得等于 tissue ───────────────────────────────────────
    print('[1] 组织名不得被当作疾病名')
    fabricated = [r for r in rows if r['disease'] == r['tissue']]
    check(
        'no dataset carries a disease equal to its own tissue',
        not fabricated,
        '; '.join(f"{r['species']}/{r['tissue']}/{r['pmid']}" for r in fabricated),
    )

    # ── [2] 生产代码：同一 PMID 不得两边都算 ──────────────────────────────
    print('\n[2] 同一 PMID 不得同时计入健康与疾病（走 routes.handle_stats）')
    import routes

    captured: dict = {}

    class _StubHandler:
        def _json(self, payload):
            captured.update(payload)

    original = routes.datasets
    try:
        routes.datasets = rows
        routes.handle_stats(_StubHandler(), {})
    finally:
        routes.datasets = original

    health = captured.get('species_health_counts', {})
    disease = captured.get('species_disease_counts', {})

    # Denominator computed here, NOT taken from species_dataset_counts: that
    # field is built from `all_ds`, which drops tissue in ('Health','Multi-organ')
    # for the per-tissue breakdown table, while the health/disease tally above
    # runs over the unfiltered list. Comparing the two was apples to oranges —
    # it reported Human 63 != 60 when the true gap was 63 != 62.
    total: dict[str, set] = {}
    for r in rows:
        total.setdefault(r['species'], set()).add(r['pmid'])

    double_counted = []
    for sp in sorted(total):
        h, d, t = health.get(sp, 0), disease.get(sp, 0), len(total[sp])
        if h + d != t:
            double_counted.append(f'{sp}: {h}H + {d}D = {h + d} != {t} unique PMIDs')
    check(
        'health + disease equals unique PMIDs for every species',
        not double_counted,
        '; '.join(double_counted),
    )

    # ── [3] 用户实际看到的那一行 ─────────────────────────────────────────
    print('\n[3] Monkey 的多器官图谱是同一套健康数据')
    monkey_multi = [
        r for r in rows
        if r['species'] == 'Monkey' and r['tissue'] == 'Multi-organ'
    ]
    if not monkey_multi:
        GAP.append('Monkey 多器官数据集不在 Data/ 里 —— 跳过 [3]')
        print('  [GAP] 未找到 Monkey/Multi-organ 数据集')
    else:
        got = {r['disease'] for r in monkey_multi}
        check(
            "Monkey's Multi-organ atlas is labelled Health",
            got == {'Health'},
            f'actual disease label(s): {sorted(got)}',
        )
        # 结构性说法，不是数据快照 —— 将来合法地加一个 Monkey 疾病数据集
        # （换个 PMID）不该让这条失败；只有**同一篇**图谱被劈进两栏才算错。
        # 断言写成「Monkey 疾病数为 0」会随数据增长误报，逼人去削弱守卫。
        atlas_pmids = {r['pmid'] for r in monkey_multi}
        split = sorted(
            p for p in atlas_pmids
            if any(r['species'] == 'Monkey' and r['pmid'] == p
                   and r['disease'].lower() != 'health' for r in rows)
        )
        check(
            "Monkey's Multi-organ atlas is not also counted as a disease",
            not split,
            f'PMID(s) split across both buckets: {split}',
        )
        print(f"         （当前 Monkey: {health.get('Monkey', 0)}H · "
              f"{disease.get('Monkey', 0)}D）")

    # ── [4] 少一级的路径不得把组学名当疾病 ───────────────────────────────
    print('\n[4] 缺疾病层级的路径不得把组学名当成疾病名')
    # 合成路径，不落盘：Multi-organ/Metabolism/x.h5ad 少一个疾病层级，
    # 'Metabolism' 恰好是 OMICS_TYPES 的一员 —— 这正是本次修复的错误类别。
    synthetic = DATA_DIRS[0] / 'Human' / 'Multi-organ' / 'Metabolism' / '00000000.synthetic.h5ad'
    parsed = scanner._extract_path_fields(synthetic)
    check(
        'an omics token in the disease slot is not accepted as a disease label',
        parsed['disease'] not in OMICS_TYPES,
        f"synthetic path -> disease={parsed['disease']!r}, omics_type={parsed['omics_type']!r}",
    )

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed, {len(GAP)} gap')
    if FAIL:
        print('FAILED: ' + '; '.join(FAIL))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
