"""MemoryDeleteTool — 删除记忆。"""
from __future__ import annotations
from pathlib import Path
from skills import register_skill, ParamDef

_MD = Path(__file__).resolve().parent.parent.parent / 'memory'

def memory_delete(name: str) -> dict:
    fp = _MD / f'{name}.md'
    if not fp.is_file(): return {'error': f'Memory not found: {name}'}
    idx = _MD / 'MEMORY.md'
    if idx.is_file():
        c = idx.read_text(encoding='utf-8')
        idx.write_text('\n'.join([l for l in c.split('\n') if f'({name}.md)' not in l]) + '\n', encoding='utf-8')
    fp.unlink()
    return {'name': name, 'status': 'deleted'}

register_skill(name='memory_delete',
               description='Delete a memory file by name. Also removes its entry from the MEMORY.md index.',
               params=[ParamDef(name='name', type='string', description='记忆文件名(不含.md)')])(memory_delete)
