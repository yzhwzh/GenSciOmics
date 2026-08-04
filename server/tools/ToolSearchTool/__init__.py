"""ToolSearchTool — 搜索 MCP 工具。对标 Claude Code 的 ToolSearchTool。"""
from __future__ import annotations
import re
from skills import register_skill, ParamDef
from core import ALL_TOOLS

TS_PROMPT = """Fetches full schema definitions for deferred tools so they can be called.
Deferred tools appear by name in the system prompt. Until fetched, only the name is known — there is no parameter schema, so the tool cannot be invoked.
Query forms:
- "select:tool1,tool2" — fetch these exact tools by name
- "keywords" — keyword search, returning best matches"""


def _fm(q, t):
    ql, tl = q.lower().strip(), t.lower()
    ws = set(re.findall(r'\w+', ql))
    if not ws:
        return 0
    s = 20 if ql in tl else 0
    for w in ws:
        if w in tl:
            s += 2
    return s


def tool_search(query: str, max_results: int = 5) -> dict:
    """Search deferred tools by keyword or exact name."""
    _deferred = [t for t in ALL_TOOLS if t.is_deferred]
    scored = [(s, t) for t in _deferred if (s := _fm(query, f'{t.name} {t.description}')) > 0]
    scored.sort(key=lambda x: -x[0])
    return {
        'query': query,
        'matches': [{'name': t.name, 'description': t.description,
                      'input_schema': t.input_schema, 'server': t.server_name}
                     for _, t in scored[:max_results]],
        'n_matches': min(len(scored), max_results),
        'total_deferred': len(_deferred),
    }


register_skill(name='tool_search', description=TS_PROMPT,
               params=[ParamDef(name='query', type='string', description='"select:name" 精确选或关键词搜索'),
                       ParamDef(name='max_results', type='integer', description='返回数量', required=False)])(tool_search)
