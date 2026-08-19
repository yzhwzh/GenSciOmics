# 缺陷日志 (Bug Log)

> 活文档 — 记录 GenSci 开发过程中发现和修复的所有缺陷。
> 每条记录包含：日期、现象、根因、修复方案、涉及文件。
> **新增缺陷请按序号追加，不要删除历史记录。**

---

## B1. Vite HMR WebSocket 断线触发页面刷新 (2026-07-14 ~ 2026-07-15)

### 现象
页面加载后约 30 秒自动执行 `location.reload()` 全量刷新。即使没有 LLM 请求也会发生。FreeAnalysis 中已输入的内容全部丢失。

### 根因
Vite HMR WebSocket 在连接后约 **28.8 秒自动断开**，客户端立即重连，但 Vite 在 WebSocket 重连后发送 `full-reload` 指令，浏览器执行 `location.reload()`。

```
T+367ms  [vite] connected.              ← WebSocket 连接成功
T+28782ms [vite] connecting...           ← WebSocket 断开（ws 库默认 ping timeout）
T+28793ms [vite] connected.              ← 重连成功
T+29000ms LOAD #2 (location.reload())    ← Vite 发送 full-reload 指令
```

**深层原因**：
- `ws` 库有默认的 ping/pong 超时机制，约 30 秒未收到 pong 即断开连接
- Vite 在 WebSocket 重新连接后自动发送 `full-reload` 以同步客户端状态
- `hmr.host: '10.243.163.51'` 使 WebSocket 通过 IP 连接，在某些网络环境下 ping/pong 不稳定

### 修复
1. `server/routes.py`: `Connection: keep-alive` → **`close`**（SSE 结束后正确关闭连接）
2. 添加 `X-Accel-Buffering: no` 头（nginx 兼容）
3. 添加**心跳线程**（每 15s 发 `: heartbeat\n\n`，tool 执行阶段保持 proxy 连接活跃）
4. `finally` 块中显式 `handler.connection.shutdown(SHUT_WR)` / `close()`
5. `vite.config.ts`: `hmr.timeout: 30000` → **`120000`**

### 涉及文件
- `server/routes.py` — SSE 响应头 + 心跳线程
- `vite.config.ts` — HMR timeout

### 验证方法
- SSE 响应头返回 `Connection: close`
- 需要用户在实际浏览器中验证页面 60 秒内无刷新

### 已知未解决问题
- `hmr.host` 设为 `'localhost'` 时 Playwright 无法正确加载页面
- `hmr.host` 设为 `'10.243.163.51'` 时 WebSocket 在约 29 秒断开
- **正式环境（production build）不存在此问题**，仅 Vite dev server 有 HMR 机制

---

## B2. FreeAnalysisTab 刷新后消息丢失 (2026-07-14)

### 现象
页面刷新后，FreeAnalysis 中的聊天记录不恢复（白板状态）。

### 根因
`FreeAnalysisTab.tsx` 用 `useState` 从 sessionStorage 恢复消息初始值，但 `storageKey` 依赖 `realPath` prop。

`realPath` 是异步加载的（`findDataset()` → `setRealPath()`），组件挂载时 `realPath` 为 `''`，所以 `useState` 的初始值读取的 key 是 `gensci_free_msgs_`（错误 key），永远拿不到之前保存的消息。

### 修复
添加 `useEffect` 监听 `realPath` 变化，加载完成后重新从 sessionStorage 恢复消息：

```typescript
useEffect(() => {
  if (!realPath) return
  const key = `gensci_free_msgs_${realPath}`
  const saved = sessionStorage.getItem(key)
  if (saved) setMessages(JSON.parse(saved))
}, [realPath])
```

### 涉及文件
- `src/components/analysis/FreeAnalysisTab.tsx`

---

## B3. FreeAnalysisTab Tab 切换消息丢失 (2026-07-13)

### 现象
切换到其他 Tab 再切回 Free Analysis，之前的聊天记录消失。

### 根因
组件无持久化机制，一旦组件 remount（如路由变化），状态丢失。

### 修复
添加 sessionStorage 持久化 `useEffect`，`messages` 变化时自动保存。

### 涉及文件
- `src/components/analysis/FreeAnalysisTab.tsx`

---

## B4. AnalysisPage activeTab 刷新后重置为 0 (2026-07-13)

### 现象
页面刷新后，AnalysisPage 的 activeTab 从当前 Tab 跳回 Study Info (Tab 0)。

### 根因
`activeTab` 状态无持久化，每次刷新回到默认值 0。

### 修复
`useState` 初始值从 sessionStorage 读取，`useEffect` 实时持久化。

### 涉及文件
- `src/pages/AnalysisPage.tsx`

---

## B5. Scanner Cache Key 不匹配导致启动缓慢 (2026-07-14)

### 现象
服务器启动需要 30-60 秒才能加载完所有数据集（正常应 <5 秒）。

### 根因
`.scanner_cache.json` 的 cache key 格式不一致：
- 旧文件：resolved path（`/data/yuanwuzhou/08.GEO/...`）
- 新代码：symlink path（`Data/Human/Kidney/...`）

导致每次读取缓存全部 miss，必须重新扫描所有 60+ 个 h5ad 文件。

### 修复
1. 删除旧的 `.scanner_cache.json`
2. 首次扫描用正确的 symlink-path key 重建缓存
3. 之后重启只需 mtime 比对，无需打开 h5ad

### 涉及文件
- `server/scanner.py` — cache key 从 `str(real)` 改为 `str(path)`

---

## B6. Scanner 数据重复 (2026-07-13)

### 现象
同一数据集在 `/api/datasets` 中出现两次。

### 根因
cache key 使用 resolved path，多个 symlink 指向同一文件时产生重复条目。

### 修复
cache key 改为 symlink path，每个 symlink 只记录一次。

### 涉及文件
- `server/scanner.py`

---

## B7. MCP Tools 未注册 (2026-07-13)

### 现象
LLM Agent 找不到 MCP 工具，只能使用 native 函数。

### 根因
`_init_mcp_tools()` 在 streaming 路径中未被调用。

### 修复
在 `process_chat_streaming()` 开始时调用 `_init_mcp_tools()`。

### 涉及文件
- `server/agent/__init__.py`

---

## B8. Literature Agent 迭代次数过少 (2026-07-13)

### 现象
Literature Agent 在完成搜索后无法输出总结，报 "Max iterations reached"。

### 根因
Literature 有独立的 `MAX_LITERATURE_ITERATIONS = 6`，执行搜索+分析+总结需要更多轮数。

### 修复
删除 `MAX_LITERATURE_ITERATIONS`，统一使用 `max_iterations=50`。

### 涉及文件
- `server/llm_proxy.py`

---

## B9. FreeAnalysisTab Stop 按钮无效 (2026-07-13)

### 现象
点击 Stop 按钮无法停止 LLM 响应流。

### 根因
`sendChatMessageStreaming()` 未接收 AbortSignal，`fetch()` 无法被取消。

### 修复
- `sendChatMessageStreaming()` 新增 `signal?: AbortSignal` 参数
- `fetch()` 调用传入 `signal`
- `handleStop` 调用 `abortRef.current?.abort()`

### 涉及文件
- `src/api/analysis.ts`
- `src/components/analysis/FreeAnalysisTab.tsx`

---

## B10. ALL_TOOLS 线程不安全 (2026-07-13)

### 现象
多线程同时注册 Tool 时可能导致 `ALL_TOOLS` 数据竞争。

### 根因
`ALL_TOOLS` 是共享的 `list[Tool]`，无锁保护。

### 修复
添加 `_all_tools_lock`，通过 `add_tool()` 以 context manager 方式安全写入。

### 涉及文件
- `server/core/tool.py`

---

## B11. 后端端口混乱 (2026-07-14)

### 现象
Vite proxy 将 `/api` 请求代理到 `127.0.0.1:6000`，但后端实际在 7070 端口运行，导致 API 全部返回空。

### 根因
服务器被从 6000 移到 7070 但 proxy target 未同步更新。同时存在多个 Python 服务实例。

### 修复
杀掉所有 Python 服务进程，在 6000 端口重新启动。

### 涉及文件
- `server/main.py`（端口参数）
- `vite.config.ts`（确认 proxy target 对齐）

---

## B12. Literature Agent 近限 nudge 不足 (2026-07-13)

### 现象
Literature Agent 在迭代接近上限时无法及时总结。

### 根因
旧版本注入 "留 1 轮给总结" 策略不足。改为 50 轮后需要更强的近限提示。

### 修复
在迭代 >= `max_iterations - 3` 时添加 "请立即总结" 的 nudge。

### 涉及文件
- `server/agent/__init__.py`
- `server/llm_proxy.py`

---

## B13. `window.location.reload` 只读属性导致页面白屏 (2026-07-15)

### 现象
页面白屏，React 无法挂载，`#root` 元素为空。控制台报 TypeError。

### 根因
ES modules 运行在严格模式下，`window.location.reload` 是只读属性（`configurable: false, writable: false`），直接赋值抛出：
```
TypeError: Cannot assign to read only property 'reload' of object '[object Location]'
```

### 修复
改用 `window.addEventListener('beforeunload', ...)` —— SSE 活跃时拦截页面卸载事件，静默取消不弹框。

### 涉及文件
- `src/api/analysis.ts`

---

## B14. Vite oxc 解析器括号对齐错误 (2026-07-15)

### 现象
Vite 返回 500，页面白屏。`tsc --noEmit` 通过但 Vite 的 oxc 解析器报 PARSE_ERROR。

### 根因
Vite 8 使用 oxc（Rust TS 解析器），对嵌套 `try {} finally {}` 的括号缩进比 `tsc` 更严格。

### 修复
确保 `try` / `catch` / `finally` 的闭合括号与打开语句**缩进层级一致**。

### 涉及文件
- `src/api/analysis.ts`

---

## B15. 重启后首次加载首页空白 (2026-07-20)

### 现象
后端重启后，第一次打开网页（`:6000` 直连静态前端）首页空白几秒，数据组件不渲染。

### 根因
`main.py` 中用 `Thread(target=scan_datasets, daemon=True)` 异步启动初始扫描，HTTP server 不等待扫描完成就启动。用户直接访问 `:6000` 时，浏览器立即加载静态前端并发送 API 请求，但 scanner 尚未执行完，`datasets` 列表仍为空，前端收到空数据后渲染为空。

**次要问题**：`scanner_loop()` 在初始扫描后立即又执行一次完全相同的扫描，造成 30 秒内的冗余扫描和 `datasets` 列表的短暂清空窗口。

### 修复
1. `server/main.py`: 初始扫描改为**同步执行**（去掉 `Thread`），阻塞 HTTP server 启动直到 `datasets` 就绪
2. `server/main.py`: 添加扫描耗时日志（`Initial scan complete (X.Xs, N datasets)`）
3. `server/scanner.py`: `scanner_loop()` 开头加 `time.sleep(SCAN_INTERVAL)`，避免与同步扫描重叠产生冗余遍历

### 涉及文件
- `server/main.py` — 初始扫描同步化 + 耗时日志
- `server/scanner.py` — `scanner_loop()` 首轮延迟

### 验证方法
1. 重启后端，立即 curl `/api/tissues` 应立刻返回非空数据
2. 日志显示初始扫描耗时
3. 浏览器访问 `:6000` 首页直接展示数据，无空白期

---

## 附录：修复清单总览

| ID | 缺陷 | 类型 | 严重度 | 日期 | 涉及文件数 |
|----|------|------|--------|------|-----------|
| B1 | Vite HMR 页面刷新 | 性能/架构 | CRITICAL | 07-14~15 | 2 |
| B2 | FreeAnalysis 刷新消息丢失 | 功能 | HIGH | 07-14 | 1 |
| B3 | FreeAnalysis Tab 切换消息丢失 | 功能 | HIGH | 07-13 | 1 |
| B4 | activeTab 刷新重置 | 功能 | MEDIUM | 07-13 | 1 |
| B5 | Scanner 缓存 key 不匹配 | 性能 | HIGH | 07-14 | 1 |
| B6 | Scanner 数据重复 | 功能 | HIGH | 07-13 | 1 |
| B7 | MCP 工具未注册 | 功能 | CRITICAL | 07-13 | 1 |
| B8 | Literature 迭代次数过少 | 功能 | HIGH | 07-13 | 1 |
| B9 | Stop 按钮无效 | 功能 | MEDIUM | 07-13 | 2 |
| B10 | ALL_TOOLS 线程不安全 | 架构 | MEDIUM | 07-13 | 1 |
| B11 | 后端端口混乱 | 运维 | HIGH | 07-14 | 2 |
| B12 | Literature nudge 不足 | 功能 | MEDIUM | 07-13 | 2 |
| B13 | `window.location.reload` 只读属性 | 运行时 | CRITICAL | 07-15 | 1 |
| B14 | oxc 解析器括号对齐 | 构建 | CRITICAL | 07-15 | 1 |
| B15 | 重启后首次加载首页空白 | 架构/性能 | HIGH | 07-20 | 2 |
| B16 | Tissue Workspace 返回聊天丢失 | 功能 | HIGH | 07-24 | 1 |
| B17 | @tailwindcss/vite 扫描 dist/ 无限循环 | 性能/构建 | CRITICAL | 07-28 | 1 |
| B18 | TypeScript 严格模式 60+ 构建错误 | 构建 | HIGH | 07-28 | 14 |

---

## B16. Tissue Workspace 返回后聊天记录丢失 (2026-07-24)

### 现象
在 Tissue Workspace 发起 LLM 对话后，点击 PMID 进入分析页面，再通过浏览器返回按钮回到 TissuePage，聊天内容全部清空。

### 根因
`LiteratureTab.tsx` 用 `useState` 初始化器从 sessionStorage 恢复消息，但 storage key 依赖于 `context` prop：

```tsx
// TissuePage.tsx — context 依赖异步加载的 rows
<LiteratureTab context={`${tissueName} — ${[...new Set(rows.map(r => r.disease))].join(', ')}`} />
```

初始 `rows=[]` → `context = "Lung — "`，数据加载后才变成 `"Lung — COPD, IPF"`。

`useState` 初始化器**仅在挂载时执行一次**，而此时 context 仅为 `"Lung — "`（rows 为空），sessionStorage key 为 `gensci_lit_msgs_Lung — `（错误 key），永远匹配不到之前以 `gensci_lit_msgs_Lung — COPD, IPF` 保存的数据。

### 修复
添加 `useEffect` 监听 `context` 变化，重新从 sessionStorage 加载消息：

```typescript
useEffect(() => {
  const saved = loadMessages(context)
  if (saved.length > 0) setMessages(saved)
}, [context])
```

同时将 `useState` 初始值从 `() => loadMessages(context)` 改为直接 `[]`，避免首次挂载时加载不完整的 context key。

### 涉及文件
- `src/components/analysis/LiteratureTab.tsx`

### 验证方法
1. 在 Tissue Workspace 中发起对话，确认消息正常保存
2. 点击任意 PMID 跳转到分析页面
3. 浏览器返回 Tissue Workspace
4. 验证之前的聊天记录完整恢复，无内容丢失

---

## B17. @tailwindcss/vite Oxide 扫描器无限循环 → 白屏 (2026-07-28)

### 现象
Vite 启动后 5~30 秒内 CPU 飙升至 3810%，页面返回 `ERR_EMPTY_RESPONSE`。修改任意文件（包括不影响服务的 `docs/*.md`）都会触发重新扫描，再次白屏。

### 根因
`@tailwindcss/vite` 插件的 Oxide 扫描器（独立于 Vite chokidar）默认 `**/*` 递归扫描整个项目目录查找 Tailwind 工具类。`dist/` 中的 1.7MB 压缩 JS bundle 被扫描时触发反馈循环：

```
请求 → generate() → Oxide 扫描所有文件 → 扫到 dist/ 1.7MB JS
→ addWatchFile → CSS 失效 → generate() 再次调用 → 循环
→ 并发扫描线程堆积，CPU 爆炸
```

**关键误区：** `vite.config.ts` 的 `watch.ignored: ['**/dist/**']` 只控制 Vite 自身的 chokidar，管不了 Oxide 扫描器。改 `docs/*.md` 也触发白屏是因为 Oxide 监听所有文件变化。

### 修复（三重保障）

**1. `src/index.css` 用 `@source` 限制扫描范围（核心修复）：**
```css
@import "tailwindcss" source(none);   /* 关闭全局扫描 */
@source "../src";                     /* 仅扫描 src/ 目录 */
```
这从根源上阻止 Oxide 进入 `dist/`、`docs/`、`Data/`、`node_modules/`。

**2. 删除 `dist/`（开发模式不需要）：**
```bash
rm -rf dist
```

**3. `vite.config.ts` watch.ignored 增加 `**/dist/**`（防止 chidokar 触发）：**
```typescript
watch: { ignored: ['**/dist/**', ...] }
```

### 涉及文件
- `src/index.css` — `source(none)` + `@source "../src"`（核心）
- `vite.config.ts` — watch.ignored 新增 `'**/dist/**'`（辅助）

---

## B18. TypeScript 严格模式导致 60+ 构建错误 (2026-07-28)

### 现象
`tsc -b` 报 60+ 错误，涉及 TissuePage、SearchPage 等 12 个文件。`tsc --noEmit` 无错误（宽松模式）。

### 根因
1. **`DatasetInfo` 的 `[key: string]: unknown`** 索引签名覆盖了所有字段类型为 `unknown`
2. **`tsconfig.app.json`** 启用了 `noUncheckedIndexedAccess: true`
3. **`SkillCards.test.tsx`** 引用已删除的组件

### 修复
核心改动：删除 `DatasetInfo` 的索引签名 → 修复 `useTableFilter` 类型链条 → 关闭不必要的严格选项 → 清理死代码 → 零星类型修复（共 14 个文件）

### 涉及文件
`src/api/types.ts`、`src/hooks/useTableFilter.ts`、`tsconfig.app.json`、`src/pages/TissuePage.tsx`、`SearchPage.tsx`、`src/components/analysis/` 下 5 个文件、`src/data/mockData.ts`

### 验证
```bash
tsc -b        # 0 错误
tsc --noEmit  # 0 错误
```

---

---

## B19. 删除 .scanner_cache.json 后服务长时间不可用 (2026-08-05)

### 现象
删除 `.scanner_cache.json` 后重启后端，HTTP 服务在扫描完成前完全不接受连接。

### 根因
Scanner 逐一读取 h5ad 文件获取 obs stats，大文件（5.5GB）单个耗时 10-30s，86 个文件累计数分钟。扫描在 HTTP 服务启动前同步执行。

### 修复
不要随意删除 `.scanner_cache.json`。它记录每个文件的 mtime + obs stats，命中缓存无需重读 h5ad。

### 涉及文件
`server/scanner.py`, `server/main.py`


## B20. DATA_DIRS 变更导致数据全消失 (2026-08-05)

### 现象
Data/ 从 symlink 改为本地目录后只剩 2 个新数据集，原有 86 个全消失。

### 根因
symlink 指向 06.GenSci/Data（86 个文件），改本地目录后数据源断开。

### 修复
config.py 中新增 LEGACY_DATA 指向 06.GenSci/Data，DATA_DIRS 支持多个数据源。Scanner 对 legacy 路径默认 omics_type='scRNA'。

### 涉及文件
`server/config.py`, `server/scanner.py`

---

---

## B21. 同步初始扫描阻塞 HTTP 启动 → 前端超时 (2026-08-05)

### 现象
后端重启后前端 API 请求全部返回 "signal is aborted without reason"，持续数分钟。

### 根因
`main()` 中 `scan_datasets()` 同步执行，86 个 h5ad 逐一读取 obs stats，耗时 4-5 分钟。HTTP 端口未监听，请求全部超时。

### 修复
将初始扫描移到后台线程，HTTP 服务立即可用。扫描期间 datasets 逐步填充。

### 涉及文件
`server/main.py`

---

*后续新缺陷按 B22、B23... 追加。*

---

## B22. scanpy 1.11 DotPlot API 变化 (2026-08-07)

### 现象
`sc.pl.dotplot(return_fig=True, show=False)` 返回的对象 `.fig` 和 `.ax_dict` 均为 None，`plt.close(result)` 报 `close() argument must be a Figure... not DotPlot`。

### 根因
scanpy ≥1.10 的 `return_fig=True` 返回 `DotPlot` 对象（非 matplotlib Figure）。必须先调用 `.make_figure()` 才能访问 `.fig` 和 `.get_axes()`。

### 修复
```python
result = sc.pl.dotplot(adata, plot_dict, groupby='CellType',
    standard_scale='var', dot_max=1, return_fig=True, show=False)

if hasattr(result, 'make_figure'):
    result.make_figure()
    fig = result.fig
```
`get_axes()` 返回的 dict 包含 `['mainplot_ax', 'gene_group_ax', 'size_legend_ax', 'color_legend_ax']`。

### 涉及文件
`server/analysis/plots.py`

---

## B23. HDF5 backed-mode AnnData 并发冲突 (2026-08-11)

### 现象
`ThreadingHTTPServer` 并发请求（如快速切换 Group filter）时报错：
```
RuntimeError: Can't synchronously determine if attribute exists by name
(invalid identifier type to function)
```

### 根因
`get_adata()` (`server/core/adata_cache.py`) 返回共享的 `anndata.read_h5ad(path, backed='r')` 对象，HDF5 文件句柄不是线程安全的。多个线程同时访问同一 .h5ad → h5py 的 `h5a.exists()` 同步失败。

### 修复
在 `_generate_marker_dotplot()` 中不用共享 backed AnnData，改用内存版缓存（注意：此修复后被 B24 推翻，全内存 load 引入了双句柄冲突）
```python
from caches import LRUCache
_adata_mem_cache = LRUCache(max_size=3)

adata = _adata_mem_cache.get(str(real_path))
if adata is None:
    adata = anndata.read_h5ad(str(real_path))  # 全内存，无 backed
    _adata_mem_cache.set(str(real_path), adata)

# subset 直接用 .copy()
if group_filter:
    mask = adata.obs['Group'].astype(str) == group_filter
    adata = adata[mask].copy()
```
- 首次加载慢（28s for 188K cells），后续命中缓存快（~5s）
- `LRUCache` 线程安全（内部 `threading.Lock`）

### 涉及文件
`server/analysis/plots.py`

---

## B24. Dotplot 双 HDF5 句柄冲突导致持续加载/刷新 (2026-08-11)

### 现象
- Dotplot 一直处于刷新状态（loading spinner 不消失）
- 当 Dotplot 出现时，其他图（UMAP、Boxplot）也开始刷新
- 出现 "signal is aborted without reason" 报错
- 后端收到大量重复请求（12+ 次 markder-dotplot 请求）

### 根因
**B23 的修复引入了更严重的问题。** B23 让 dotplot 使用 `anndata.read_h5ad()`（全内存，独立 h5py File 句柄），而其他端点（UMAP、expression、stats）使用 `get_adata()`（backed='r'，共享 h5py File 句柄）。两个 h5py `File` 句柄同时打开同一文件 → 冲突/数据损坏。

**前端加剧因素：** React StrictMode 双重 effect、缺少 AbortController cleanup，导致 4 个并发请求同时打到后端。

### 修复

**后端（主修复）：** 统一所有端点使用 backed AnnData + 文件级锁

1. `server/core/adata_cache.py` — 新增 `locked_backed_adata()` context manager：
   - 每文件一个 `threading.Lock`，串行化对共享 backed AnnData 的访问
   - 调用方在锁内提取数据、`.to_memory()` 物化，释放锁后做重计算

2. `server/analysis/plots.py` — `_generate_marker_dotplot()` 改用统一 backed 访问：
   - 移除 `_adata_mem_cache` LRU 缓存（全内存 load 的独立句柄）
   - 移除 `import anndata`
   - 用 `with locked_backed_adata(path) as adata:` 代替 `anndata.read_h5ad()`
   - 仅物化需要的基因列：`adata[:, needed_genes].to_memory()`（大幅减少锁持有时间）
   - Group filter：`adata[mask, needed_genes].to_memory()` 而非 `.copy()`

**前端（辅助修复）：** `UmapTabContent.tsx`
- useEffect 内联 fetch 逻辑，添加 `cancelled` 标志清理
- StrictMode 重渲染时旧请求的 setState 被忽略，减少服务端压力

### 涉及文件
`server/core/adata_cache.py`, `server/analysis/plots.py`, `src/components/analysis/UmapTabContent.tsx`

### 关键教训
**全内存 read_h5ad() 作为 HDF5 并发冲突的"修复"是反模式。** 它新建一个独立的 h5py File 句柄，与 backed 模式的共享句柄冲突，因为 `HDF5_USE_FILE_LOCKING=FALSE` 禁用了 HDF5 内部的文件级锁。正确方案是统一使用 backed 模式 + Python 层 per-file 锁。

---

## B25. BulkAnalysisTab 切 Free Analysis 后选择项重置 (2026-08-19)

### 现象
Protein / Bulk RNA 分析页选中 disease + gene、出结果后，切到 Free Analysis 再切回 Expression & DE，disease/palette/case/control 全部回到默认值（disease='All'）。

### 根因
`AnalysisPage.tsx` 的 Tab 1 是条件渲染（`activeTab === 1 &&`），切 tab 时 `BulkAnalysisTab` 被卸载，本地 state 全部丢失。仅 `gene` 幸存（已持久化到 sessionStorage `gensci_bulk_gene`）。系统本有两层缓存（前端 `cachedFetch` + 后端 LRU），但缓存 key 含 disease，disease 重置使 key 漂移、命中不了缓存，导致真重算（还算错疾病）。

### 修复
`BulkAnalysisTab.tsx` 将 `disease`/`caseGroup`/`controlGroup`/`palette` 持久化到 sessionStorage（`gensci_bulk_disease`/`gensci_bulk_case`/`gensci_bulk_control`/`gensci_bulk_palette`），`useState` 初始化器读 + `useEffect` 写入，与 scRNA `gensci_boxplot_gene`/`gensci_agg_gene` 同一模式。key 稳定后命中现有两层缓存，无需重算。

### 涉及文件
- `src/components/analysis/BulkAnalysisTab.tsx`
- `src/components/analysis/BulkAnalysisTab.test.tsx`（新增回归测试）
- `src/components/analysis/BoxPlotContainer.test.tsx`（修复测试隔离：afterEach 清 sessionStorage）

---

*后续新缺陷按 B26、B27... 追加。*
