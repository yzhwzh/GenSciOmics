---
name: statistical-analysis
description: "共表达/相关分析(correlation)、找 marker 基因、表达可视化(expression plot)、统计检验(t-test/Mann-Whitney)、导出表格(CSV)、基因功能查询(gene info)、数据集概览(summary)。当用户提到以下关键词时必须使用：共表达、相关性、correlation、marker基因、表达量、boxplot、统计检验、t检验、p值。先调此 skill 获取指令，再通过 shell 执行脚本。"
---

# Statistical Analysis

## Overview

Perform statistical analysis on single-cell data.
**Data path**: from system prompt `Current dataset path:`.
**Output directory**: use `/tmp/gensci_results/` for generated files.

## Critical rules
1. Run the script once. Only the Venn diagram is needed — do not generate boxplots, scatter plots, or any additional charts.
2. Cell type and gene names are auto-resolved by the script.
3. Run: `python3 ${CLAUDE_SKILL_DIR}/scripts/find_related_genes.py <h5ad> <genes> pearson 20 /tmp/gensci_results "<celltype>"`

## 🖼️ Image Display (CRITICAL)
脚本运行后会在 stdout 输出 `![Venn](/api/results?file=xxx.png)` 这样的 markdown 图片标签。
**你必须把这个 markdown 图片标签原样包含在你的回复中，不要改写为文字说明。**
前端的 ChatPanel 使用 ReactMarkdown，会自动渲染图片 `/api/results?file=xxx.png`。
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
**Trigger**: 用户想看多个基因的共表达/相关性/Venn图/UpSet图
**Usage**: `python3 ${CLAUDE_SKILL_DIR}/scripts/find_related_genes.py <data.h5ad> <gene1,gene2,...> [method] [n_top] [outdir] [celltype]`
**Parameters**: `celltype`(可选—只在用户指定时传，不传则分析全部细胞)
**Note**: Only add celltype when the user explicitly requests a specific cell type.

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
