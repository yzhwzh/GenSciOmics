---
name: statistical-analysis
description: "共表达/相关分析(correlation)、多基因 Venn 图/UpSet 图与共表达组合计数表、找 marker 基因、表达可视化(expression plot)、统计检验(t-test/Mann-Whitney)、导出表格(CSV)、基因功能查询(gene info)、数据集概览(summary)。当用户提到以下关键词时必须使用：共表达、相关性、correlation、Venn图、UpSet图、组合计数、marker基因、表达量、boxplot、统计检验、t检验、p值。先调此 skill 获取指令，再通过 shell 执行脚本。"
---

# Statistical Analysis

## Overview

Perform statistical analysis on single-cell data.
**Data path**: from system prompt `Current dataset path:`.
**Output directory**: use `/tmp/gensci_results/` for generated files.

## Critical rules
1. Run the script once. Only the Venn / UpSet diagram is needed — do not generate boxplots, scatter plots, or any additional charts. （这条禁的是**额外的图**；脚本自己打印的那张共表达组合计数表不是额外的图，必须一并转达，见下节。）
2. Cell type and gene names are auto-resolved by the script.
3. Run: `python3 ${CLAUDE_SKILL_DIR}/scripts/find_related_genes.py <h5ad> <genes> pearson 20 /tmp/gensci_results "<celltype>"`

## 🖼️ Image & Table Display (CRITICAL)
脚本运行后会在 stdout 输出**三样东西**：
- 一个 markdown 图片标签：`![Venn](/api/results?file=xxx.png)` 或 `![UpSet](/api/results?file=upset_xxx.png)`
- 一张 **Markdown 共表达组合计数表**（`| Combination | Cells | % of ... |`）
- 表尾的口径说明行：`Counts overlap (cells expressing all listed genes); UpSet bars show exact combinations.`

**三样都必须原样包含在你的回复中**：
- 图片标签不要改写为文字说明；
- **表格不要改写成散文、不要只挑几个数字复述** —— 整张表照抄；
- **那行口径说明必须一起带上，一个字都不要省。** 表格用的是「重叠计数」
  （`LRP2 + CUBN` = 同时表达这两个的细胞，不管它还表不表达 SLC9A3/SLC5A2），
  UpSet 柱子用的是「互斥组合」（同一根柱还要求其余基因为阴）。两者数字**不相等**，
  这不是算错。少了这行，用户会拿表和柱子对读，然后得出错误结论。

前端的 ChatPanel 使用 ReactMarkdown + remark-gfm，会自动把图片渲染成图、把表格渲染成表。
如果输出了多张图片标记，全部原样传递。

## Available Scripts

### 1. Gene Expression Plot — `expression_plot.py`
**Trigger**: 用户想看某个基因的表达量/表达图/boxplot/barplot
**Usage**:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/expression_plot.py <data.h5ad> <gene> <plot_type> [metric] [condition_col] [palette] [min_cells]
```
**Parameters**: `gene`(必填), `plot_type`(boxplot/barplot/grouped_bar/simple_bar), `metric`(expression_pct/mean_expression), `condition_col`(Group/None), `palette`(default/pastel/bold/nature/tab10), `min_cells`(默认10)
**Output**: stdout 包含 `![gene plot_type](/api/results?file=xxx.png)` 图片标签 + PNG 文件保存到 `/tmp/gensci_results/`

### 2. Marker Genes — `find_marker_genes.py`
**Trigger**: 用户想看每种细胞类型的标记基因
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/find_marker_genes.py <data.h5ad> [groupby] [method] [n_genes]`
**Parameters**: `groupby`(CellType), `method`(cosg/wilcoxon/t-test), `n_genes`(10)
**Output**: 打印 marker 基因列表

### 3. Co-expression — `find_related_genes.py`
**Trigger**: 用户想看多个基因的共表达/相关性/Venn图/UpSet图/组合计数表
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/find_related_genes.py <data.h5ad> <gene1,gene2,...> [method] [n_top] [outdir] [celltype]`
**Parameters**: `celltype`(可选—只在用户指定时传，不传则分析全部细胞)
**Note**: Only add celltype when the user explicitly requests a specific cell type.
**Output**: stdout 包含 `![Venn|UpSet](/api/results?file=xxx.png)` 图片标签 **+ 一张共表达组合计数 Markdown 表格**；两者都要原样转达（见 `## 🖼️ Image & Table Display`）。

**计数口径 = 重叠**：`A + B` 是同时表达 A 和 B 的细胞数，不管该细胞还表不表达 C/D。
这与 2/3 基因的 Venn 交集区口径一致。表格下方会打印一行说明。
（UpSet 的柱子画的是**互斥**组合——`A∩B` 柱还要求"非 C 且非 D"。两者口径不同，不要把表格数字直接对着柱子读。）

**细胞范围**：
- **4 个及以上基因**：一个基因都不表达的细胞会被**整个剔出分析**，表格与表达率的分母是
  "至少表达其中一个基因"的细胞数。脚本会先打印 `Cells expressing ≥1 of N genes: X/Y (Z%) — excluded W expressing none`。
- **2/3 个基因**：不剔细胞，分母是全部细胞（表头写作 `% of all cells`）。

因此 3 基因与 4 基因两次运行的百分比**分母不同**，跨运行比较时以脚本打印的说明行为准。
表格只列 **≥2 个基因**的组合（单基因的表达率已由表格下方的 `基因: n/N (pct%)` 行给出）；
组合数超过 50 种时只列前 50 种，并显式打印 `… and K more combinations (M total).`。

### 4. Gene Info — `gene_info.py`
**Trigger**: 用户想问基因功能/通路
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/gene_info.py <gene1,gene2,...> [species]`
**Output**: 打印基因功能、通路、UniProt

### 5. Dataset Summary — `get_data_summary.py`
**Trigger**: 用户想了解数据集
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/get_data_summary.py <data.h5ad>`
**Output**: 打印细胞数、基因数、细胞类型、样本、分组

### 6. Statistical Tests — `statistical_analysis.py`
**Trigger**: 用户想做两组间统计检验
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/statistical_analysis.py <data.h5ad> <gene> <groupby> [test]`
**Parameters**: `test`(mannwhitneyu/ttest_ind/f_oneway)
**Output**: 打印检验统计量、p值

### 7. Export Tables — `export_tables.py`
**Trigger**: 用户想导出 CSV
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/export_tables.py <data.h5ad> <table_type> [gene]`
**Output**: CSV → `/tmp/gensci_results/`

## Boundary

- 共表达/相关性 → `find_related_genes.py`
- 差异表达(DEG) → 简单两组比较用 `statistical_analysis.py`；完整 DEG 流程调 `omicverse-single-cell-differential-expression`
- 细胞通讯 → 调 `omicverse-single-cell-cellphonedb-communication`
- 轨迹推断 → 调 `omicverse-single-cell-trajectory-inference`
- 基础模型 → 调 `omicverse-single-cell-foundation-model`
