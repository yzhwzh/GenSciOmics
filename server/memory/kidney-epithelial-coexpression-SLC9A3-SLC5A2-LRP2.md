---
name: kidney-epithelial-coexpression-SLC9A3-SLC5A2-LRP2
description: SLC9A3, SLC5A2, LRP2 在肾上皮细胞中的共表达分析结果
type: project
created: 2026-07-13
---

## 项目背景
- 数据集: 35549404.Kidney.Tabula.h5ad (Tabula Sapiens Kidney)
- 细胞类型: kidney epithelial cell (9278 cells)
- 基因: SLC9A3, SLC5A2, LRP2

## 结果
### 表达率
| 基因 | 表达细胞数 | 表达率 |
|------|-----------|--------|
| SLC9A3 | 199/9278 | 2.1% |
| SLC5A2 | 1817/9278 | 19.6% |
| LRP2   | 5965/9278 | 64.3% |

### 共表达率（双基因同时表达）
| 基因对 | 共表达细胞数 | 共表达率 |
|--------|-------------|---------|
| SLC9A3 + SLC5A2 | 56 | 0.60% |
| SLC9A3 + LRP2 | 157 | 1.69% |
| SLC5A2 + LRP2 | 1427 | 15.38% |
| 三基因同时 | 49 | 0.53% |

### 皮尔逊/斯皮尔曼相关性
- SLC9A3 与 SLC5A2: r=0.013 (极弱)
- SLC9A3 与 LRP2: r=0.047 (极弱)
- SLC5A2 与 LRP2: r=0.173 (弱正相关)

输出文件: /tmp/gensci_results/venn_SLC9A3_SLC5A2_LRP2.png, SLC9A3_boxplot.png, SLC5A2_boxplot.png, LRP2_boxplot.png
