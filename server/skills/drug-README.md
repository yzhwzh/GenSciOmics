# drug-* skills 的来源与移植说明

> 本目录下所有 `drug-*` 前缀的 skill 由脚本生成，**请勿手工编辑** ——
> 改动会在下次移植时被覆盖。要改行为请改 `scripts/port_tooluniverse_skills.py`，
> 或改阶段编排 `server/drug_stages.py`。

## 来源

| 项 | 值 |
|---|---|
| 上游项目 | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse)（Zitnik Lab, Harvard） |
| 许可证 | Apache-2.0（上游仓库 https://github.com/mims-harvard/ToolUniverse） |
| 移植版本 | `1.4.0` |
| 上游路径 | `/home/yuanwuzhou/.claude/plugins/cache/tooluniverse/tooluniverse/1.4.0/skills` |
| 生成脚本 | `scripts/port_tooluniverse_skills.py` |

移植 = 拷贝目录 + 在 SKILL.md 的 frontmatter 后插入「⚠️ GenSci 执行适配」头 +
把 frontmatter 的 `name:` 改写为 GenSci 侧的名字。**正文内容未作改动。**

## 清单

| GenSci skill | ToolUniverse 上游 | 随拷文件 |
|---|---|---|
| `drug-target-intelligence` | `tooluniverse-target-research` | 6 个：`EVIDENCE_GRADING.md`, `EXAMPLES.md`, `IMPLEMENTATION.md`, `REFERENCE.md`, … |
| `drug-target-validation` | `tooluniverse-drug-target-validation` | 5 个：`QUICK_START.md`, `REPORT_TEMPLATE.md`, `SCORING_CRITERIA.md`, `SKILL.md`, … |
| `drug-gene-liability` | `tooluniverse-gene-liability` | 1 个：`SKILL.md` |
| `drug-gwas-target` | `tooluniverse-gwas-drug-discovery` | 7 个：`EXAMPLES.md`, `PROCEDURES.md`, `QUICK_START.md`, `REFERENCE.md`, … |
| `drug-network-pharmacology` | `tooluniverse-network-pharmacology` | 8 个：`ANALYSIS_PROCEDURES.md`, `QUICK_START.md`, `REPORT_TEMPLATE.md`, `SCORING_REFERENCE.md`, … |
| `drug-binder-discovery` | `tooluniverse-binder-discovery` | 6 个：`CHECKLIST.md`, `EXAMPLES.md`, `REPORT_TEMPLATE.md`, `SKILL.md`, … |
| `drug-small-molecule` | `tooluniverse-small-molecule-discovery` | 1 个：`SKILL.md` |
| `drug-therapeutic-protein` | `tooluniverse-protein-therapeutic-design` | 6 个：`CHECKLIST.md`, `DESIGN_PROCEDURES.md`, `EXAMPLES.md`, `SKILL.md`, … |
| `drug-gpcr-pharmacology` | `tooluniverse-gpcr-structural-pharmacology` | 1 个：`SKILL.md` |
| `drug-antibody-engineering` | `tooluniverse-antibody-engineering` | 9 个：`.env.template`, `CHECKLISTS.md`, `EXAMPLES.md`, `MANUFACTURING.md`, … |
| `drug-admet` | `tooluniverse-admet-prediction` | 1 个：`SKILL.md` |
| `drug-pharmacokinetics` | `tooluniverse-pharmacokinetics` | 2 个：`SKILL.md`, `scripts/nca_from_csv.py` |
| `drug-interaction` | `tooluniverse-drug-drug-interaction` | 7 个：`.env.template`, `EXAMPLES.md`, `SKILL.md`, `ddi_pipeline.py`, … |
| `drug-chemical-sourcing` | `tooluniverse-chemical-sourcing` | 1 个：`SKILL.md` |
| `drug-mechanism` | `tooluniverse-drug-mechanism-research` | 1 个：`SKILL.md` |
| `drug-pathway-analysis` | `tooluniverse-kegg-disease-drug` | 1 个：`SKILL.md` |
| `drug-regulatory-networks` | `tooluniverse-gene-regulatory-networks` | 1 个：`SKILL.md` |
| `drug-repurposing` | `tooluniverse-drug-repurposing` | 6 个：`EXAMPLES.md`, `PROCEDURES.md`, `REFERENCE.md`, `REPORT_TEMPLATE.md`, … |
| `drug-dose-response` | `tooluniverse-dose-response` | 2 个：`SKILL.md`, `scripts/fit_dose_response.py` |
| `drug-synergy` | `tooluniverse-drug-synergy` | 2 个：`SKILL.md`, `scripts/synergy_reference.py` |
| `drug-enzyme-kinetics` | `tooluniverse-enzyme-kinetics` | 2 个：`SKILL.md`, `scripts/fit_michaelis_menten.py` |
| `drug-cell-line-profiling` | `tooluniverse-cell-line-profiling` | 2 个：`SKILL.md`, `scripts/depmap_gene_dependency.py` |
| `drug-toxicology` | `tooluniverse-toxicology` | 1 个：`SKILL.md` |
| `drug-chemical-safety` | `tooluniverse-chemical-safety` | 5 个：`SKILL.md`, `evidence-grading.md`, `phase-details.md`, `phase-procedures-detailed.md`, … |
| `drug-pharmacovigilance` | `tooluniverse-pharmacovigilance` | 7 个：`CHECKLIST.md`, `EXAMPLES.md`, `REPORT_TEMPLATES.md`, `SIGNAL_ANALYSIS.md`, … |
| `drug-adverse-events` | `tooluniverse-adverse-event-detection` | 5 个：`PHASE_DETAILS.md`, `QUICK_START.md`, `REPORT_TEMPLATE.md`, `SKILL.md`, … |
| `drug-regulatory` | `tooluniverse-drug-regulatory` | 1 个：`SKILL.md` |
| `drug-pharmacogenomics` | `tooluniverse-pharmacogenomics` | 1 个：`SKILL.md` |
| `drug-research` | `tooluniverse-drug-research` | 6 个：`CHECKLIST.md`, `EXAMPLES.md`, `REPORT_GUIDELINES.md`, `REPORT_TEMPLATE.md`, … |

## 未移植的两个上游 skill

`tooluniverse-protein-modification-analysis` 与 `tooluniverse-protein-interactions`
的内容已经在更早一次移植中以 `protein-modification-analysis` / `protein-interactions`
的名字存在于 `server/skills/` 下，重复搬运没有意义。阶段编排直接引用那两个现成目录。

## 重新生成

```bash
# ToolUniverse 升级后重跑（自动取插件缓存里版本号最大的那份）
python3 scripts/port_tooluniverse_skills.py

# 指定源目录 / 只看会做什么
python3 scripts/port_tooluniverse_skills.py --source /path/to/skills --dry-run
```

重跑后必须**重启后端** —— `server/skills/_loader.py` 的 `scan_skills()` 有模块级缓存。
