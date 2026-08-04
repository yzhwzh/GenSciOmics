# Claude Code vs GenSci Agent — 架构对比文档

> **最终版** — 生成 2026-07-15，更新 2026-07-21
> 对齐目标: GenSci Agent 全面对标 Claude Code 已验证的成熟架构
> 本文档是 docs/ 下三份最终文档之一（另: system-architecture.svg, ecc-dev-pipeline.svg）
> 2026-07-21 清理: 删除 planner.py/retriever.py/tests, NativeTool, register_deferred_mcp_tool
> 2026-07-21 新增: streaming retry + memory prefetch（对齐 Claude Code）

---

## 目录

1. [架构总览](#1-架构总览)
2. [核心概念名词解释](#2-核心概念名词解释)
3. [Harness — Agent 循环](#3-harness--agent-循环)
4. [Loop 控制 — 迭代与终止](#4-loop-控制--迭代与终止)
5. [工具管理](#5-工具管理)
6. [工具调用优先级](#6-工具调用优先级)
7. [Memory 管理](#7-memory-管理)
8. [Hook 系统](#8-hook-系统)
9. [关键流程节点提示词对比](#9-关键流程节点提示词对比)
10. [差距分析](#10-差距分析)

---

## 1. 架构总览

### Claude Code

```
┌──────────────────────────────────────────────────────────────────┐
│                    QueryEngine.submitMessage()                    │
│  (生命周期管理, SDK 协议, 会话状态)                               │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  fetchSystemPromptParts()                                        │
│  ┌─────────────┐ ┌──────────┐ ┌───────────┐                     │
│  │ getSystem   │ │ getUser  │ │ getSystem │                     │
│  │ Prompt()    │ │ Context()│ │ Context() │                     │
│  │ (tools,     │ │ (CLAUDE  │ │ (git      │                     │
│  │  model, mcp)│ │ .md,     │ │  status)  │                     │
│  └─────────────┘ │ date)    │ └───────────┘                     │
│                  └──────────┘                                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │ asSystemPrompt()
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                    query() / queryLoop()                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  while (true):                                           │   │
│  │  1. Message prepare (compact, budget, collapse)          │   │
│  │  2. callModel() → Anthropic API (streaming)              │   │
│  │  3. Process assistant response                            │   │
│  │  4. tool_use blocks found?                               │   │
│  │     ├─ Yes → execute tools → append results → continue   │   │
│  │     └─ No  → return { reason: 'completed' }              │   │
│  │  5. Check maxTurns / tokenBudget / hooks                 │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  Tool System (src/Tool.ts + buildTool())                         │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐    │
│  │ Core Tools  │ │ MCP Tools   │ │ ToolSearchTool         │    │
│  │ (Bash, Read,│ │ (deferred,  │ │ (discovers deferred    │    │
│  │  Write...)  │ │  lazily     │ │  tools via keyword or  │    │
│  │ alwaysLoad  │ │  loaded via │ │  select: syntax)       │    │
│  │             │ │  tool_ref)  │ │                        │    │
│  └─────────────┘ └──────────────┘ └────────────────────────┘    │
│  ALL tools are Tool[] array, filtered by isDeferredTool()       │
└──────────────────────────────────────────────────────────────────┘
```

### GenSci Agent

```
┌──────────────────────────────────────────────────────────────────┐
│  routes.py: HTTP Handler                                         │
│  ┌──────────────────┐  ┌────────────────────────────┐            │
│  │ POST /api/llm/   │  │ POST /api/llm/literature/ │            │
│  │ chat/stream      │  │ stream                    │            │
│  │ (Free Analysis)  │  │ (Literature/Tissue Worksp)│            │
│  └────────┬─────────┘  └─────────────┬──────────────┘            │
│           │                          │ inject context             │
└───────────┼──────────────────────────┼───────────────────────────┘
            │                          │
            ▼                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  llm_proxy.py                                                    │
│  process_chat_streaming() / process_literature_chat_streaming()  │
│  (thin delegation shim → SSE format wrapping)                    │
└────────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  agent/__init__.py: process_chat_streaming()                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  for iteration in range(max_iterations):                 │   │
│  │  1. assemble_prompt() → 综合系统提示                     │   │
│  │  2. _stream_sse() → DeepSeek API (streaming)             │   │
│  │  3. Process assistant response                            │   │
│  │  4. tool_calls found?                                     │   │
│  │     ├─ Yes → execute tools (ThreadPool, 3 workers)        │   │
│  │     │        → run_post_tool hooks                        │   │
│  │     │        → append results → continue                  │   │
│  │     └─ No  → yield done → return                          │   │
│  │  5. Near-limit nudge (iter >= max-3)                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Tool System (core/tool.py + tools/)                             │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐    │
│  │ Core Tools  │ │ MCP Tools   │ │ ToolSearchTool         │    │
│  │ (shell,     │ │ (52 MCP     │ │ (searches ALL_TOOLS    │    │
│  │  skill,     │ │  tools,     │ │  by is_deferred flag)   │    │
│  │  memory*)   │ │  full schema│ │                        │    │
│  │             │ │  in fn call) │ │                        │    │
│  └─────────────┘ └──────────────┘ └────────────────────────┘    │
│  ALL TOOLS is list[Tool], unified registry                       │
│  Prompt: 8 个章节 ~200 行的系统提示                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心概念名词解释

### Harness（代理引擎）

| 概念 | 说明 |
|------|------|
| **Harness** | Agent 运行的主循环框架。包含系统提示词组装、LLM 调用、工具执行、结果处理的全流程编排 |
| **Claude Code Harness** | `QueryEngine.submitMessage()` + `queryLoop()` — 三层架构：外层生命周期管理 → 中层 while(true) 循环 → 内层 LLM API 调用 |
| **GenSci Harness** | `process_chat_streaming()` — 单层循环，for-range 迭代，集成在 agent/__init__.py 中，无独立 harness 层 |

### Loop（循环）

| 概念 | 说明 |
|------|------|
| **Turn** | 一次完整的"LLM 请求 → 响应 → 工具执行 → 结果回传"循环 |
| **queryLoop** | Claude Code 的 `while(true)` 主循环。每次 turn 从消息准备、压缩、API 调用到工具执行 |
| **maxTurns** | Claude Code 的安全边界参数。子 agent 默认 200 轮，主线无上限。达到后返回 `reason: 'max_turns'` |
| **max_iterations** | GenSci 的循环安全边界。两个 agent 统一 50 轮（对应 maxTurns）。达到后 yield done with warning |
| **Streaming** | SSE（Server-Sent Events）协议流式返回 LLM 响应。两个 agent 均使用 streaming 模式 |

### Hook（钩子）

| 概念 | 说明 |
|------|------|
| **Hook** | 在 Agent 生命周期的特定节点触发的扩展逻辑。用于权限控制、日志、验证等 |
| **PreToolUse** | 工具执行前触发。可拦截、修改输入、允许/拒绝 |
| **PostToolUse** | 工具执行后触发。可注入额外上下文、修改结果 |
| **Stop** | Agent 即将结束响应前触发。可阻止结束、追加内容 |
| **SessionStart** | 会话开始时触发。注入初始上下文、设置监听路径 |

### Tool 管理

| 概念 | 说明 |
|------|------|
| **Tool** | Agent 可调用的功能单元。有 name/description/input_schema/output_schema/call |
| **isDeferred** | 标记工具是否延迟加载。Claude Code 中 MCP 工具默认 deferred，GenSci 中根据 API 协议决定 |
| **tool_reference** | Anthropic API 专有特性。ToolSearchTool 返回 `tool_reference` block，API 自动将工具 schema 注入后续 function calling |
| **alwaysLoad** | 标记工具始终加载，不被 defer。MCP 工具可通过 `_meta['anthropic/alwaysLoad']` 设置 |

### Memory 管理

| 概念 | 说明 |
|------|------|
| **memdir** | Claude Code 的文件记忆系统。`~/.claude/projects/<project>/memory/` 目录 |
| **MEMORY.md** | 记忆索引文件。列出所有记忆文件的名称和描述。行上限 200，字节上限 25KB |
| **Memory Type** | 记忆类型：`user`（用户画像）、`feedback`（反馈）、`project`（项目）、`reference`（参考） |
| **Memory Prefetch** | 对话开始时后台异步加载相关记忆，不阻塞首轮响应 |

### Skill（技能）

| 概念 | 说明 |
|------|------|
| **Skill** | 可复用的领域能力封装。GenSci 中用 SKILL.md 文件定义，或注册为 callable tool |
| **SKILL.md** | Markdown 格式的技能文档。包含技能描述、使用规则、参数说明 |
| **skill("name")** | 通过 SkillTool 读取技能内容并执行。GenSci 中 SKILL.md-only 技能通过此方式调用 |

---

## 3. Harness — Agent 循环

### Claude Code 的 queryLoop

```
queryLoop()
│
├─ prepareMessages()
│   ├─ snip compact (截断最旧消息)
│   ├─ microcompact (缓存感知压缩)
│   ├─ context collapse (上下文折叠)
│   └─ auto compact (摘要压缩)
│
├─ buildSystemPrompt()
│   ├─ default system prompt (来自 constants/prompts.ts)
│   ├─ user context (CLAUDE.md, 当前日期)
│   └─ system context (git status)
│
├─ callModel() → Anthropic API
│   ├─ tools → toolToAPISchema() (defer/deferred 过滤)
│   ├─ system → buildSystemPromptBlocks() (缓存分块)
│   └─ stream → 实时处理 content + tool_use
│
├─ processAssistantResponse()
│   ├─ 收集 content (给用户的消息)
│   ├─ 提取 tool_use blocks
│   └─ needsFollowUp = hasToolUseBlocks()
│
├─ handleErrors() [if any]
│   ├─ prompt_too_long → collapse drain → reactive compact
│   ├─ max_output_tokens → escalate 64k → recovery msg
│   └─ media_size → reactive compact strip
│
├─ runStopHooks() [if stop hook blocks → return]
│
├─ checkTokenBudget() [if diminishing returns → return]
│
├─ [needsFollowUp?]
│   ├─ YES:
│   │   ├─ executeTools() (并行或流式)
│   │   ├─ generateToolUseSummary()
│   │   ├─ injectAttachments() (memory, skill discovery)
│   │   ├─ checkMaxTurns() [if exceeded → return]
│   │   └─ nextState() → continue
│   │
│   └─ NO: return { reason: 'completed' }
```

### GenSci 的 process_chat_streaming()

```
process_chat_streaming()
│
├─ _init_mcp_tools() [if first call]
│
├─ assemble_prompt()  ← 重写后: 8 个章节 ~200 行
│   ├─ CORE_IDENTITY (角色定义)
│   ├─ CORE_RULES (4 条核心规则)
│   ├─ DATA_ACCESS (.h5ad 读取规范)
│   ├─ MEMORY_INSTRUCTIONS
│   ├─ IMAGE_DISPLAY_PROTOCOL ★ (图片返回完整协议)
│   ├─ SHELL_CONSTRAINTS (stdout 5k/stderr 1k/timeout 60s)
│   ├─ ERROR_RECOVERY (模块缺/文件找不到/超时处理)
│   ├─ CONVERSATION_RULES (多轮对话/停止策略)
│   ├─ OUTPUT_FORMAT (Markdown 规范)
│   ├─ 可用技能列表 (scan_skills())
│   └─ intent hints + 前轮结果摘要
│
├─ Inject system-reminder (技能提醒 + 图片协议提醒)
│
├─ _stream_sse() → DeepSeek API (OpenAI 格式)
│   ├─ messages + tools (所有工具的 schema)
│   └─ stream → 实时处理 content + tool_calls delta
│
├─ processAssistantResponse()
│   ├─ 收集 content (SSE message 事件)
│   ├─ 合并 tool_calls delta 流
│   └─ tcl = list(collected_tc.values())
│
├─ [tcl 非空?]
│   ├─ YES:
│   │   ├─ executeTools() (ThreadPool, max_workers=3)
│   │   ├─ run_post_tool() hooks
│   │   │   ├─ _hook_image_return (检测图片协议)
│   │   │   └─ _hook_error_recovery (错误恢复指引)
│   │   ├─ nearLimitNudge() (iter >= max-3 → 注入总结指令)
│   │   └─ continue
│   │
│   └─ NO: yield done → return
│
└─ [loop exit] yield done with warning
```

### 对比

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| 循环结构 | `while (true)`，State 突变 | `for iteration in range(N)` |
| 消息压缩 | 多层：snip→microcompact→collapse→autocompact | ❌ 无压缩 |
| 错误恢复 | prompt_too_long / max_output_tokens 多层兜底 | API 重试 2 次 + hooks 错误指引 |
| 停止机制 | LLM 不调工具 → `reason: 'completed'` | LLM 不调工具 → `event: done` |
| 安全边界 | `maxTurns` (子 agent 200) + tokenBudget | `max_iterations=50` |
| Streaming | Anthropic SDK 原生流式 | 自建 SSE + _stream_sse() |
| 系统提示 | `buildSystemPromptBlocks()` 缓存分块 | `assemble_prompt()` 完整拼接 |
| 图片协议 | Read 工具原生支持展示图片 | 需专门的 markdown 标签 + /api/results 端点 |

---

## 4. Loop 控制 — 迭代与终止

### Claude Code

```
queryLoop() Continue/Return 决策树:

LLM API 返回
  ├─ tool_use blocks 存在
  │   ├─ 执行工具
  │   ├─ check maxTurns → 超限则 return {reason: 'max_turns'}
  │   ├─ check tokenBudget → 递减则 return {reason: 'diminishing_returns'}
  │   ├─ check abortSignal → 中断则 return {reason: 'aborted_tools'}
  │   └─ state = {..., transition: {reason: 'next_turn'}} → continue
  │
  └─ tool_use blocks 不存在
      └─ return {reason: 'completed'}
      
外层 QueryEngine 捕获 attachment 'max_turns_reached'
  └─ yield {type: 'result', subtype: 'error_max_turns'}
```

### GenSci

```
process_chat_streaming() 终止决策:

LLM API 返回 (一轮 streaming 完成)
  ├─ collected_tc 非空 (有 tool_calls)
  │   ├─ 执行工具 (ThreadPool)
  │   ├─ run_post_tool() hooks
  │   │   ├─ _hook_image_return → 检测图片并引导协议
  │   │   └─ _hook_error_recovery → 错误恢复指引
  │   ├─ near-limit nudge: iter >= max_iterations - 3
  │   │   └─ inject "请立即总结" 消息
  │   └─ continue 进入下一轮
  │
  └─ collected_tc 为空 (无 tool_calls)
      ├─ yield {event: 'done', data: {final: true}}
      └─ return 正常结束

循环自然结束 (iter >= max_iterations)
  └─ yield {event: 'done', data: {final: true, warning: 'Max iterations reached'}}
```

### 对比

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| 正常终止 | LLM 无 tool_use → `reason: 'completed'` | LLM 无 tool_calls → `done final: true` |
| 超限终止 | `maxTurns` 超限 → `error_max_turns` | `max_iterations` 超限 → `done warning` |
| Token Budget | ✅ 有 diminishing returns 检测 | ❌ 无 |
| Abort 信号 | ✅ AbortController + signal | ✅ 前端有 AbortController |
| 预终止提示 | ❌ 无（Claude 主动停） | ✅ near-limit nudge（适配 DeepSeek） |
| Post-Tool Hooks | ❌ 无 post-tool（靠模型决策） | ✅ image_return + error_recovery |

---

## 5. 工具管理

### 工具注册方式对比

```
Claude Code                           GenSci
───────────                           ──────
Tool = buildTool({                    Tool = dataclass(...)
  name: 'Bash',                       register_tool(name='shell', ...)
  description: ...,                   def shell(...)
  inputSchema: z.object(...),
  outputSchema: z.string(),
  call: async (input) => {...},
  isMcp: false,
  shouldDefer: false,
  maxResultSizeChars: 100_000,
})

Tools = Tool[]                        ALL_TOOLS: list[Tool]

isDeferredTool(tool):                 ALL_TOOLS 权限过滤:
  if tool.alwaysLoad → false            tools_filter (list of names)
  if tool.isMcp → true                  ---
  if tool.name == 'ToolSearch' → false  MCP 工具不 defer
  return tool.shouldDefer               (OpenAI 协议, 无 tool_reference)

ToolSearchTool                        ToolSearchTool
  returns tool_reference blocks         searches ALL_TOOLS by is_deferred flag
  → API auto-injects schema             → returns schema as text
  (Anthropic 协议专有)                   (OpenAI 协议, 无 tool_reference)
```

### 工具描述详细度对比

| 工具 | Claude Code | GenSci (当前) |
|------|-------------|---------------|
| **Shell/Bash** | 含：用途、约束、返回值、示例 | ✅ 已更新：约束/stdout截断/图片协议/错误恢复 |
| **Skill** | 含：调用规则、权限控制 | ✅ 基本一致（无权限控制） |
| **Memory Read** | 含：三种模式、参数 | ✅ 已更新：用途/三种模式/典型场景 |
| **Memory Write** | 含：类型、使用场景 | ✅ 已更新：类型说明/自动索引 |
| **Memory Delete** | ❌ Claude Code 无删除 | ✅ GenSci 有 |

### 工具列表

```
Claude Code 核心工具                    GenSci 核心工具
─────────────────                     ────────────────
BashTool (shell)                       shell ✅ (含截断/图片协议描述)
FileReadTool                           ❌
FileWriteTool                          ❌
FileEditTool                           ❌
GlobTool                               ❌
GrepTool                               ❌
SkillTool                              skill ✅
ToolSearchTool                         tool_search ✅
AgentTool                              ❌
MCPTool (所有 MCP 工具, deferred)      MCPTool (52 工具, 不 defer)
Memory tools (read/write)              memory_read/write/delete ✅

GenSci 独有:
- memory_delete（Claude Code 无显式删除工具）
- 工具 description 含图片协议指引
```

### 关键差异：MCP 工具处理

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| MCP 初始加载 | Deferred（仅名称在 system prompt） | 不 defer（完整 schema 在 function calling） |
| 发现机制 | `tool_search` → `tool_reference` → API 自动注入 | `tool_search` → 返回纯文本 schema |
| 调用方式 | LLM 直接 function calling（名称已注入） | LLM 直接 function calling（schema 已知） |
| 协议依赖 | 依赖 Anthropic API `tool_reference` | 兼容 OpenAI/Anthropic 双协议 |
| 总工具数 | 核心~10 + MCP 动态 | 6 native + 52 MCP = 58 |

---

## 6. 工具调用优先级

### Claude Code

```
LLM 响应中的 tool_use blocks 处理顺序:

1. ALL_TOOLS 数组中按名称匹配
2. 优先执行:
   - 非 deferred 工具（已经在 function calling schema 中）
   - 已发现的 deferred 工具（之前 tool_search 返回过）
3. 权限检查 (checkPermissions):
   - hook 自动允许 → 执行
   - hook 自动拒绝 → 报错
   - 无 hook → 弹交互对话框 → 用户批准/拒绝
4. 并发: 无限制（模型决定并行度）
```

### GenSci

```
LLM 响应中的 tool_calls 处理顺序:

1. ALL_TOOLS 列表按名称匹配 (next(t for t in ALL_TOOLS if t.name == name))
2. 优先执行:
   - 所有 58 工具均在同一 schema（无 defer 区分）
   - MCP 工具按 is_mcp 路由到 MCPManager.call_tool()
   - Native 工具按 fn 直接调用
3. 权限检查: ❌ 无（直接执行，无用户确认）
4. 并发: ThreadPoolExecutor(max_workers=3)
5. Post-Tool: run_post_tool() hooks → image_return + error_recovery
```

### 对比

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| 发现顺序 | deferred → tool_search → 注入 schema → 可调用 | 所有工具都在 schema 中，直接可调 |
| 执行路由 | all tools → name match | ALL_TOOLS → name match → is_mcp? → MCP/fn |
| 权限控制 | hook 允许/拒绝/交互对话框 | ❌ 无权限控制，直接执行 |
| 并发执行 | 无限制（模型决定） | 最多 3 个并行 |
| 超时控制 | 无硬超时（可配） | future.result(timeout=30) |
| 失败处理 | 结果返回 LLM，模型决定后续 | 结果返回 LLM + post-tool error hooks |
| Post-Tool 注入 | ❌ 无（靠系统 prompt 记忆） | ✅ image_return + error_recovery hooks |

---

## 7. Memory 管理

### 架构对比

```
Claude Code memdir                    GenSci memory
────────────────                     ──────────────
~/.claude/projects/<proj>/memory/    server/memory/
├── MEMORY.md (入口索引)              ├── MEMORY.md (入口索引)
├── user-profile.md                   ├── <相同结构>
├── feedback-*.md
└── project-*.md

记忆类型:                             记忆类型:
  user / feedback / project /           user / feedback / project /
  reference                             reference ✅

文件格式:                             文件格式:
  Markdown + YAML frontmatter           Markdown + YAML frontmatter ✅
  ---                                  ---
  name: short-kebab-case               name: short-kebab-case
  description: ...                     description: ...
  metadata:                            metadata:
    type: user | feedback | ...          type: user | feedback | ...

关联机制:                             关联机制:
  [[memory-name]] 交叉引用              [[memory-name]] 交叉引用 ✅

加载方式:                             加载方式:
  buildMemoryPrompt() 在 query 前置     memory_read 工具按需读取
  startRelevantMemoryPrefetch()        ❌ 无后台预取
  后台异步加载，不阻塞首轮
```

### 访问方式

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| 读取 | `memory_read("query")` 工具 | `memory_read(query)` 工具 ✅ |
| 写入 | `memory_write(name, content, type)` 工具 | `memory_write(name, content, type)` 工具 ✅ |
| 删除 | ❌ 无删除工具（文件系统操作） | `memory_delete(name)` 工具 |
| 预取 | ✅ `startRelevantMemoryPrefetch()` 首轮后台加载 | ❌ 无预取 |
| 入口注入 | ✅ `buildMemoryPrompt()` 自动注入前置消息 | ❌ 无自动注入 |

---

## 8. Hook 系统

### Claude Code 的 26 个事件

```
工具生命周期:
  PreToolUse       → 工具执行前 (拦截、修改、允许/拒绝)
  PostToolUse      → 工具执行后 (注入额外上下文)
  PostToolUseFailure → 工具执行失败
  PermissionRequest  → 权限请求时
  PermissionDenied   → 权限拒绝后

会话生命周期:
  SessionStart     → 新会话创建 (注入初始上下文)
  SessionEnd       → 会话结束
  Stop             → Agent 即将结束响应前
  StopFailure      → 响应因错误结束
  UserPromptSubmit → 用户提交提示词时

Agent/任务:
  SubagentStart/Stop → 子 Agent 生命周期
  TeammateIdle     → 队友空闲
  TaskCreated/Completed → 任务创建/完成

其他:
  Notification, PreCompact, PostCompact, Setup,
  ConfigChange, InstructionsLoaded,
  Elicitation/ElicitationResult,
  WorktreeCreate/Remove, CwdChanged, FileChanged
```

### GenSci 的 Hook 系统（v4 升级后）

```
server/engine/hooks.py:
  run_pre_tool(name, args) → 单 pre-tool 钩子 (当前无注册)
  run_post_tool(name, args, result) → 串行执行所有 post-tool 钩子

当前已注册:
  1. _hook_image_return
     - 触发: tool 返回的 stdout 含 plt.savefig/matplotlib/seaborn/.png 等
     - 条件: stdout 中未包含 /api/results?file= 标签
     - 行为: 注入图片协议指引 → 引导 LLM 正确输出 markdown 标签
     - 文件: server/engine/hooks.py _hook_image_return()
  
  2. _hook_error_recovery
     - 触发: tool 返回 error
     - 行为: 按错误类型注入恢复指引
       - ModuleNotFoundError → "pip install <module>"
       - FileNotFoundError → "用 ls/find 确认路径"
       - TimeoutError → "增大 timeout 或减小数据量"
       - 其他 → "检查参数或换方案"
     - 文件: server/engine/hooks.py _hook_error_recovery()

system-reminder 注入:
  agent/__init__.py 在第 1 轮注入:
  - 技能提醒：先检查技能，不要自己写代码
  - 图片协议提醒：保存 /tmp/gensci_results/ → stdout 输出 markdown → 回复包含标签
```

### 对比

| 特性 | Claude Code | GenSci |
|------|-------------|--------|
| 事件数量 | 26 个 | 3 个（pre_tool 框架 + 2 个 post_tool） |
| 钩子类型 | command/prompt/agent/http/callback/function | callback（Python 函数） |
| 注册方式 | settings.json + 插件 | `register_post_tool()` 装饰器 |
| 并行执行 | 所有钩子并行 + 结果聚合 | 串行调用 |
| 权限控制 | PreToolUse 可拦截/允许/拒绝 | ❌ 无权限钩子 |
| 持久化 | settings.json 配置，支持 source 优先级 | 硬编码在 engine/hooks.py 中 |
| 异步支持 | ✅ async + pub/sub event system | ❌ 同步 |
| 超时控制 | ✅ 每钩子独立 timeout | ❌ 无超时 |

---

## 9. 关键流程节点提示词对比

### 9.1 系统提示词组装

```
Claude Code 系统提示词构成 (buildSystemPromptBlocks):
──────────────────────────────────────────────────
1. ATTRIBUTION_HEADER ("x-anthropic-billing-header")
2. CLI_SYSPROMPT_PREFIX ("You are Claude Code...")
3. 核心指令 (工具使用、记忆、CLAUDE.md)
4. 模型配置 (fast mode, thinking)
5. MCP 工具列表 (deferred tools 名称)
6. 技能列表 (skills/plugins)
   ──────────────────── DYNAMIC_BOUNDARY ────────────────────
7. 日期 (当前日期)
8. Git 状态
   ↑ 缓存分界: 1-6 设 cache_control: ephemeral (global),
     7-8 不缓存 (每次更新)

GenSci 系统提示词构成 (assemble_prompt)  ← v4 升级后
──────────────────────────────────────────
1. CORE_IDENTITY (角色定义)
2. CORE_RULES (4 条核心规则)
3. 当前日期 + 数据集路径
4. DATA_ACCESS (.h5ad 读取规范, 跨组织遍历)
5. MEMORY_INSTRUCTIONS (4 种类型)
6. IMAGE_DISPLAY_PROTOCOL ★ (CRITICAL)
   - 保存到 /tmp/gensci_results/
   - stdout 输出 markdown 标签
   - 回复中必须包含该标签
   - 反面案例：HTML img/Base64 不可用
7. SHELL_CONSTRAINTS
   - stdout 5k / stderr 1k / timeout 60s
   - 截断绕过方法
8. ERROR_RECOVERY (模块缺/文件找不到/超时处理)
9. CONVERSATION_RULES (多轮对话/停止策略)
10. OUTPUT_FORMAT (Markdown 规范/图文混排)
11. 可用技能列表
12. Intent hints + 前轮结果摘要
13. "Call the tool, then explain results in plain language."
    ↑ 无缓存分块, 无 dynamic boundary
    ↑ 约 200 行 / 8000 字符
```

### 9.2 工具描述提示词

```
Claude Code ShellTool PROMPT:            GenSci ShellTool PROMPT (v4):
─────────────────────────────            ─────────────────────────────
"Executes a command..."                  SHELL_DESCRIPTION:
                                          "Execute shell commands. Use this to
                                           run Python/R scripts, install packages,
                                           manipulate files... 
                                          ### Constraints
                                          - stdout: 5,000 chars max
                                          - stderr: 1,000 chars max  
                                          - Timeout: 60 seconds
                                          ### Image Protocol
                                          1. Save to /tmp/gensci_results/{uuid}.png
                                          2. Print ![desc](/api/results?file=...) to stdout
                                          3. LLM MUST echo in response
                                          ### Error Recovery
                                          - Module not found → pip install
                                          - File not found → verify path"

Claude Code SkillTool PROMPT:            GenSci SkillTool PROMPT:
──────────────────────────────           ──────────────────────────
"Execute a skill within the              与 Claude Code 基本一致
 main conversation..."
 (含 skill 发现 + 权限 + 子 agent)
```

### 9.3 记忆指令

```
Claude Code MEMORY_INSTRUCTIONS:         GenSci MEMORY_INSTRUCTIONS:
─────────────────────────────────        ────────────────────────────
"## Types of memory                     "## Memory System
 There are several discrete types..."     You have a persistent
 (xml 标签格式, <types><type><name>...)    file-based memory..."
 4 种类型各有详细描述                      Markdown + YAML frontmatter
 <scope>private/team</scope>              memory_read/write/delete
 <when_to_save><how_to_use>               ❌ 无 scope（无 team mode）
 <examples>...</examples>                 基本对齐 ✅
```

### 9.4 图片返回指令 ★

```
Claude Code（原生支持）:
- Read 工具能直接读取图片文件并展示
- 生成 → 保存 → Read → 显示
- 不需要特殊协议

GenSci（需手动遵守）:
- Image Display Protocol (★ CRITICAL)
- 生成 Python 图 → 保存到 /tmp/gensci_results/ → stdout 输出 markdown 标签
  → LLM 在回复中 echo 标签 → ChatPanel ReactMarkdown 渲染
- 在系统 prompt 中明确写明步骤
- 在 system-reminder 中额外提醒
- 在 post-tool hooks 中 (image_return) 自动检测并引导
```

### 9.5 迭代策略指令

```
Claude Code:                             GenSci (当前):
───────────                              ──────────────
无迭代策略指令                            系统 prompt 的 CONVERSATION_RULES:
（不干预 LLM 决策）                       "Once you have enough information to answer,
                                          synthesize and present results.
                                          Do not call tools just to confirm correct output.
                                          If you hit the iteration limit, conclude with what you have."
                                         + near-limit nudge (harness 层注入):
                                           "已到对话轮次上限边缘，请根据已获取的信息立即生成最终总结"
```

### 9.6 错误恢复指令

```
Claude Code:                             GenSci (v4 新增):
───────────                              ──────────────────
错误由引擎自动处理：                      系统 prompt 的 ERROR_RECOVERY 章节:
- prompt_too_long → 自动压缩            "When a tool reports an error:
- max_output_tokens → 自动升级            Shell errors → check stderr → pip/ls/fix
- API 错误 → 自动重试                      API errors → retry
- 不放在 prompt 中 (engine 层处理)          Tool errors → adjust params → retry
                                          If fails 2+ times → switch strategy"
                                         + _hook_error_recovery 自动注入指引
```

---

## 10. 差距分析

### 已对齐 ✅

| 维度 | 状态 |
|------|------|
| Tool 统一注册 `list[Tool]` | ✅ `ALL_TOOLS: list[Tool]` |
| Flat 工具数组 | ✅ 不分层，统一列表 |
| `is_deferred_tool()` | ✅ `core/tool.py` 实现 |
| `build_tool()` 工厂 | ✅ `core/tool.py` 实现 |
| `register_tool()` 装饰器 | ✅ `core/tool.py` 实现 |
| MCP 工具统一路由 | ✅ `Tool.call()` → is_mcp → MCPManager |
| 文件记忆 memdir | ✅ 4 类型 + MEMORY.md ✅ |
| 安全边界 | ✅ `max_iterations=50` |
| Tool 描述逐工具展开 | ✅ Shell/Skill/Memory 均有详细描述 ✅ |
| 图片返回协议 | ✅ 系统提示 + reminder + hooks 三层指引 ✅ |
| 错误恢复指引 | ✅ system prompt + post-tool hooks ✅ |
| Post-Tool 自动注入 | ✅ image_return + error_recovery hooks ✅ |

### 未对齐 ❌

| 维度 | Claude Code | GenSci | 优先级 |
|------|-------------|--------|--------|
| Token budget | 有 diminishing returns 检测 | ❌ 无 | P2 |
| 消息压缩 | snip→microcompact→autocompact | ❌ 无 | P2 |
| 权限系统 | hook + 交互式批准/拒绝 | ❌ 无 | P1 |
| MCP 沙箱 | 有 sandbox 隔离 | ❌ 无 | P2 |
| API 重试 (streaming) | 有 (模型降级) | ✅ 有（2026-07-21 新增重试） | P1（已对齐） |
| Hook 系统 | 26 事件 + 4 类型 | 3 个 post-tool | P3 |
| Memory 预取 | 后台异步加载 | ❌ 无 | P2 |
| 模型降级 | 自动降级到 fallback model | ❌ 无 | P2 |
| Tool 结果持久化 | maxResultSizeChars + 磁盘备份 | 50000 字符硬截断 | P3 |
| 子 Agent | AgentTool + forkSubagent | ❌ 无 | P3 |
| 话题分支/恢复 | 全消息链快照 | ❌ 线性 | P3 |
| 消息缓存分块 | buildSystemPromptBlocks 缓存分界 | ❌ 无缓存 | P2 |
| 图片原生展示 | Read 工具原生支持 | ❌ 需 markdown 标签 + /api/results 端点 | ❌ 架构差异 |

### 2026-07-21 新增对齐 ✅

| 维度 | Claude Code | GenSci | 代码证据 |
|------|-------------|--------|---------|
| Streaming API 重试 | 自动重试 + 模型降级 | ✅ `_stream_sse()` 新增 502/503/504 重试（指数退避，最多 2 次），网络超时/断连也触发重试 | `server/llm_proxy.py` |
| Memory 预取 | `startRelevantMemoryPrefetch()` 后台异步 | ✅ `process_chat_streaming()` 启动时自动搜索相关记忆并注入 system prompt | `server/agent/__init__.py` |

### P1（短期优先）

1. **Streaming 路径 API 重试** — ✅ **已对齐**（2026-07-21 新增 `_stream_sse()` 502/503/504 重试）
2. **基本权限控制** — shell/skill 工具执行前至少加一次用户确认

### P2（中期）

3. **消息压缩** — 长对话时自动摘要历史消息
4. **Memory 预取** — ✅ **已对齐**（2026-07-21 新增启动时自动预取）
5. **模型降级** — DeepSeek 失败时自动切备用模型
6. **Token budget** — 按轮次 token 消耗递减自动停止

### P3（长期）

7. **Hook 系统扩展** — PreToolUse / PostToolUse / Stop 事件
8. **子 Agent 支持** — LLM 可 spawn 子 Agent 并行处理
9. **话题分支** — 从任意历史节点恢复对话
10. **Tool 结果磁盘持久化** — 大结果自动存文件

---

## 11. 逐维对齐详情

### 架构层

| 维度 | Claude Code | GenSci | 对齐度 | 代码证据 |
|------|-------------|--------|--------|---------|
| Agent 循环 | `queryLoop()`: while(true) + State 突变 | `process_chat_streaming()`: for-range | ⚡ 功能对齐 | `server/agent/__init__.py` |
| 系统提示组装 | `buildSystemPromptBlocks()` 缓存分块 | `assemble_prompt()` 13 章节拼接 | ⚡ 功能对齐 | `server/agent/prompt.py` |
| 消息压缩 | snip→microcompact→autocompact | ❌ 无 | ❌ | — |
| 无工具终止 | LLM 不调工具 → `reason: 'completed'` | LLM 不调工具 → `event: done` | ✅ | `agent/__init__.py:264` |
| 超限终止 | maxTurns → `error_max_turns` | max_iterations → `done warning` | ✅ | `agent/__init__.py:347` |
| Streaming | Anthropic SDK 原生流式 | 自建 SSE + 15s 心跳 | ⚡ 功能对齐 | `server/llm_proxy.py` + `server/routes.py:463` |
| API 重试 (非 streaming) | 自动重试 + 模型降级 | 2 次重试 (429/502/503/504) | ✅ | `agent/__init__.py:520` |
| API 重试 (streaming) | 有 (模型降级) | ✅ 有（2026-07-21 新增 502/503/504 重试） | ✅ | `llm_proxy.py:_stream_sse()` |

### 工具层

| 维度 | Claude Code | GenSci | 对齐度 | 代码证据 |
|------|-------------|--------|--------|---------|
| 工具注册 | `Tool[]` + `buildTool()` | `ALL_TOOLS: list[Tool]` + `build_tool()` | ✅ | `server/core/tool.py` |
| 统一路由 | Flat 数组，无 tier | Flat 数组 (`ALL_TOOLS`) | ✅ | `server/core/tool.py:14` |
| MCP 路由 | 统一 via Tool.call | `is_mcp` → MCPManager.call_tool() | ✅ | `agent/__init__.py:288` |
| Deferred 工具 | `isDeferredTool()` | `is_deferred_tool()` | ✅ | `core/tool.py:81` |
| Tool 搜索 | ToolSearchTool → tool_reference | `tool_search()` → 纯文本 schema | ⚡ 功能对齐 | `tools/ToolSearchTool/` |
| 线程安全 | 单线程 (Node.js) | `_all_tools_lock` + `threading.Lock()` | ✅ | `core/tool.py:16` |
| 权限控制 | hook + 交互式批准/拒绝 | ❌ 无 | ❌ | — |
| 并行执行 | 无限制（模型决定） | ThreadPoolExecutor(max_workers=3) | ⚡ 不同实现 | `agent/__init__.py:280` |
| 超时控制 | 无硬超时 | `future.result(timeout=120)` | ⚡ 更保守 | `agent/__init__.py:305` |
| 原生文件工具 | Read/Write/Edit/Glob/Grep | ❌ 无（依赖 shell） | ❌ | — |

### 记忆层

| 维度 | Claude Code | GenSci | 对齐度 | 代码证据 |
|------|-------------|--------|--------|---------|
| 存储模型 | memdir: `~/.claude/.../memory/` | `server/memory/` 目录 | ✅ | `server/memory/` |
| 索引文件 | MEMORY.md | MEMORY.md (自动更新) | ✅ | `server/memory/MEMORY.md` |
| 文件格式 | Markdown + YAML frontmatter | Markdown + YAML frontmatter | ✅ | `tools/MemoryWriteTool/` |
| 记忆类型 | user/feedback/project/reference | user/feedback/project/reference | ✅ | `tools/MemoryWriteTool/` |
| 交叉引用 | `[[memory-name]]` | `[[memory-name]]` | ✅ | `tools/MemoryWriteTool/` |
| 读取工具 | `memory_read("query")` | `memory_read(query)` | ✅ | `tools/MemoryReadTool/` |
| 写入工具 | `memory_write(name, content, type)` | `memory_write(...)` | ✅ | `tools/MemoryWriteTool/` |
| 删除工具 | ❌ 无（文件系统操作） | `memory_delete(name)` | ➕ GenSci 额外有 | `tools/MemoryDeleteTool/` |
| 预取机制 | `startRelevantMemoryPrefetch()` 后台异步 | ✅ 有（2026-07-21 新增，启动时自动搜索并注入） | ✅ | `agent/__init__.py` |
| 自动注入 | `buildMemoryPrompt()` 前置消息 | ⚡ 部分（预取注入 system message） | ⚡ | `agent/__init__.py` |

### Hook 层

| 维度 | Claude Code | GenSci | 对齐度 | 代码证据 |
|------|-------------|--------|--------|---------|
| 事件数量 | 26 个 | 3 个（pre + 2 post） | ❌ | `server/engine/hooks.py` |
| PreToolUse | 拦截/修改/允许/拒绝 | 空列表（框架就绪，无注册钩子） | ❌ | `engine/hooks.py:20` |
| PostToolUse | 工具执行后 | `image_return` + `error_recovery` | ⚡ 部分对齐 | `engine/hooks.py:39-76` |
| SessionStart | 新会话触发 | ❌ 无 | ❌ | — |
| Stop | 响应结束前 | ❌ 无（空列表） | ❌ | `engine/hooks.py:33` |
| 注册方式 | settings.json + 插件 | `register_post_tool()` 装饰器 | ⚡ 不同实现 | `engine/hooks.py:14` |
| 图片协议引导 | Read 原生支持 | post-tool 检测 + 注入提醒 | ⚡ 架构差异 | `engine/hooks.py:39` |
| 错误恢复 | 引擎自动处理 | post-tool 注入恢复指引 | ⚡ 功能对齐 | `engine/hooks.py:65` |

### 技能层

| 维度 | Claude Code | GenSci | 对齐度 | 代码证据 |
|------|-------------|--------|--------|---------|
| Skill 定义 | SKILL.md + 注册函数 | SKILL.md + 注册函数 | ✅ | `server/skills/` |
| 发现机制 | 插件扫描 | `scan_skills()` 目录扫描 | ✅ | `skills/_loader.py` |
| 执行方式 | `skill("name")` 工具 | `skill("name")` 工具 | ✅ | `tools/SkillTool/` |
| Tool 注册 | `@register_tool` | `@register_skill` → ALL_TOOLS + SKILL_REGISTRY | ⚡ 双注册 | `skills/__init__.py:69` |
| MCP 集成 | deferred + tool_reference | 完整 schema 在 function calling | ⚡ 协议差异 | `skills/__init__.py:116` |
