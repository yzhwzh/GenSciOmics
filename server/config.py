#!/usr/bin/env python3
"""GenSci v2 configuration constants."""

import os
import sys
from pathlib import Path

# ─── Project paths ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 10.GenSciOmics/
DATA_DIRS = [PROJECT_ROOT / 'Data']
for d in ['Mouse', 'Monkey']:
    p = PROJECT_ROOT / 'Data' / d
    if p.is_dir():
        DATA_DIRS.append(p)
# Agent 记忆根目录（每用户隔离于 MEMORY_DIR/<sanitized_user_id>/）
MEMORY_DIR = PROJECT_ROOT / 'server' / 'memory'

# ─── Agent 产出目录 ───────────────────────────────────────────
# 由 LLM 生成的一切文件（报告 / CSV / 表格 / 图 / 中间结果）都写这里，
# 绝不写进源码树 —— 尤其 server/skills/，那是给人读的指令文档，不是工作目录。
# 这是全项目唯一一处定义；ShellTool 把它作为 GENSCI_RESULTS_DIR 传给子进程，
# 各 skill 脚本据此解析落点（脚本需独立运行，import 不到 config）。
RESULTS_DIR = Path(os.environ.get('GENSCI_RESULTS_DIR', '/tmp/gensci_results'))

# ─── Server ───────────────────────────────────────────────────
HOST = '0.0.0.0'  # bind to all interfaces (needed for SSE direct connection from browser)
API_PORT = int(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--port' else 6001)

# ─── CORS allowed origins ────────────────────────────────────
ALLOWED_ORIGINS = [
    'http://127.0.0.1:5180', 'http://127.0.0.1:5181',
    'http://localhost:5180',  'http://localhost:5181',
    'http://10.243.163.51:5180', 'http://10.243.163.51:5181',
]

# ─── Scanning ─────────────────────────────────────────────────
SCAN_INTERVAL = 30  # seconds
SCANNER_CACHE_FILE = PROJECT_ROOT / '.scanner_cache.json'

# ─── Cache limits ─────────────────────────────────────────────
CACHE_MAX_SIZE = 1000
PLOT_CACHE_MAX_SIZE = 500

# ─── Proxy ────────────────────────────────────────────────────
HTTP_PROXY = os.environ.get('HTTP_PROXY', 'http://10.230.68.120:3128')
os.environ.setdefault('http_proxy', HTTP_PROXY)
os.environ.setdefault('https_proxy', HTTP_PROXY)
os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1,10.0.0.0/8,.ai.dgtmeta.com')

# ─── Obs columns convention ──────────────────────────────────
OBS_COLUMNS = ['Patient', 'Sample', 'Group', 'CellType', 'Tissue']

# ─── Bulk RNA import convention ──────────────────────────────
# Header columns matching these names are treated as sample metadata (obs);
# everything else (plus the first column = sample name) is the gene matrix (var).
BULK_META_COLUMNS = {
    'Disease', 'Group', 'Patient', 'Sample', 'Label', 'Tumor',
    'CellType', 'Tissue', 'Condition',
}
# Cached .h5ad lives at <source_dir>/.bulk_cache/<stem>.h5ad
BULK_CACHE_DIR_NAME = '.bulk_cache'

# ─── Supplementary material cache ────────────────────────────
# PMC 的补充材料包只能整包下载（25–37 MB），没有单文件接口，
# 所以要留一个磁盘缓存：第一次点开某篇的附件要下整包，之后秒开。
SUPP_CACHE_DIR = PROJECT_ROOT / '.supp_cache'
SUPP_CACHE_MAX_MB = 500  # 超过就按 mtime 淘汰最旧的包 —— 102 个数据集全点一遍是 3 GB

# ─── Event log ────────────────────────────────────────────────
EVENT_LOG_MAX = 100
LOG_FILE = PROJECT_ROOT / 'GenSci.log'
MILESTONE_FILE = PROJECT_ROOT / 'milestones.json'

# ─── MCP Servers Configuration ───────────────────────────────
MCP_SERVERS = {
    'exa': {
        'type': 'http',
        'url': 'https://mcp.exa.ai/mcp',
        'api_key': os.environ.get('EXA_API_KEY', ''),  # 个人 key 已耗尽 → 默认匿名访问 mcp.exa.ai；将来有 key 再设环境变量 EXA_API_KEY
        'enabled': True,
    },
    'context7': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@upstash/context7-mcp@2.1.4'],
        'enabled': True,
    },
    'sequential-thinking': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-sequential-thinking@2025.12.18'],
        'enabled': True,
    },
    'github': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-github@2025.4.8'],
        'enabled': True,
    },
    'playwright': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@playwright/mcp@0.0.69', '--extension'],
        'enabled': True,
    },
    'tooluniverse': {
        'type': 'stdio',
        'command': str(Path.home() / '.local/bin/tooluniverse'),
        'args': ['--global'],  # 读 ~/.tooluniverse 的 API key；默认 workspace 是当前目录 .tooluniverse
        'enabled': True,
    },
}
