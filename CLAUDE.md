# CLAUDE.md — GenSci v3

## 硬编码禁令

**绝对禁止在代码中硬编码以下内容：**
- 基因名/别名映射（GENE_ALIASES 词典等）→ 必须用 mygene.info API 查询
- API key、密钥、token
- 文件路径（必须用 config.py 或环境变量）
- 依赖特定机器的路径（如 conda 安装路径）

违反此规则的代码将被拒绝合并。

## Mandatory Development Workflow

**Every new feature MUST follow this workflow. Do NOT skip stages.** V1/V2/V3 violated this — going forward it's enforced.

```
Phase 0: Research & Reuse      gh search / docs-lookup / Explore
  ↓ (approve)
Phase 1: Architecture & Plan    architect / code-architect / planner
  ↓ (approve)
Phase 2: TDD - RED              tdd-guide → write tests → run → FAIL
  ↓ (approve)
Phase 3: TDD - GREEN            implement → run tests → PASS
  ↓
Phase 4: Code Review            code-reviewer + language-specific reviewer
  ↓
Phase 5: Security Review        security-reviewer (if auth/input/API)
  ↓
Phase 6: Build Check            build-error-resolver (if build fails)
  ↓
Phase 7: Coverage Check         npm run test:coverage ≥ 80%
```

### Phase 0 — Research & Reuse
Before writing any code, search for existing solutions:
- `gh search repos` / `gh search code` — find templates, skeletons, reference implementations
- `ecc:docs-lookup` — library API docs (Context7)
- `Explore` agent — sweep codebase for patterns
- `WebSearch` / `Exa` — broader web research

**Gate**: produce a summary of what exists and what we'll reuse.

### Phase 1 — Architecture & Planning
For features touching 3+ files or involving architectural decisions:
- `ecc:architect` — system design, tech choices, data flow diagrams
- `ecc:code-architect` — concrete file list, interfaces, build order
- `ecc:planner` or `Plan` agent — phased implementation plan, task breakdown

**Gate**: produce a plan file. Do NOT start coding without an approved plan.

### Phase 2 — TDD: RED
- `ecc:tdd-guide` — write tests first (unit + integration)
- Run `npm test` — tests MUST fail (RED)
- If modifying an existing feature, add regression tests that fail for the bug

**Gate**: test output showing RED. Create git checkpoint commit.

### Phase 3 — TDD: GREEN
- Write minimal implementation to pass tests
- Run `npm test` — all tests MUST pass (GREEN)

**Gate**: test output showing GREEN. Create git checkpoint commit.

### Phase 4 — Code Review
- `ecc:code-reviewer` — general code quality
- Language-specific reviewer:
  - Frontend/TS → `ecc:typescript-reviewer`
  - Python → `ecc:python-reviewer`
  - Rust → `ecc:rust-reviewer`
  - (see full agent list below)

**Gate**: all CRITICAL/HIGH issues addressed. No silent error swallowing.

### Phase 5 — Security Review
Mandatory when the feature involves:
- Authentication/authorization
- User input → SQL/filesystem
- External API calls
- Cryptography

Use `ecc:security-reviewer`.

**Gate**: no CRITICAL security issues.

### Phase 6 — Build Check
If build fails at any point:
- `ecc:build-error-resolver` — TS/JS build errors
- Or language-specific build resolver (Python, Rust, Go, etc.)

### Phase 7 — Coverage Verification
```bash
npm run test:coverage
```
Target: **≥ 80%** coverage (lines, branches, functions, statements).

### Full Agent Reference

| Stage | Agent | When |
|-------|-------|------|
| Research | `gh search`, `Explore`, `docs-lookup` | Every new feature |
| Architecture | `ecc:architect`, `ecc:code-architect`, `ecc:planner` | 3+ files or design decisions |
| TDD | `ecc:tdd-guide`, `/ecc:tdd-workflow` | Every code change |
| E2E | `ecc:e2e-runner` | Critical user flows |
| Code Review | `ecc:code-reviewer` | After every implementation |
| TS/JS Review | `ecc:typescript-reviewer` | TypeScript changes |
| Python Review | `ecc:python-reviewer` | Python changes |
| Security | `ecc:security-reviewer` | Auth/input/API/database |
| Build Fix | `ecc:build-error-resolver` | Build fails |
| Performance | `ecc:performance-optimizer` | Slow code, large data |
| Dead Code | `ecc:refactor-cleaner` | Maintenance |
| Docs | `ecc:doc-updater` | Updating CLAUDE.md, README |

## Commands

```bash
# Start both backend + frontend together
npm run start                  # python3 server/main.py & vite on :5173

# Or separately:
npm run dev                    # Vite frontend only on :5173
npm run server                 # Python API only on :6000

# Build & type-check
npm run build                  # tsc -b && vite build
npx tsc --noEmit               # Type-check only

# Lint
npm run lint

# Test
npm test                      # vitest run
npm run test:watch            # vitest watch mode
npm run test:coverage         # vitest with coverage report

# HDF5 file locking is auto-disabled in server/main.py via os.environ.
# No manual flag needed. Prevents concurrent .h5ad read hangs.
```

## Architecture (v2 — Modular Refactor)

**GenSci v2** — single-cell data analysis platform. Refactored from a monolithic codebase into domain modules.

### Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19, TypeScript 6, Tailwind CSS v4, Vite 8 |
| Routing | react-router-dom v7 |
| Interactive Viz | ECharts 6 |
| Backend | Python 3 stdlib (`ThreadingHTTPServer`) — concurrent requests |
| Static Charts | matplotlib 3.10 + seaborn 0.13 + colorcet 3.2 (base64 PNG) |
| Data | `.h5ad` (AnnData) via `anndata` (backed='r') |

### Directory Structure

```
GenSci/
├── server/
│   ├── main.py          # Entry: ThreadingHTTPServer on :6000
│   ├── config.py        # All constants (paths, ports, proxy, cache limits)
│   ├── handler.py       # HTTP handler (CORS, JSON routing)
│   ├── routes.py        # Route table — dict-based dispatch
│   ├── caches.py        # Thread-safe LRUCache class
│   ├── scanner.py       # Background .h5ad filesystem scanner (30s interval)
│   ├── search.py        # Gene/disease/PMID/celltype search
│   ├── pubmed.py        # EuropePMC abstract fetching
│   ├── events.py        # Event log + milestones
│   ├── online.py        # Heartbeat user tracking
│   ├── llm_proxy.py     # LLM proxy (delegates to agent/)
│   ├── agent/
│   │   ├── __init__.py  # ReAct loop 编排器
│   │   ├── prompt.py    # Dynamic prompt assembler (13 sections)
│   │   └── evaluator.py # Result evaluator + SQLite logging
│   ├── engine/
│   │   └── hooks.py     # Post-tool hooks (image_return, error_recovery)
│   ├── core/
│   │   ├── tool.py      # Unified Tool dataclass + ALL_TOOLS registry
│   │   └── mcp_manager.py # MCP server connection manager
│   ├── tools/           # 6 native tools (Shell/Skill/ToolSearch/Memory*)
│   ├── skills/          # 40+ skill directories (light-*, single-*)
│   ├── memory/          # Persistent file-based memory (memdir model)
│   └── analysis/
│       ├── utils.py     # Shared: gene index resolution, group column detection, palettes
│       ├── umap.py      # UMAP coordinate extraction
│       ├── expression.py# Gene expression statistics
│       ├── stats.py     # Mann-Whitney U / Fisher exact tests
│       └── plots.py     # matplotlib/seaborn chart generation
├── src/
│   ├── main.tsx         # Entry: BrowserRouter + StrictMode
│   ├── App.tsx          # 5 routes, wrapped in ErrorBoundary
│   ├── index.css        # Tailwind v4 brand theme
│   ├── api/             # Shared API client layer
│   │   ├── client.ts    # apiFetch + cachedFetch with TTL
│   │   ├── types.ts     # All API response types (single source of truth)
│   │   ├── datasets.ts  # Dataset/tissue/stats endpoints
│   │   ├── analysis.ts  # UMAP, expression, plot, table, LLM endpoints
│   │   └── search.ts    # Search + log endpoints
│   ├── hooks/
│   │   └── useTableFilter.ts  # Generic column-based filtering
│   ├── pages/
│   │   ├── HomePage.tsx       # Two-column layout
│   │   ├── TissuePage.tsx     # Dataset table per tissue + Tissue Workspace
│   │   ├── DatasetPage.tsx    # Dataset detail (placeholder)
│   │   ├── AnalysisPage.tsx   # Analysis hub (5 tabs, state owner)
│   │   └── SearchPage.tsx     # Search results
│   ├── components/
│   │   ├── ErrorBoundary.tsx  # React error boundary
│   │   ├── Header.tsx         # Logo + search (debounced dropdown)
│   │   ├── CoreDatasets.tsx   # 28 organ cards with icons
│   │   ├── TissueAtlas.tsx    # SVG body map with GEPIA paths
│   │   ├── StatsTable.tsx     # Tissue×species cross-tabulation
│   │   ├── OnlineUsers.tsx    # Real-time online user counter
│   │   ├── FilterDropdown.tsx # Multi-select filter with search
│   │   ├── UpdateLog.tsx      # Milestone + event feed
│   │   └── analysis/          # AnalysisPage sub-components
│   │       ├── InfoPanel.tsx, UmapPlot.tsx, DualGeneColorMap.tsx
│   │       ├── ZoomableImage.tsx, PlotImage.tsx, RawDataDownload.tsx
│   │       ├── DetailTable.tsx, MuTestTable.tsx, AggregateDetailTable.tsx
│   │       ├── FisherTable.tsx, UmapTabContent.tsx
│   │       ├── BoxPlotContainer.tsx, ExpressionChartContainer.tsx
│   │       ├── DragHandle.tsx, FreeAnalysisTab.tsx
│   │       ├── ChatPanel.tsx, ToolResultsPanel.tsx
│   │       ├── LLMConfigPanel.tsx, SkillDetailModal.tsx
│   │       └── LiteratureTab.tsx  # Tissue Workspace LLM
│   └── data/
│       ├── mockData.ts    # Organ paths, datasets, icons data
│       ├── organIcons.tsx  # SVG organ icon paths (healthicons.org)
│       └── organShapes.ts  # Mouse/Monkey organ SVG paths
```

### Data Layout

```
06.GenSci/                 # PROJECT_ROOT (server/config.py)
├── Data/                  # All dataset symlinks organized by species
│   ├── Human/
│   │   ├── Lung/COPD/*.h5ad       # Symlinks to /data/yuanwuzhou/08.GEO/...
│   │   ├── Lung/IPF/*.h5ad
│   │   ├── Lung/ILD/*.h5ad
│   │   └── Ulterus/EM/*.h5ad
│   ├── Mouse/             # (future)
│   └── Monkey/            # (future)
├── GenSci.log             # JSONL event log
└── milestones.json        # Development milestones
```

### API Endpoints

| Method | Endpoint | File | Description |
|--------|----------|------|-------------|
| GET | `/api/datasets` | routes.py | List datasets, optional `?tissue=` |
| GET | `/api/search` | routes.py | Search across genes/diseases/PMIDs |
| GET | `/api/tissues` | routes.py | Distinct tissue list |
| GET | `/api/stats` | routes.py | Tissue×species cross-tabulation |
| GET | `/api/log` | routes.py | Event log + milestones |
| GET | `/api/analysis-info` | routes.py | Dataset abstract + stats |
| GET | `/api/umap-data` | routes.py | UMAP coordinates |
| GET | `/api/search-genes` | routes.py | Gene name autocomplete |
| GET | `/api/expression-stats` | routes.py | Gene expression statistics |
| GET | `/api/per-sample-table` | routes.py | Per-sample detail table |
| GET | `/api/per-sample-mutest` | routes.py | Mann-Whitney U test |
| GET | `/api/aggregate-table` | routes.py | Per-group aggregate table |
| GET | `/api/plot` | routes.py | matplotlib boxplot/barplot |
| GET | `/api/cell-ratio-plot` | routes.py | Cell ratio plots |
| GET | `/api/umap-ratio-plots` | routes.py | UMAP ratio plots |
| POST | `/api/milestone` | routes.py | Add development milestone |

### Key Design Decisions

1. **ThreadingHTTPServer** — Each request gets its own thread; slow .h5ad reads don't block other users. No external framework needed.
2. **LRU caches** — All caches bounded by max size (default 1000 entries). Prevents memory leak.
3. **Path traversal protection** — All `real_path` parameters validated against whitelist of data directories.
4. **No silent error swallowing** — Every `except` block logs the error.
5. **Modular backend** — Each domain in its own file. Adding a feature = adding one file + one route entry.
6. **Shared frontend API layer** — `src/api/client.ts` + `src/api/types.ts` is the single source of truth. No more duplicate fetch() calls.
7. **Bounded scanner interval** — 30s (was 5s) — adequate for symlink-based data directories.
8. **HDF5 file locking disabled** — `os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'` at the top of `main.py` prevents thread hangs when multiple requests read the same `.h5ad` file concurrently (read-only access, no corruption risk).
9. **Palette system** — 5 named palettes (`default`/`pastel`/`bold`/`nature`/`tab10`) in `server/analysis/utils.py`. `PALETTE_OPTIONS` shared constant in `src/api/types.ts`. Backend validates palette name via `get_palette_name(q)` in `routes.py`; invalid names silently fall back to `'default'`.
10. **Vite proxy** — `vite.config.ts` proxies `/api` requests to `http://127.0.0.1:6000`, so frontend dev server on :5173 can reach the Python backend without CORS issues.

### Analysis Page Data Flow

```
AnalysisPage (state owner — fetches all data for active tab)
  ├── Tab 0: InfoPanel (receives info as prop, pure presenter)
  ├── Tab 1: UmapTabContent (receives umapData, colorBy, palette as props)
  │   ├── UmapPlot (ECharts scatter, pure chart renderer)
  │   └── fetches umap-ratio-plots internally
  ├── Tab 2: BoxPlotContainer (owns gene/metric/condition/palette state)
  │   ├── PlotImage → fetchPlot() via shared api/analysis.ts
  │   ├── DetailTable, MuTestTable
  │   └── DragHandle (resizable panels)
  └── Tab 3: ExpressionChartContainer (same pattern as BoxPlotContainer)
      ├── PlotImage
      ├── AggregateDetailTable, FisherTable
      └── DragHandle
```

### Plot Generation Pipeline

```
User picks gene + palette → PlotImage (React)
  → fetchPlot() from src/api/analysis.ts
    → GET /api/plot?real_path=...&gene=...&palette=...
      → routes.py: get_palette_name(q), validate_real_path()
        → analysis/plots.py: _generate_plot() uses build_cond_palette(palette_name)
          → matplotlib boxplot/barplot → base64 PNG → frontend renders via ZoomableImage
```

### Palette System

| File | Role |
|------|------|
| `server/analysis/utils.py` | `CATEGORICAL_PALETTE_MAP` (categorical) + `COND_PALETTES` (disease/control) |
| `server/analysis/plots.py` | `_generate_plot()`, `_generate_cell_ratio_plot()`, `_generate_umap_ratio_plots()` — all accept `palette_name` |
| `server/analysis/umap.py` | `_get_umap_data()` uses `CATEGORICAL_PALETTE_MAP` for scatter plot colors |
| `server/routes.py` | `get_palette_name(q)` — validates palette param, falls back to `'default'` |
| `src/api/types.ts` | `PALETTE_OPTIONS` shared constant + `PaletteName` type |
| `src/api/analysis.ts` | `fetchPlot()`, `fetchUmapData()`, `fetchUmapRatioPlots()` — all pass `palette` param |

## v3 — Free Analysis Tab (2026-06-25)

### Architecture
```
AnalysisPage
  └── Tab 4: FreeAnalysisTab (LLM-powered chat + skill cards)
      ├── LLMConfigPanel (model, API key, base URL, temperature)
      ├── SkillCards (22 skills as expandable cards)
      ├── ChatPanel (messages + resizable tool results)
      ├── DragHandle (resize skills/chat split)
      └── Persistent input bar (always visible)
```

### Skill System (folder-based)

Each skill = a subdirectory under `server/skills/`:
```
server/skills/
├── __init__.py          ← auto-discovers skill directories
├── _base.py             ← shared helpers
├── get_data_summary/    ← folder name = skill name
│   ├── __init__.py      ← registered Python function (tool calling)
│   └── SKILL.md         ← LLM-readable reference doc
└── ... 22 skill directories
```

**Add a skill:** `mkdir server/skills/my_skill/` → write `__init__.py` + `SKILL.md`
**Delete a skill:** `rm -rf server/skills/my_skill/`
**Plugin mode:** Any directory with `SKILL.md` (no `__init__.py`) auto-appears as a "Reference Skills" card

### API Endpoints (v3 additions)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/skills` | List all skills with tool/SKILL.md metadata |
| GET | `/api/skills/content?name=xxx` | Get SKILL.md content for LLM reference |
| POST | `/api/llm/chat` | LLM proxy with function calling (DeepSeek/OpenAI) |
| POST | `/api/llm/chat/stream` | SSE streaming chat |

### Skill Ecosystem

Skills are auto-discovered from `server/skills/` subdirectories. Categories include:
- **Core tools** (6): shell, skill, tool_search, memory_read, memory_write, memory_delete
- **Light skills** (~29): light-figure-drawing, light-literature-search, light-paper-drafting, light-result-analysis, light-slides, light-citation, etc.
- **Single-cell skills** (~11): single-cell-annotation, single-cell-differential-expression, single-cell-foundation-model, single-cell-rna-velocity, single-cell-scenic, single-cell-trajectory-inference, statistical-analysis, etc.

See `/api/skills` for the live list of available skills.

### LLM Proxy Design
- Default: Company LLM gateway (`http://llm-gateway.ai.dgtmeta.com/v1`, Qwen3.5-397B)
- API key passed from frontend per-request (not stored server-side)
- Also supports OpenAI-compatible APIs (DeepSeek, Claude via proxy, local Ollama)
- Function calling via registered tools
- SSE streaming for real-time responses
- System prompt auto-injected with tool descriptions

## v4 — Agent System (实际)

### 代码现状

```
server/agent/
├── __init__.py      ← ReAct loop 编排器（被 llm_proxy.py 调用）
├── prompt.py        ← Dynamic prompt assembler（13 章节，在用）
├── evaluator.py     ← Result evaluator + SQLite logging（在用）
└── (planner.py / retriever.py / tests/ 已于 2026-07-21 删除)
```

### 实际 Agent Pipeline (ReAct Loop)

```
  llm_proxy.py (SSE 入口)
       │
       ▼
  agent/__init__.py
  ┌──────────────────────────────────────────────────────┐
  │  0. Memory Prefetch（启动时异步搜索相关记忆）         │
  │     → 找到匹配记忆自动注入 system message            │
  │                                                      │
  │  1. assemble_prompt() → 构建 System Prompt           │
  │     (注入日期 + skill 列表 + 工具描述 + 记忆)         │
  │                                                      │
  │  2. for iteration < max_iterations:                  │
  │       a. _stream_sse() → LLM API（502/503/504 重试） │
  │       b. LLM 返回: text 或 tool_calls               │
  │       c. 如果 tool_calls → 并行执行（ThreadPool 3）  │
  │            → run_post_tool hooks                     │
  │            → 结果追加到 working_messages             │
  │       d. 接近上限时注入 nudge 提示总结                │
  │       e. 流式输出到前端                              │
  │                                                      │
  │  3. 无 tool_calls → yield done → 结束               │
  └──────────────────────────────────────────────────────┘
```

**说明：** 这是一个标准的 ReAct 循环，**与 Claude Code 完全对齐**。意图理解、工具选择(Skill 检索)、任务规划**全部由 LLM 在循环中自动完成**，后端没有独立的分类/检索/规划模块。

| 能力 | Claude Code | Single-cell Atlas | 结论 |
|------|-------------|-------------------|------|
| 意图识别 | LLM 从对话上下文自动理解 | LLM 自动理解（Qwen3.5） | ✅ 对齐，两者都不需要独立分类器 |
| 任务规划 | ReAct 循环中自然展开，无 plan() 函数 | 同左，process_chat_streaming() 的 for-range 循环 | ✅ 对齐，都是 LLM 决定调用顺序 |
| Skill 检索 | 系统提示词列出 + API tools 参数传入 schema，模型自选 | 同左，assemble_prompt() + get_openai_tools() | ✅ 对齐，都是 LLM 根据描述选工具 |

早期 v4 曾尝试过独立的 intent.py（规则分类）/ planner.py（Ollama 任务分解）/ retriever.py（TF-IDF 检索），后确认为死代码（从未被调用），已删除。

### 记忆系统 (Memory)

**GenSci 的记忆系统直接对标 Claude Code 的 memdir 模型：**

```
Claude Code memdir                    GenSci memory
────────────────                     ──────────────
~/.claude/projects/<proj>/memory/    server/memory/
├── MEMORY.md (入口索引)              ├── MEMORY.md (入口索引)
├── user-profile.md                   ├── kidney-epithelial-...md
└── feedback-*.md                     └── (按需写入)

访问方式:                             访问方式:
  buildMemoryPrompt()                  memory_read / memory_write
  (系统自动加载)                        / memory_delete 工具 (LLM 按需调用)

文件格式:                             文件格式:
  Markdown + YAML frontmatter ✅       Markdown + YAML frontmatter ✅
  类型: user/feedback/project/ref ✅   类型: user/feedback/project/ref ✅
  [[memory-name]] 交叉引用 ✅          [[memory-name]] 交叉引用 ✅
```

实现在 `server/tools/Memory{Read,Write,Delete}Tool/__init__.py` 中，通过 `register_skill()` 注册为 LLM 可调用的工具。LLM 在 ReAct 循环中按需读写记忆。

**对比 `agent/memory/`（已删除）：**
- 早期 v4 版本曾开发过 SQLite + Ollama embedding + 实体提取的重型记忆系统（`server/agent/memory/`）
- 在 commit `f2296b2` 中移除，替换为当前的轻量文件系统版本
- 当前版本直接克隆 Claude Code 的设计，无向量搜索，靠 LLM 自身理解做 recall

### Evaluator
- 每次工具调用后评估结果是否充分
- 如果不满足 → 自动生成跟进查询，继续下一轮 ReAct 迭代
- 日志写入 SQLite（`/tmp/gensci_monitor.db`，`sessions` 表）
- 字段：session_id, query, intent(always 'unknown'), latency_ms, tool_calls, iterations

### API Format Support
- Auto-detects OpenAI vs Anthropic format via `_api_url(base_url)`
- OpenAI: `base_url/chat/completions` + `Bearer` auth
- Anthropic: `base_url/v1/messages` + `x-api-key` auth
- Detects "anthropic" in base_url → switches format automatically
- Supports: DeepSeek, OpenAI, Claude, Ollama (Ollama uses OpenAI format)

### 架构图
详见 `docs/system-architecture.svg`（分层架构图，反映真实代码结构）。
