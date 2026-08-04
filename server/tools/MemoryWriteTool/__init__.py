"""MemoryWriteTool — 保存记忆。"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from skills import register_skill, ParamDef

_MD = Path(__file__).resolve().parent.parent.parent / 'memory'

def _update_index(name, desc):
    idx = _MD / 'MEMORY.md'
    if not idx.is_file(): idx.write_text('# GenSci Memory Index\n\n')
    c = idx.read_text(encoding='utf-8')
    line = f'- [{desc[:50]}]({name}.md) — {desc[:80]}\n'
    if line not in c: idx.write_text(c + line)

def memory_write(name: str, type: str = 'user', description: str = '', content: str = '') -> dict:
    if not _MD.is_dir(): return {'error': 'Memory directory not found'}
    if type not in ('user', 'feedback', 'project', 'reference'): return {'error': f'Invalid type: {type}'}
    body = content.strip() or '(empty)'
    (_MD / f'{name}.md').write_text(f'---\nname: {name}\ndescription: {description}\ntype: {type}\ncreated: {date.today().isoformat()}\n---\n\n{body}\n', encoding='utf-8')
    _update_index(name, description[:80])
    return {'name': name, 'type': type, 'status': 'saved'}

register_skill(name='memory_write',
               description='Save a persistent memory. Use when you learn something about the user, '
                           'get feedback on your approach, or want to record project context. '
                           'Types: user (role/preferences), feedback (corrections/confirmations), '
                           'project (ongoing work), reference (external resources). '
                           'Auto-indexes into MEMORY.md.',
               params=[ParamDef(name='name', type='string', description='名称'),
                       ParamDef(name='type', type='string', description='类型', enum=['user','feedback','project','reference']),
                       ParamDef(name='description', type='string', description='描述'),
                       ParamDef(name='content', type='string', description='正文')])(memory_write)
