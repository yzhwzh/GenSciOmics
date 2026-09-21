#!/usr/bin/env python3
"""SKILL.md 规格一致性 —— 全仓回归测试。

盯的是「skill 对外宣传的名字」与「真正能查到它的名字」是不是同一个。
GenSci 里有两套并行的 skill 名解析：

  - `skills/_loader.py:scan_skills()` → 取 **frontmatter 的 name**，被
    `agent/prompt.py` 用来生成给模型看的技能列表（「call skill("<name>")」）；
  - `skills/__init__.py:SKILL_REGISTRY` → 键是**目录名**，`SkillTool` 拿 prompt
    给的那个名字来这里查表。

两边不等时，模型看到的名字必然查不到，`skill()` 返回 `{'error': 'Skill not found'}`
—— 而 prompt 里照样列着它、前端也照样显示，**没有任何一处会报错**。这类失败很难
从现象反推回根因，所以只能靠断言钉住。

Anthropic 的 Agent Skills 手册与 Claude Code 都要求 `name` 等于所在目录名：
Claude Code 只把 frontmatter 的 name 当 displayName，正式名始终取目录名
（`08.claude-code-source` 的 `loadSkillsDir.ts:452`）。仓库里 drug-* 早就有了这条
断言（`test_drug_stages.py`），本文件把它推广到**全部** skill，并补上手册的其余
硬性约束（kebab-case、长度上限、description 上限、保留字）。

第 6 节是**契约级**断言，比逐字校验更接近问题本质：它直接调生产用的
`scan_skills()` 与 `SKILL_REGISTRY`，而不是在测试里复刻一份规则 —— 复刻的那份
永远陪着自己写的规则，测不到真正在跑的代码（同 `test_handler_post_routes.py`
把 `post_route_delivers_json_body()` 抽出去给测试直接调用的理由）。

运行：python3 server/tests/test_skill_spec_conformance.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = SERVER_DIR / 'skills'

sys.path.insert(0, str(SERVER_DIR))

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        PASS.append(label)
        print(f'  ✓ {label}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(label)
        print(f'  ✗ {label}  {detail}')


# ── 手册硬性约束 ────────────────────────────────────────────────
NAME_MAX = 64          # name ≤ 64 字符
DESC_MAX = 1024        # description ≤ 1024 字符
KEBAB = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
# name 里不得出现这两个词（会与产品名混淆）
RESERVED = ('claude', 'anthropic')

# YAML 块标量的裸标记（`|` / `>` / `|-` / `>2` …）。
# 两个生产解析器都是**手写逐行**解析、不是 YAML 解析器，遇到块标量只会把标记本身
# 当值返回 —— 实测 `description: |` 后接 2000 字，解析值是字面串 '|'（长度 1）。
# 于是 DESC_MAX 这条断言会被**恰好绕过**：最想写长描述的人用了最自然的写法，
# 测试反而全绿。所以必须显式识别，否则这条断言是守不住的。
# 只在测试这层识别，**不去改生产解析器** —— 那会动到运行时行为。
BLOCK_SCALAR = re.compile(r'^[|>][0-9+-]*$')

# 详情里最多列几个反例，避免一个坏文件刷屏
SAMPLE = 8


def _brief(items: list[str]) -> str:
    head = items[:SAMPLE]
    tail = f' …共 {len(items)} 个' if len(items) > SAMPLE else ''
    return '; '.join(head) + tail


def run() -> None:
    import skills
    from skills import _loader

    skill_dirs = sorted(d for d in SKILLS_DIR.iterdir()
                        if d.is_dir() and (d / 'SKILL.md').is_file())
    print(f'\n共发现 {len(skill_dirs)} 个带 SKILL.md 的 skill 目录')
    # 目录数一旦变化，下面的比例类结论都要重新看，所以先钉住下界
    check('skill 目录数 ≥ 80（扫描确实扫到了东西）', len(skill_dirs) >= 80,
          f'得到 {len(skill_dirs)}')

    # ── 1. frontmatter 块存在且可解析 ─────────────────────────────
    print('\n[1] frontmatter 块存在且可解析')
    metas: dict[str, dict] = {}
    no_fm: list[str] = []
    for d in skill_dirs:
        meta = _loader.parse_frontmatter((d / 'SKILL.md').read_text(encoding='utf-8'))
        metas[d.name] = meta
        if not meta:
            no_fm.append(d.name)
    check(f'{len(skill_dirs)} 个 SKILL.md 都能解析出 frontmatter', not no_fm,
          f'解析为空: {_brief(no_fm)}')

    # ── 2. name 等于目录名（本文件要抓的那个 bug） ────────────────
    print('\n[2] name 等于目录名')
    missing_name = [n for n, m in metas.items() if not m.get('name', '').strip()]
    check('每个 skill 都写了 name', not missing_name, f'缺 name: {_brief(missing_name)}')

    mismatched = [f'{n}(name={metas[n].get("name", "").strip()!r})'
                  for n in sorted(metas)
                  if metas[n].get('name', '').strip() not in ('', n)]
    check(f'{len(skill_dirs)} 个 skill 的 frontmatter name 都等于所在目录名',
          not mismatched, f'不一致: {_brief(mismatched)}')

    # ── 3. name / description 的规格约束 ─────────────────────────
    print('\n[3] name / description 的规格约束')
    names = [m.get('name', '').strip() for m in metas.values()]
    bad_kebab = [n for n in names if n and not KEBAB.match(n)]
    check('name 均为 kebab-case', not bad_kebab, f'不合规: {_brief(bad_kebab)}')

    too_long = [n for n in names if len(n) > NAME_MAX]
    check(f'name 均 ≤ {NAME_MAX} 字符', not too_long,
          f'超长: {_brief([f"{n}({len(n)})" for n in too_long])}')

    reserved = [n for n in names if any(r in n.lower() for r in RESERVED)]
    check('name 不含保留词 claude / anthropic', not reserved, f'命中: {_brief(reserved)}')

    no_desc = [n for n, m in metas.items() if not m.get('description', '').strip()]
    check('每个 skill 都写了 description', not no_desc, f'缺 description: {_brief(no_desc)}')

    desc_long = [f'{n}({len(metas[n]["description"])})' for n in sorted(metas)
                 if len(metas[n].get('description', '')) > DESC_MAX]
    check(f'description 均 ≤ {DESC_MAX} 字符', not desc_long,
          f'超长: {_brief(desc_long)}')

    # 上面那条长度断言的前置条件：值必须真的被解析出来了。用了块标量时解析值是
    # 裸标记 '|'，长度恒为 1 —— 断言会在一条实际超长的 description 上全绿。
    blocky = [f'{n}({metas[n]["description"]!r})' for n in sorted(metas)
              if BLOCK_SCALAR.match(metas[n].get('description', ''))]
    check('description 未用 YAML 块标量（否则上面的长度约束形同虚设）',
          not blocky, f'用了块标量，请改成单行: {_brief(blocky)}')

    # ── 4. disable-model-invocation 取值合法 ─────────────────────
    # Claude Code 支持该字段（loadSkillsDir.ts:255-257），只认布尔。
    # 本仓**尚未实现**它的语义（没有任何代码读它），所以这里只校验取值 ——
    # 不假装它在生效，也不替它做策略决定。
    print('\n[4] disable-model-invocation 取值')
    flag_bad: list[str] = []
    flag_n = 0
    for n, m in sorted(metas.items()):
        if 'disable-model-invocation' not in m:
            continue
        flag_n += 1
        if m['disable-model-invocation'].strip().lower() not in ('true', 'false'):
            flag_bad.append(f'{n}={m["disable-model-invocation"]!r}')
    check('写了 disable-model-invocation 的取值均为 true / false', not flag_bad,
          f'非法: {_brief(flag_bad)}')
    print(f'    （{flag_n} 个 skill 写了该字段；代码目前不消费它）')

    # ── 5. 两套 frontmatter 解析器不漂移 ─────────────────────────
    # 同一种病的第二个实例：_loader.parse_frontmatter 与 skills._parse_frontmatter
    # 是两份独立实现。只要它们对 name/description 的解读一致就不会出事，
    # 但一旦漂移，prompt 与注册表就会各说各话 —— 正是本文件要防的那类 bug。
    print('\n[5] 两套 frontmatter 解析器一致')
    drift: list[str] = []
    for d in skill_dirs:
        text = (d / 'SKILL.md').read_text(encoding='utf-8')
        a = _loader.parse_frontmatter(text)
        b = skills._parse_frontmatter(text)
        for key in ('name', 'description'):
            if a.get(key) != b.get(key):
                drift.append(f'{d.name}.{key}')
    check('_loader 与 skills 两份解析器对 name/description 的解读一致', not drift,
          f'漂移字段: {_brief(drift)}')

    # ── 6. 契约：宣传出去的名字必须查得到 ────────────────────────
    print('\n[6] scan_skills() 宣传的名字都能在 SKILL_REGISTRY 里查到')
    advertised = _loader.scan_skills()
    registry_keys = set(skills.SKILL_REGISTRY)
    unresolvable = sorted({s['name'] for s in advertised} - registry_keys)
    check(f'scan_skills() 的 {len(advertised)} 个名字全部可解析', not unresolvable,
          f'查不到: {_brief([f"{n} → 实际注册键应为目录名" for n in unresolvable])}')

    # 反向看一眼：注册表里的 key 必须都有出处。两种合法出处 —— 同名目录，
    # 或 tools/ 里 @register_skill 注册的函数型工具（shell / skill / tool_search /
    # memory_{read,write,delete} 六个核心工具**本来就没有目录**，这是设计如此）。
    # 两者都不是，才是真正的幽灵条目。
    #
    # 目录基准取 `skills._skills_path` 而不是本文件的 SKILLS_DIR：注册表正是由
    # 前者构建的，用后者比等于拿两个可能各自漂移的来源互校（一旦本文件的常量
    # 写错，会把一整个注册表报成幽灵，而真凶只是一行路径）。
    ghost = sorted(k for k, sd in skills.SKILL_REGISTRY.items()
                   if not (skills._skills_path / k).exists() and sd.func is None)
    check('SKILL_REGISTRY 无既无目录、又非函数型工具的幽灵键', not ghost,
          f'幽灵: {_brief(ghost)}')

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL skill spec CHECK PASSED')


if __name__ == '__main__':
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
