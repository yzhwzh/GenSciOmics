"""MemoryReadTool — 读取/搜索记忆。"""
from __future__ import annotations
import re
from pathlib import Path
from config import MEMORY_DIR as _BASE
from skills import register_skill, ParamDef

_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def _mem_dir(root: str) -> Path:
    """root（agent 注入的 per-user 记忆目录）非空则用 root，否则回退全局 server/memory/。"""
    return Path(root) if root else _BASE


def _pfm(text):
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    return {l.partition(':')[0].strip(): l.partition(':')[2].strip().strip('"').strip("'") for l in m.group(1).strip().split('\n') if ':' in l} if m else {}


def memory_read(query: str = '', name: str = '', root: str = '') -> dict:
    md = _mem_dir(root)
    if not md.is_dir():
        # per-user 目录尚未创建 → 视为空，而非错误；全局目录缺失也走这里（正常不发生）
        if name:
            return {'error': f'Memory not found: {name}'}
        if query:
            return {'query': query, 'results': [], 'n_results': 0}
        return {'memories': [], 'n_memories': 0, 'index': ''}
    if name:
        if not _NAME_RE.match(name):
            return {'error': f'Invalid memory name: {name}'}
        fp = md / f'{name}.md'
        if not fp.is_file(): return {'error': f'Memory not found: {name}'}
        t = fp.read_text(encoding='utf-8')
        m = _pfm(t)
        return {'name': name, 'type': m.get('type'), 'description': m.get('description'), 'content': re.sub(r'^---.*?---\s*', '', t, flags=re.DOTALL).strip()}
    if query:
        results = []
        for f in sorted(md.glob('*.md')):
            if f.name == 'MEMORY.md': continue
            t = f.read_text(encoding='utf-8')
            if query.lower() in t.lower():
                m = _pfm(t)
                results.append({'name': f.stem, 'type': m.get('type'), 'description': m.get('description'), 'snippet': re.sub(r'^---.*?---\s*', '', t, flags=re.DOTALL).strip()[:300]})
        return {'query': query, 'results': results, 'n_results': len(results)}
    memories = []
    for f in sorted(md.glob('*.md')):
        if f.name == 'MEMORY.md': continue
        m = _pfm(f.read_text(encoding='utf-8'))
        memories.append({'name': f.stem, 'type': m.get('type'), 'description': m.get('description')})
    return {'memories': memories, 'n_memories': len(memories), 'index': (md / 'MEMORY.md').read_text(encoding='utf-8') if (md / 'MEMORY.md').is_file() else ''}

register_skill(name='memory_read',
               description='Read/search persistent memories. Use at conversation start to load context, '
                           'or when the user references prior work. Supports three modes: '
                           '(1) by `name` to read one memory, (2) by `query` to search across all memories, '
                           '(3) leaving both empty to list all memories.',
               params=[ParamDef(name='query', type='string', description='搜索关键词', required=False),
                       ParamDef(name='name', type='string', description='记忆文件名', required=False)])(memory_read)
