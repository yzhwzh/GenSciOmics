---
name: gh-proteomics-literature-project
description: 用户正在收集 GH(生长激素)相关蛋白质组学文献与公开数据集，偏好药物/治疗相关(如 rhGH、SRL 治疗)。已确认 3 个可下载 PXD 数据集。
type: project
created: 2026-07-31
---

用户需求(2026-07-31)：GH 相关的蛋白质组学数据，最好药物相关，不限定组织/疾病(最初是肠道/IBD 背景，后放宽为任意 GH 相关)。已确认公开数据集：
- PXD052194 (iProX IPX0008783000)：rhGH 干预的垂体切除大鼠肝蛋白质组+磷酸化组，Front Endocrinol 2024, PMID 38836220。PX 页: https://proteomecentral.proteomexchange.org/cgi/GetDataset?ID=PXD052194
- PXD017671 (PRIDE)：GHR 缺失猪(GHR-/-，Laron 综合征模型)肝蛋白质组，Mol Metab 2020, PMID 32277923。FTP: ftp://ftp.pride.ebi.ac.uk/pride/data/archive/2020/03/PXD017671/
- PXD009537 (PRIDE)：GH 转基因 vs 选育大马哈鱼肌肉蛋白质组，J Proteomics 2019, PMID 30153513。FTP: ftp://ftp.pride.ebi.ac.uk/pride/data/archive/2018/09/PXD009537/
药物相关但数据需向作者索取：JCEM 2019 haptoglobin/rhGH (PMID 31215990)、JCEM 2011 低剂量 GH 替代标志物 (PMID 21543428)、EJE 2026 肢端肥大症 SRL 治疗 Olink 靶向蛋白组 (PMID 42120545)、IJMS 2021 rbGH 处理鲷鱼 (PMID 34884912)。
技术要点：PRIDE API v2 端点 https://www.ebi.ac.uk/pride/ws/archive/v2/projects?query=... 可用但相关性差；PX 数据集元数据用 GetDataset?ID=XXX.0-2&outputMode=XML&test=no；全文 PXD 号用 Europe PMC fullTextXML(需 PMCID)。
