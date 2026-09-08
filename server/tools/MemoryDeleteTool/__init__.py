"""MemoryDeleteTool — 删除记忆。"""
from __future__ import annotations
import re
from pathlib import Path
from config import MEMORY_DIR as _BASE
from skills import register_skill, ParamDef

_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def _mem_dir(root: str) -> Path:
    return Path(root) if root else _BASE


def memory_delete(name: str, root: str = '') -> dict:
    if not _NAME_RE.match(name):
        return {'error': f'Invalid memory name: {name}'}
    md = _mem_dir(root)
    fp = md / f'{name}.md'
    if not fp.is_file(): return {'error': f'Memory not found: {name}'}
    idx = md / 'MEMORY.md'
    if idx.is_file():
        c = idx.read_text(encoding='utf-8')
        idx.write_text('\n'.join([l for l in c.split('\n') if f'({name}.md)' not in l]) + '\n', encoding='utf-8')
    fp.unlink()
    return {'name': name, 'status': 'deleted'}

register_skill(name='memory_delete',
               description='Delete a memory file by name. Also removes its entry from the MEMORY.md index.',
               params=[ParamDef(name='name', type='string', description='记忆文件名(不含.md)')])(memory_delete)
