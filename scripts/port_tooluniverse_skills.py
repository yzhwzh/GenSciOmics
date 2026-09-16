#!/usr/bin/env python3
"""把 ToolUniverse 的 skill 目录移植进 GenSci。

用法:
    python3 scripts/port_tooluniverse_skills.py                       # 全部移植
    python3 scripts/port_tooluniverse_skills.py --only target-research
    python3 scripts/port_tooluniverse_skills.py --dry-run
    python3 scripts/port_tooluniverse_skills.py --source /path/to/skills --force

为什么要有这个脚本（而不是手工拷）：
    移植动作 = 拷目录 + 改 frontmatter 的 name + 前置「GenSci 执行适配」头。
    这三步手工做 29 遍必然漂移。ToolUniverse 升级后本脚本可以原样重跑，
    产出与首次一致；改了映射关系也只改下面的 MANIFEST。

源目录解析顺序（都不硬编码机器路径）:
    --source 参数  >  环境变量 TOOLUNIVERSE_SKILLS_DIR  >  ~/.claude/plugins/cache/
    tooluniverse/tooluniverse/<版本>/skills（取版本号最大的那个）
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = PROJECT_ROOT / 'server' / 'skills'

# 上游默认落点：Claude Code 的插件缓存。版本目录由 _default_source() 挑最新。
PLUGIN_CACHE = Path.home() / '.claude' / 'plugins' / 'cache' / 'tooluniverse' / 'tooluniverse'

# 移植后在 SKILL.md 中作为「已由本脚本生成」的判据。改这句话会让 --force 判断失效，
# 因为旧的产出会认不出来（届时需要 --force 一次性重建）。
ADAPT_HEADER_MARK = '⚠️ GenSci 执行适配'

# 与 server/skills/bulk-* 保持逐字一致 —— 那批是同一套移植流程的上一批产物。
ADAPT_HEADER = f"""> **{ADAPT_HEADER_MARK}**（GenSci 自动注入）
> 本 skill 源自 ToolUniverse。在 GenSci 中执行方式：
> - **调 ToolUniverse 工具**：文档里的 `tu run X` / `X(...)` 形式，统一改用 MCP 工具 `mcp__tooluniverse__execute_tool`，参数 `tool_name="X"`、`arguments=<原 JSON>`。
> - **找工具**：不确定工具名时用 `mcp__tooluniverse__find_tools`（query 用自然语言描述）。
> - **计算/统计**：用 `shell` 工具跑 Python/R（pandas/scipy/matplotlib 等）。
> - **本地脚本**：本 skill 的 `scripts/` 已随拷贝就位，用 `python <scripts_dir>/xxx.py` 调用（scripts_dir 见 skill 元信息）。
"""

# ── 移植清单 ────────────────────────────────────────────────────────────
# (ToolUniverse 上游目录名去掉 tooluniverse- 前缀, GenSci 落点目录名)
#
# 不移植的两个上游 skill 及原因：tooluniverse-protein-modification-analysis 与
# tooluniverse-protein-interactions 的内容已经以 protein-modification-analysis /
# protein-interactions 的名字在 server/skills/ 下存在（更早一次移植），重复搬没有意义。
# 阶段 4 直接引用那两个现成目录。
MANIFEST: list[tuple[str, str]] = [
    # 1 靶点与机制发现
    ('target-research', 'drug-target-intelligence'),
    ('drug-target-validation', 'drug-target-validation'),
    ('gene-liability', 'drug-gene-liability'),
    ('gwas-drug-discovery', 'drug-gwas-target'),
    ('network-pharmacology', 'drug-network-pharmacology'),
    # 2 药物设计
    ('binder-discovery', 'drug-binder-discovery'),
    ('small-molecule-discovery', 'drug-small-molecule'),
    ('protein-therapeutic-design', 'drug-therapeutic-protein'),
    ('gpcr-structural-pharmacology', 'drug-gpcr-pharmacology'),
    ('antibody-engineering', 'drug-antibody-engineering'),
    # 3 分子优化
    ('admet-prediction', 'drug-admet'),
    ('pharmacokinetics', 'drug-pharmacokinetics'),
    ('drug-drug-interaction', 'drug-interaction'),
    ('chemical-sourcing', 'drug-chemical-sourcing'),
    # 4 机制深化
    ('drug-mechanism-research', 'drug-mechanism'),
    ('kegg-disease-drug', 'drug-pathway-analysis'),
    ('gene-regulatory-networks', 'drug-regulatory-networks'),
    ('drug-repurposing', 'drug-repurposing'),
    # 5 药效确证
    ('dose-response', 'drug-dose-response'),
    ('drug-synergy', 'drug-synergy'),
    ('enzyme-kinetics', 'drug-enzyme-kinetics'),
    ('cell-line-profiling', 'drug-cell-line-profiling'),
    # 6 安评与注册情报
    ('toxicology', 'drug-toxicology'),
    ('chemical-safety', 'drug-chemical-safety'),
    ('pharmacovigilance', 'drug-pharmacovigilance'),
    ('adverse-event-detection', 'drug-adverse-events'),
    ('drug-regulatory', 'drug-regulatory'),
    ('pharmacogenomics', 'drug-pharmacogenomics'),
    # 常驻（所有阶段都可用）
    ('drug-research', 'drug-research'),
]

_IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store')

_FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?)\n---\s*\n', re.DOTALL)


class PortError(Exception):
    """可预期的移植失败（而非编程错误）——调用方打印后以非零码退出。"""


def _default_source() -> Path:
    """插件缓存里版本号最大的那个 skills/ 目录。"""
    if not PLUGIN_CACHE.is_dir():
        raise PortError(
            f'找不到 ToolUniverse 插件缓存: {PLUGIN_CACHE}\n'
            '用 --source 指定 skills 目录，或设环境变量 TOOLUNIVERSE_SKILLS_DIR。'
        )
    versions = [p for p in PLUGIN_CACHE.iterdir() if (p / 'skills').is_dir()]

    def _ver_key(p: Path) -> tuple:
        # 只按数字段比较，非数字段退化为 0，避免 '1.10.0' < '1.9.0' 这类字符串排序错误。
        return tuple(int(x) if x.isdigit() else 0 for x in re.split(r'[._-]', p.name))

    if not versions:
        raise PortError(f'{PLUGIN_CACHE} 下没有含 skills/ 的版本目录')
    return max(versions, key=_ver_key) / 'skills'


def _resolve_source(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser()
        if not p.is_dir():
            raise PortError(f'--source 不存在或不是目录: {p}')
        # 传进来的可能是版本目录而不是 skills/，两边都认
        return p / 'skills' if (p / 'skills').is_dir() else p
    env = os.environ.get('TOOLUNIVERSE_SKILLS_DIR')
    if env:
        p = Path(env).expanduser()
        if not p.is_dir():
            raise PortError(f'TOOLUNIVERSE_SKILLS_DIR 不存在或不是目录: {p}')
        return p
    return _default_source()


def _upstream_version(source: Path) -> str:
    """从 <...>/tooluniverse/<版本>/skills 反推版本号；推不出来就记 'unknown'。"""
    return source.parent.name if source.name == 'skills' else 'unknown'


def _rewrite_skill_md(text: str, upstream: str, local: str) -> str:
    """改 frontmatter 的 name、在 frontmatter 之后插入适配头。

    上游正文里若引用自己的 `tooluniverse-X` 名字，那些引用**保留原样** ——
    它们只是文档措辞，真正决定 GenSci 侧身份的是 frontmatter 的 name。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise PortError('SKILL.md 没有 frontmatter，无法改写 name')

    front = m.group(1)
    body = text[m.end():]

    new_front, n = re.subn(
        r'^(name\s*:\s*).*$',
        lambda mm: mm.group(1) + local,
        front,
        count=1,
        flags=re.MULTILINE,
    )
    if n == 0:
        # 上游若省略 name，_loader 会退回目录名 —— 落点目录名已经是 local，行为一致。
        new_front = f'name: {local}\n{front}'

    return f'---\n{new_front}\n---\n\n{ADAPT_HEADER}\n{body.lstrip(chr(10))}'


def _already_generated(dest: Path) -> bool:
    md = dest / 'SKILL.md'
    return md.is_file() and ADAPT_HEADER_MARK in md.read_text(encoding='utf-8', errors='replace')


def port_one(source: Path, dest_root: Path, upstream: str, local: str,
             *, force: bool, dry_run: bool) -> dict:
    src = source / f'tooluniverse-{upstream}'
    if not src.is_dir():
        raise PortError(f'上游目录不存在: {src}')
    if not (src / 'SKILL.md').is_file():
        raise PortError(f'上游目录没有 SKILL.md: {src}')

    dest = dest_root / local
    if dest.exists() and not force and not _already_generated(dest):
        # 防的是「覆盖一份手写的、或别人移植的 skill」。本脚本自己的产物认得出来，可重复覆盖。
        raise PortError(
            f'{dest} 已存在且不是本脚本生成的（缺「{ADAPT_HEADER_MARK}」标记）。'
            '确认要覆盖请加 --force。'
        )

    files = [p for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, dirs_exist_ok=True, ignore=_IGNORE)
        skill_md = dest / 'SKILL.md'
        skill_md.write_text(
            _rewrite_skill_md(skill_md.read_text(encoding='utf-8'), upstream, local),
            encoding='utf-8',
        )

    return {
        'upstream': f'tooluniverse-{upstream}',
        'local': local,
        'files': [str(p.relative_to(src)) for p in sorted(files)],
    }


def _write_readme(dest_root: Path, results: list[dict], source: Path, version: str) -> Path:
    """集中记录来源、版本、许可证 —— 移植的是第三方内容，出处必须可追溯。"""
    upstream_license = source.parent.parent / 'LICENSE'
    license_note = 'Apache-2.0（上游仓库 https://github.com/mims-harvard/ToolUniverse）'
    if upstream_license.is_file():
        license_note += f'；本地副本 `{upstream_license}`'

    lines = [
        '# drug-* skills 的来源与移植说明',
        '',
        '> 本目录下所有 `drug-*` 前缀的 skill 由脚本生成，**请勿手工编辑** ——',
        '> 改动会在下次移植时被覆盖。要改行为请改 `scripts/port_tooluniverse_skills.py`，',
        '> 或改阶段编排 `server/drug_stages.py`。',
        '',
        '## 来源',
        '',
        '| 项 | 值 |',
        '|---|---|',
        '| 上游项目 | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse)（Zitnik Lab, Harvard） |',
        f'| 许可证 | {license_note} |',
        f'| 移植版本 | `{version}` |',
        f'| 上游路径 | `{source}` |',
        '| 生成脚本 | `scripts/port_tooluniverse_skills.py` |',
        '',
        f'移植 = 拷贝目录 + 在 SKILL.md 的 frontmatter 后插入「{ADAPT_HEADER_MARK}」头 +',
        '把 frontmatter 的 `name:` 改写为 GenSci 侧的名字。**正文内容未作改动。**',
        '',
        '## 清单',
        '',
        '| GenSci skill | ToolUniverse 上游 | 随拷文件 |',
        '|---|---|---|',
    ]
    for r in results:
        shown = ', '.join(f'`{f}`' for f in r['files'][:4])
        if len(r['files']) > 4:
            shown += ', …'
        lines.append(f'| `{r["local"]}` | `{r["upstream"]}` | {len(r["files"])} 个：{shown} |')

    lines += [
        '',
        '## 未移植的两个上游 skill',
        '',
        '`tooluniverse-protein-modification-analysis` 与 `tooluniverse-protein-interactions`',
        '的内容已经在更早一次移植中以 `protein-modification-analysis` / `protein-interactions`',
        '的名字存在于 `server/skills/` 下，重复搬运没有意义。阶段编排直接引用那两个现成目录。',
        '',
        '## 重新生成',
        '',
        '```bash',
        '# ToolUniverse 升级后重跑（自动取插件缓存里版本号最大的那份）',
        'python3 scripts/port_tooluniverse_skills.py',
        '',
        '# 指定源目录 / 只看会做什么',
        'python3 scripts/port_tooluniverse_skills.py --source /path/to/skills --dry-run',
        '```',
        '',
        '重跑后必须**重启后端** —— `server/skills/_loader.py` 的 `scan_skills()` 有模块级缓存。',
        '',
    ]

    path = dest_root / 'drug-README.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description='把 ToolUniverse skill 移植进 GenSci')
    ap.add_argument('--source', help='ToolUniverse 的 skills 目录（或含 skills/ 的版本目录）')
    ap.add_argument('--dest', default=str(DEFAULT_DEST), help=f'落点根目录（默认 {DEFAULT_DEST}）')
    ap.add_argument('--only', action='append', default=None,
                    help='只移植指定的名字（可重复；上游名或落点名都认）')
    ap.add_argument('--dry-run', action='store_true', help='只打印计划，不写文件')
    ap.add_argument('--force', action='store_true', help='覆盖非本脚本生成的已存在目录')
    args = ap.parse_args()

    try:
        source = _resolve_source(args.source)
    except PortError as e:
        print(f'错误: {e}', file=sys.stderr)
        return 2

    dest_root = Path(args.dest).expanduser().resolve()
    if not dest_root.is_dir():
        print(f'错误: 落点目录不存在: {dest_root}', file=sys.stderr)
        return 2

    manifest = MANIFEST
    if args.only:
        wanted = set(args.only)
        manifest = [m for m in MANIFEST if m[0] in wanted or m[1] in wanted]
        unknown = wanted - {x for m in MANIFEST for x in m}
        if unknown:
            print(f'错误: --only 里有 MANIFEST 未列出的名字: {", ".join(sorted(unknown))}', file=sys.stderr)
            return 2

    version = _upstream_version(source)
    print(f'源: {source}  (版本 {version})')
    print(f'落点: {dest_root}')
    print(f'计划移植 {len(manifest)} 个 skill{"（dry-run）" if args.dry_run else ""}\n')

    results, errors = [], []
    for upstream, local in manifest:
        try:
            r = port_one(source, dest_root, upstream, local, force=args.force, dry_run=args.dry_run)
            results.append(r)
            print(f'  ✓ {r["upstream"]:<46} → {local:<28} {len(r["files"])} 文件')
        except PortError as e:
            errors.append((upstream, str(e)))
            print(f'  ✗ {upstream:<46} → {local:<28} {e}')

    if not args.dry_run and results:
        readme = _write_readme(dest_root, results, source, version)
        print(f'\n已写 {readme}')

    if errors:
        print(f'\n{len(errors)} 个失败：', file=sys.stderr)
        for up, msg in errors:
            print(f'  {up}: {msg}', file=sys.stderr)
        return 1

    print(f'\n完成：{len(results)}/{len(manifest)}')
    if not args.dry_run:
        print('提醒：重启后端后新 skill 才会出现在 /api/skills（scan_skills 有模块级缓存）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
