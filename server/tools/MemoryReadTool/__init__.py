"""MemoryReadTool — 读取/搜索记忆。"""
from __future__ import annotations
import re
from pathlib import Path
from skills import register_skill, ParamDef

_MD = Path(__file__).resolve().parent.parent.parent / 'memory'

def _pfm(text):
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    return {l.partition(':')[0].strip(): l.partition(':')[2].strip().strip('"').strip("'") for l in m.group(1).strip().split('\n') if ':' in l} if m else {}

def memory_read(query: str = '', name: str = '') -> dict:
    if not _MD.is_dir(): return {'error': 'Memory directory not found'}
    if name:
        fp = _MD / f'{name}.md'
        if not fp.is_file(): return {'error': f'Memory not found: {name}'}
        t = fp.read_text(encoding='utf-8')
        m = _pfm(t)
        return {'name': name, 'type': m.get('type'), 'description': m.get('description'), 'content': re.sub(r'^---.*?---\s*', '', t, flags=re.DOTALL).strip()}
    if query:
        results = []
        for f in sorted(_MD.glob('*.md')):
            if f.name == 'MEMORY.md': continue
            t = f.read_text(encoding='utf-8')
            if query.lower() in t.lower():
                m = _pfm(t)
                results.append({'name': f.stem, 'type': m.get('type'), 'description': m.get('description'), 'snippet': re.sub(r'^---.*?---\s*', '', t, flags=re.DOTALL).strip()[:300]})
        return {'query': query, 'results': results, 'n_results': len(results)}
    memories = []
    for f in sorted(_MD.glob('*.md')):
        if f.name == 'MEMORY.md': continue
        m = _pfm(f.read_text(encoding='utf-8'))
        memories.append({'name': f.stem, 'type': m.get('type'), 'description': m.get('description')})
    return {'memories': memories, 'n_memories': len(memories), 'index': (_MD / 'MEMORY.md').read_text(encoding='utf-8') if (_MD / 'MEMORY.md').is_file() else ''}

register_skill(name='memory_read',
               description='Read/search persistent memories. Use at conversation start to load context, '
                           'or when the user references prior work. Supports three modes: '
                           '(1) by `name` to read one memory, (2) by `query` to search across all memories, '
                           '(3) leaving both empty to list all memories.',
               params=[ParamDef(name='query', type='string', description='搜索关键词', required=False),
                       ParamDef(name='name', type='string', description='记忆文件名', required=False)])(memory_read)
