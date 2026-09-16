#!/usr/bin/env python3
"""药物发现工作台的阶段注册表 —— 单一数据源。

阶段 → skill 的映射只写在这里，不散落到路由、编排、前端任何一处。
前端通过 GET /api/drug/stages 拿到同一份数据来渲染卡片，所以加一个阶段
只改这个文件。

为什么是「阶段」而不是「一个自由对话」：
    用户要的是「按临床前通路，自由勾选要跑哪几段」。每段有明确的输入、
    输出、以及**能力边界**。边界必须跟着阶段走 —— 第 6 段（安评与注册）
    最容易被 LLM 过度承诺成「帮你写 IND」，所以它的 gap 写得最死。
"""

from __future__ import annotations

# ── 常驻 skill：不属任何阶段，每个阶段都可调用 ────────────────────────
# drug-research 是综合药物画像（9 条 research path），当某一阶段需要「这个药
# 到底是什么」的背景时用得上，所以不锁进任何单一段。
DRUG_BASE_SKILLS: list[str] = ['drug-research']


# ── 全局能力边界 ────────────────────────────────────────────────────
# 返回给前端在页面上常驻展示。**这是对用户的承诺边界，不是免责声明** ——
# 每一条都在 2026-09-11 对着 ToolUniverse 1.4.0 的 skill 清单核过：
# 确实没有对应的 skill，不是「藏在某个 skill 里没找到」。
DRUG_CAPABILITY_NOTE = (
    'ToolUniverse 覆盖的是「用公开数据做研究与评估」。以下能力**没有**，'
    '被问到时必须直说做不到，不得编造流程或产出：'
    '① IND/CTA/eCTD 申报文档撰写（drug-regulatory 只查批准状态、橙皮书、NDA/BLA 路径选型，不产申报材料）；'
    '② GLP 毒理试验设计（种属选择、剂量组、终点，毒理 skill 挖的是 AOP/FAERS/标签数据）；'
    '③ CMC／制剂／生产工艺；'
    '④ in-vivo PK/PD、动物药效模型、异速放大；'
    '⑤ 专用 SAR / 多参数先导优化（MPO）。'
)

# 每个阶段都注入的硬规则。
_COMMON_RULES = (
    '【硬性要求】\n'
    '1. 先用 skill 工具读取本阶段列出的 skill 指令，再按其指引调 ToolUniverse 工具取数。'
    '所有数字、ID、结论必须来自实际调用返回，不得凭记忆或常识填充。\n'
    '2. 每一段关键结论后面给出证据来源（数据库名 + 记录 ID / 文献 PMID / 工具名）。\n'
    '3. 本阶段做不到的事，直接写「本阶段无法完成：<原因>」，不要用近似方法假装完成。\n'
    '4. 输出用中文，结构化（小标题 + 表格/列表），不要写成流水账。'
)


DRUG_STAGES: list[dict] = [
    {
        'id': 'target',
        'order': 1,
        'label': '靶点与机制发现',
        'summary': '把你给的靶点/基因摸清楚：组织表达、通路位置、互作网络、变异图谱、可成药性、遗传学证据。',
        'skills': [
            'drug-target-intelligence',
            'drug-target-validation',
            'drug-gene-liability',
            'drug-gwas-target',
            'drug-network-pharmacology',
        ],
        'focus': (
            '本阶段只做靶点发现与验证，不要展开化合物设计。'
            '给出：该靶点的生物学画像、已上市/在研药物情况、可成药性判断（GO / NO-GO / 有条件 GO）、'
            '以及支持与反对继续推进的关键证据各若干条。'
            '用 drug-gene-liability 的结果说明抑制/敲除该靶点可能带来的人体安全风险。'
        ),
        'gap': (
            '不做湿实验验证方案设计（CRISPR 敲除策略、抗体筛选流程）；'
            '靶点优先级排序依据的是公开证据，不含任何内部实验数据。'
        ),
    },
    {
        'id': 'design',
        'order': 2,
        'label': '药物设计',
        'summary': '针对靶点产生候选分子：小分子、结合物、多肽/蛋白药、抗体，以及 GPCR 结构药理学分析。',
        'skills': [
            'drug-binder-discovery',
            'drug-small-molecule',
            'drug-therapeutic-protein',
            'drug-gpcr-pharmacology',
            'drug-antibody-engineering',
        ],
        'focus': (
            '本阶段只产生**计算层面的候选**。'
            '根据靶点类型（小分子可及 / 需要生物药）选择合适的设计路径，'
            '给出候选清单：已知活性化合物、可改造的先导、或从头设计序列/骨架，'
            '每个候选标注来源（ChEMBL / PDB / 文献）与已知活性数据。'
        ),
        'gap': (
            '产出的是计算候选，不合成化合物、不做湿实验筛选、不做对接后的实验验证；'
            '设计的序列/结构未经表达纯化验证。'
        ),
    },
    {
        'id': 'optimize',
        'order': 3,
        'label': '分子优化',
        'summary': '对候选分子做 ADMET 预测、药代性质评估、药物相互作用筛查、以及可采购性核对。',
        'skills': [
            'drug-admet',
            'drug-pharmacokinetics',
            'drug-interaction',
            'drug-chemical-sourcing',
        ],
        'focus': (
            '对上一阶段（或用户指定）的候选分子逐个评估：'
            'ADMET 各项性质、类药性、代谢与转运体、DDI 风险、是否可采购/是否已有库存。'
            '输出一张**多参数对照表**（每行一个分子），并给出哪些分子应当淘汰、为什么。'
            '任何一项 FAIL（hERG / AMES / DILI）都按程序性风险处理，不要用其他项的优良来抵消。'
        ),
        'gap': (
            '基于公开数据与经验模型的**预测**（ADMET-AI / SwissADME 属计算预测级证据），'
            '不能替代实测 PK 与毒理；没有 in-vivo PK/PD、动物药效、异速放大能力。'
            '没有专用的 SAR / MPO 打分器，「多参数优化」是综合各 skill 结果后的判断。'
        ),
    },
    {
        'id': 'mechanism',
        'order': 4,
        'label': '机制深化',
        'summary': '药物怎么起作用的：作用机制、通路上下游、疾病-药物网络、老药新用、翻译后修饰层面的影响。',
        'skills': [
            'drug-mechanism',
            'drug-pathway-analysis',
            'drug-regulatory-networks',
            'drug-repurposing',
            'protein-modification-analysis',
        ],
        'focus': (
            '把「靶点被调控之后会发生什么」讲清楚：分子机制、所在通路、上下游影响、'
            '转录/翻译后层面的后果。'
            '如果该药物或同类药物存在已知的其他适应症，用 drug-repurposing 评估新适应症机会。'
            '明确区分「文献已证实的机制」与「基于通路推演的可能机制」。'
        ),
        'gap': '',
    },
    {
        'id': 'efficacy',
        'order': 5,
        'label': '药效确证',
        'summary': '剂量-反应关系、联合用药协同（Bliss/HSA/Loewe/ZIP）、酶动力学、细胞系层面的应答谱。',
        'skills': [
            'drug-dose-response',
            'drug-synergy',
            'drug-enzyme-kinetics',
            'drug-cell-line-profiling',
        ],
        'focus': (
            '用公开的体外/临床数据回答有效性：'
            '剂量-反应曲线与 EC50/IC50 落在什么区间、与同类药相比如何、'
            '联合用药是否协同（给出协同评分模型与数值）、'
            '哪些细胞系/模型对该干预敏感、哪些耐药。'
            '结论要能回答「值不值得进下一步」这个问题。'
        ),
        'gap': (
            '基于公开的体外与临床数据做计算与评估；'
            '不做动物药效模型拟合、不做体内 PD 标志物分析、不做异速放大。'
        ),
    },
    {
        'id': 'safety',
        'order': 6,
        'label': '安评与注册情报',
        'summary': '安全性情报（AOP/FAERS/标签/毒理基因组）、药物警戒信号、不良反应、药物基因组学、已上市同类药的监管状态与路径。',
        'skills': [
            'drug-toxicology',
            'drug-chemical-safety',
            'drug-pharmacovigilance',
            'drug-adverse-events',
            'drug-regulatory',
            'drug-pharmacogenomics',
        ],
        'focus': (
            '给出安全性画像与监管情报：'
            '已知毒性终点（肝/心/肾等）及其证据强度、FAERS 与标签中的不良反应信号、'
            '药物基因组学层面的用药提示、'
            '同类药在 FDA/EMA 的批准状态与所走的监管路径（NDA/BLA/加速批准等）。'
            '报告里必须写明适用市场（美国 / 欧盟），不要把两者的状态混为一谈。'
        ),
        # 这一段最容易被过度承诺成「帮你写 IND」，所以 gap 写得最死。
        'gap': (
            '本阶段**只做安全情报与监管情报**。'
            '不做 IND/CTA/eCTD 申报文档撰写、不做 GLP 毒理试验设计（种属、剂量组、终点选择）、'
            '不做 CMC/制剂、不做临床方案设计。'
            'drug-regulatory 产出的是「批准状态 + 监管路径选型」，不是申报材料 —— '
            '被要求写申报文档时，直接说明超出范围。'
        ),
    },
]

# ── 派生量 ──────────────────────────────────────────────────────────

# 每次从注册表派生而不是手写第二份，避免两处不一致。
STAGE_IDS: tuple[str, ...] = tuple(s['id'] for s in DRUG_STAGES)


def get_stage(stage_id: str) -> dict | None:
    return next((s for s in DRUG_STAGES if s['id'] == stage_id), None)


def skills_filter_for(stage: dict) -> list[str]:
    """该阶段在系统提示词里可见的 skill 名单（本阶段 skill + 常驻 skill）。

    `_match_filter` 支持精确名匹配，所以直接给名单，不加通配符 ——
    用 `drug-*` 会把 29 个 skill 全放开，阶段锁定就失去意义了。
    """
    return list(stage['skills']) + list(DRUG_BASE_SKILLS)


def resolve_stages(stage_ids) -> tuple[list[dict], list[str]]:
    """把前端传来的 id 列表解析成按 order 排好序的阶段。

    - 顺序无关：传 ['safety','target'] 得到 target → safety
    - 去重：同一个 id 传两次只跑一次
    - 未知 id 不静默丢弃，收进第二个返回值让调用方报错

    返回 (stages, unknown_ids)。stages 是新列表，不改 DRUG_STAGES 里的对象。
    """
    unknown, seen, picked = [], set(), []
    for sid in stage_ids or []:
        if sid in seen:
            continue
        seen.add(sid)
        st = get_stage(sid)
        if st is None:
            unknown.append(sid)
        else:
            picked.append(st)
    picked.sort(key=lambda s: s['order'])
    return picked, unknown


# ── 阶段消息组装 ────────────────────────────────────────────────────

# 前序阶段结论带进下一阶段的预算。6 段串行时这是唯一会累积的量：
# 每段一次完整 ReAct 循环，原始工具输出有几十 KB，全带进去会撑爆上下文，
# 所以只带每段的**最终回复文本**，且总预算封顶。
_PRIOR_STAGE_BUDGET = 6000
_PRIOR_PER_STAGE_BUDGET = 2500
_TRIM_HEAD_RATIO = 0.6


def _trim(text: str, limit: int) -> str:
    """超长时保留头尾、中间省略。头比尾多留一点 —— 结论与小标题通常在前半。

    不做「取最后 N 字符」：那样会把标题和小标题切掉，留下一段没头没尾的正文。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    head = int(limit * _TRIM_HEAD_RATIO)
    tail = limit - head
    omitted = len(text) - head - tail
    return f'{text[:head]}\n\n…（此处省略 {omitted} 字符）…\n\n{text[-tail:]}'


def build_stage_message(stage: dict, query: str,
                        prior_summaries: list[tuple[str, str]] | None = None) -> str:
    """组装送给某一阶段的 user message。

    prior_summaries: [(阶段 label, 该阶段最终回复文本), ...]，按执行顺序。
    """
    parts = ['【任务】', query.strip(), '',
             f'【当前阶段 {stage["order"]}/6：{stage["label"]}】', stage['focus']]

    if stage.get('gap'):
        parts += ['', f'【本阶段能力边界】{stage["gap"]}']

    if prior_summaries:
        parts += ['', '【前序阶段结论（供参考，不要照抄复述）】']
        budget = _PRIOR_STAGE_BUDGET
        for label, text in prior_summaries:
            if budget <= 0:
                parts.append(f'- （{label}：因上下文预算已省略）')
                continue
            chunk = _trim(text, min(_PRIOR_PER_STAGE_BUDGET, budget))
            budget -= len(chunk)
            parts.append(f'### {label}')
            parts.append(chunk)
        parts.append('若前序结论与本阶段新取到的数据冲突，以本阶段实际调用的结果为准，并指出冲突。')

    parts += ['', _COMMON_RULES]
    return '\n'.join(parts)


def stages_payload() -> dict:
    """GET /api/drug/stages 的响应体。字段名与前端 DrugStage 类型一一对应。"""
    return {
        'stages': [
            {
                'id': s['id'],
                'order': s['order'],
                'label': s['label'],
                'summary': s['summary'],
                'skills': list(s['skills']),
                'gap': s['gap'],
            }
            for s in DRUG_STAGES
        ],
        'baseSkills': list(DRUG_BASE_SKILLS),
        'capabilityNote': DRUG_CAPABILITY_NOTE,
    }
