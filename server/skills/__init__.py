"""GenSci Skills — Plugin-style + Unified Tool Registry.

Each subdirectory with SKILL.md = one skill, auto-detected.
Optional __init__.py adds a registered function (tool calling).

Unified Tool Registry (对齐 Claude Code Tools 数组):
- ALL_TOOLS: list[Tool] — 统一工具列表（Native + MCP + SKILL.md-only）
- get_openai_tools(): 输出所有工具的 OpenAI function calling schema
"""
from __future__ import annotations

import os
import re
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core import Tool, ALL_TOOLS, register_tool as _register_core_tool


@dataclass
class ParamDef:
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass
class SkillDef:
    name: str
    description: str
    params: list[ParamDef]
    func: Callable[..., Any] | None = None  # None = SKILL.md only, no registered function

    def to_openai_tool(self) -> dict:
        """If there's a registered function, expose as tool."""
        if self.func is None:
            return None
        properties = {}
        required = []
        for p in self.params:
            prop: dict = {'type': p.type, 'description': p.description}
            if p.enum:
                prop['enum'] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                },
            },
        }


SKILL_REGISTRY: dict[str, SkillDef] = {}
# DEFERRED_MCP_TOOLS 删除 -> 统一到 ALL_TOOLS (is_mcp/is_deferred 字段)


def register_skill(name: str, description: str, params: list[ParamDef]):
    """注册技能 — 保留旧接口兼容，内部转为 Tool + SkillDef。

    同时注册到 SKILL_REGISTRY 和 ALL_TOOLS。
    """
    def decorator(func):
        sd = SkillDef(name=name, description=description, params=params, func=func)
        SKILL_REGISTRY[name] = sd
        # 也注册到统一 ALL_TOOLS
        schema = _params_to_schema(params)
        _register_core_tool(
            name=name, description=description, input_schema=schema,
            is_deferred=False,
        )(func)
        return func
    return decorator


def get_skill(name: str) -> SkillDef | None:
    return SKILL_REGISTRY.get(name)


def list_skills() -> list[SkillDef]:
    return list(SKILL_REGISTRY.values())


def get_openai_tools() -> list[dict]:
    """输出 OpenAI function calling schema — 所有工具的 schema。

    对齐 Claude Code: tools → toolToAPISchema() → API request。
    ALL_TOOLS 是统一列表，不再分 Tier 1 / Tier 2。
    MCP 工具也直接输出 schema（DeepSeek/OpenAI 协议不支持 tool_reference，
    不能真正 deferred，所以直接给出完整 schema）。
    """
    result = []
    for tool in ALL_TOOLS:
        if tool.is_mcp:
            # MCP 工具始终输出 schema（OpenAI 协议）
            t = tool.to_openai_tool()
        elif tool.fn is not None:
            # Native 工具有 fn → 输出
            t = tool.to_openai_tool()
        else:
            # SKILL.md-only → 不输出（LLM 通过 skill("name") 读取）
            continue
        if t:
            result.append(t)
    return result


def _params_to_schema(params: list[ParamDef]) -> dict:
    """Convert ParamDef list to JSON Schema dict."""
    properties = {}
    required = []
    for p in params:
        prop: dict = {'type': p.type, 'description': p.description}
        if p.enum:
            prop['enum'] = p.enum
        properties[p.name] = prop
        if p.required:
            required.append(p.name)
    return {
        'type': 'object',
        'properties': properties,
        'required': required,
    }


def get_skill_content(name: str) -> str | None:
    """Read SKILL.md content (minus frontmatter) for LLM reference."""
    _path = _skills_path / name / 'SKILL.md'
    if _path.exists():
        text = _path.read_text()
        text = re.sub(r'^---.*?---\s*', '', text, flags=re.DOTALL)
        return text.strip()
    return None


_skills_path = Path(__file__).parent


def _parse_frontmatter(text: str) -> dict:
    match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return {}
    meta = {}
    for line in match.group(1).strip().split('\n'):
        if ':' in line:
            key, _, value = line.partition(':')
            meta[key.strip()] = value.strip().strip('"\'')
    return meta


# ── System tools (Tier 1) — 通过 tools/ 包导入触发注册 ─────────
# 每个工具在 tools/*/__init__.py 中通过 @register_skill 自行注册。
# 对标 Claude Code 的 src/tools.ts 集中导入。
import tools  # noqa: F401 — triggers registration via decorators
# ── Discover directories ──────────────────────────────────────
for _entry in sorted(os.listdir(_skills_path)):
    if _entry.startswith('_') or _entry.startswith('.'):
        continue
    _dir = _skills_path / _entry
    if not _dir.is_dir():
        continue

    _init_file = _dir / '__init__.py'
    _skill_file = _dir / 'SKILL.md'

    # 1. If __init__.py exists, import it (may register functions via @register_skill)
    if _init_file.exists():
        try:
            importlib.import_module(f'{__name__}.{_entry}')
        except Exception as e:
            print(f'[skills] Warning: {_entry}/__init__.py import failed: {e}')

    # 2. If SKILL.md exists but NO registered function, create a doc-only skill entry
    #    Note: these are NOT added to ALL_TOOLS — they're invoked via skill("name") tool.
    if _skill_file.exists() and _entry not in SKILL_REGISTRY:
        try:
            text = _skill_file.read_text()
            meta = _parse_frontmatter(text)
            desc = meta.get('description', '') or f'Single-cell analysis skill: {_entry}'
            SKILL_REGISTRY[_entry] = SkillDef(
                name=_entry,
                description=desc,
                params=[],  # no registered function params
                func=None,  # doc-only skill
            )
        except Exception:
            pass


# ── Resource discovery (scripts/ references/ assets/) ────────

@dataclass
class SkillResources:
    """Bundled resources for a skill (skill-creator standard)."""
    scripts_dir: str | None = None
    references_dir: str | None = None
    assets_dir: str | None = None


def get_skill_resources(name: str) -> SkillResources:
    _dir = _skills_path / name
    if not _dir.is_dir():
        return SkillResources()
    return SkillResources(
        scripts_dir=str(_dir / 'scripts') if (_dir / 'scripts').is_dir() else None,
        references_dir=str(_dir / 'references') if (_dir / 'references').is_dir() else None,
        assets_dir=str(_dir / 'assets') if (_dir / 'assets').is_dir() else None,
    )


def list_skill_resources() -> list[dict]:
    result = []
    for name in SKILL_REGISTRY:
        res = get_skill_resources(name)
        result.append({
            'name': name,
            'has_scripts': res.scripts_dir is not None,
            'has_references': res.references_dir is not None,
            'has_assets': res.assets_dir is not None,
        })
    return result
