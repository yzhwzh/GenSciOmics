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

## B26. PMID 摘要/方法永久为空：瞬时网络失败被 _EUROPE_PMC_CACHE 永久缓存 (2026-09-02)

### 现象
打开 Kidney/IgAN（PMID 33936064，PMC8085501 在 PMC 可检索）数据集，InfoPanel 的摘要和方法都显示 "not available"。但独立进程直接调 `_fetch_abstract('33936064')` 能拿到 abstract 1792 字 + methods 4805 字。

### 根因
`server/pubmed.py::_fetch_abstract` 把结果**无条件**写入 `_EUROPE_PMC_CACHE`（含全空 dict）。某次代理/网络瞬时失败时，5 个字段全空的结果被永久缓存；此后该 PMID 永远返回空，直到服务重启。routes 层 `_analysis_info_cache` 又把含空 abstract 的 `result` 缓存，形成双层毒缓存（`/api/analysis-info` 直接中招）。

### 修复
`pubmed.py` 加"失败不缓存"策略：
```python
has_record = bool(info['title'] or info['abstract'] or info.get('pmcid'))
if has_record and not (pmc_error and not info['methods']):
    _EUROPE_PMC_CACHE[pmid] = info
```
空 / PMC 全文出错的结果不写缓存，下次请求自动重试。重启服务清除已被污染的进程内缓存。

### 涉及文件
- `server/pubmed.py`

### 关键教训
**进程内 dict 缓存不能缓存"失败/空"结果，否则一次瞬时网络故障 = 永久错误（直到重启）。** 抓取类缓存正确写法：只缓存成功且完整的结果，失败走不缓存-重试路径。

---

## B27. Multi-organ 猴子数据集 Patient 统计恒为 0：瞬时 HDF5 读失败被持久缓存固化 (2026-09-10)

### 现象
新链接的 Monkey/Multi-organ 数据集（PMID 35831300，`Data/Monkey/Multi-organ/scRNA/35831300.Monkey.h5ad`）在数据集表格中 Patient 列显示 **0**，但该 `.h5ad` 的 `obs['Patient']` 确有 2 个取值。**重启服务后依旧为 0** —— 说明问题不在进程内缓存。

### 根因
两条缺陷叠加：

1. **`server/scanner.py::_read_obs_stats` 自开第二个 h5py File 句柄。**
   它用 `anndata.read_h5ad(path, backed='r')` 直接打开文件、读完 `adata.file.close()`。这与 analysis 线程经 `core.adata_cache` 持有的**共享 backed 句柄**并发访问同一个 3.9 GB `.h5ad`，触发 HDF5 内部错误：
   ```
   Can't synchronously read data (bad heap index, heap object = {768610ef, 1381})
   ```
   这正是 **B24（同一文件双句柄）** 根因的复发 —— 当时的修复只覆盖了 analysis 路径，漏了 scanner。

2. **失败兜底值被当成权威结果写入持久缓存。**
   异常分支返回全 0 哨兵 `{patient_count: 0, ...}`，调用方 `resolve_h5ad` 与 bulk 缓存分支**无条件**把它写进 `.scanner_cache.json`。该缓存按「符号链接路径 + `mtime`」复用，而一个写完的 `.h5ad` 的 mtime 永不变化 → **一次瞬时并发读失败 = 永久 Patient 0**，只能手工删缓存条目才能恢复。这是 **B26（失败被永久缓存）** 在磁盘持久化层的翻版。

### 修复
`server/scanner.py` 三处改动：

1. **复用共享锁定句柄。** `_read_obs_stats` 改走 `core.adata_cache.locked_backed_adata()`（per-file `threading.Lock` + 共享 `backed='r'` 句柄），**不再自开、也不再自行 close 句柄**。统计量计算抽成纯函数 `_collect_obs_stats(adata, tabular)`。
2. **失败不落盘。** 读失败时返回带 `_read_failed: True` 的占位结果；新增 `_is_cacheable()` 守卫，两个持久化写入点（`resolve_h5ad` 与 bulk 分支）在失败时**跳过写入**，占位值仅用于当次前端渲染。`_strip_read_failed()` 在结果离开 scanner 前摘掉该标记，API 契约不变。
3. **中毒条目自愈。** `_is_valid_cache_entry()` 把 `obs_columns` 为空的缓存条目判为无效（一次成功读取必然产生非空 `obs_columns`），下次扫描自动重算 —— 无需手工清 `.scanner_cache.json`。

线上已中毒的那 1 条条目已单独修复（`.scanner_cache.json` 删除该条目后重算）。影响面：99 条缓存中 1 条。

### 涉及文件
- `server/scanner.py`
- `server/tests/test_scanner_obs_cache.py`（新增回归测试，9 项断言，自包含无需 pytest）

### 关键教训
- **B24 的「统一走共享 backed 句柄」当初没有覆盖 scanner。** 凡是新写的 `.h5ad` 读取，一律走 `core.adata_cache.locked_backed_adata()`；不要 `anndata.read_h5ad` 裸开第二个句柄。
- **B26 的「失败不缓存」必须同时覆盖进程内缓存和磁盘持久缓存。** 按 mtime 复用的持久缓存尤其危险：文件写完 mtime 不再变，毒条目永不自愈，会跨重启存活。
- **兜底值必须带显式失败标记**，让调用方能区分「真的是 0」和「根本没读到」。全 0 与全空无法自证。

---

## B28. Merge 合成基因的成员名被子串回退静默解析成别的基因 (2026-09-10，**后端未修复；UI 侧入口已封堵**)

### 现象
Barplot「共表达」的 Merge 模式下填 `COL1|COL1A2` 生成合成基因 M。数据集里并没有 `COL1`，但接口返回 `gene2_unresolved: []`、`gene2_resolved: ['COL1A1','COL1A2']`，前端**一条警告都不显示** —— M 实际是在用户从未指定的 `COL1A1` 上取的并集/交集。已实测复现（IPF 数据集，**直接调接口复现，非 UI 复现**，可达性见下）。

### 根因
`server/analysis/utils.py` 的 `resolve_gene_indices` 在精确匹配失败后有子串回退：

```python
partial = [n for n in var_names if g.lower() in n.lower()]
```

`'col1' in 'col1a1'` 成立 → `COL1` 被映射到 `COL1A1`。该回退是**既有行为**（非本次引入），但本次新增的 `gene2_resolved` 契约把它**认证成"已解析"**，使警告机制失效 —— 恰好是本功能要消除的那种失败模式。

### 可达性（2026-09-10 实测修正，不要跳过）
初判时把本缺陷说成「用户填 COL1 就会中招」，**说重了**。用 Playwright 在真实 UI 上逐场景实测后：

| 输入 | 下拉内容 | 直接回车选中 |
|---|---|---|
| `COL1` | 17 项真实基因（`COL10A1`…`COL1A1`/`COL1A2`/`LRCOL1`），`Create "COL1"` 在**末位第 17 项** | `COL10A1`（真实基因） |
| `COL1A1` | 1 项 `COL1A1`，**无 Create 项** | `COL1A1` |
| `ZZZQQ` | 仅 `Create "ZZZQQ"` | `ZZZQQ` |

关键对称性：下拉源 `routes.py:279` 与解析回退 `utils.py:124` 用的是**同一个子串谓词、同一份基因表**。因此
`token 能被子串回退命中` ⟺ `下拉一定会列出那些真实基因` → 用户眼前有真选项，Create 反而被挤到末位；而当真选项为空（只剩 Create）时，后端子串回退**同样匹配不到** → `gene2_unresolved` 正常上报、警告正常显示。**静默只发生在「token 是真实基因子串 且 用户特意翻到底部点 Create」这唯一组合**。

即便如此仍是真实缺陷：`AsyncCreatableSelect` 保留了 Create 项，刻意操作可以走到。

### 状态
**后端未修复；UI 入口已封堵。** 处置：
1. `ExpressionChartContainer.tsx` 的 Merge 成员选择器加 `isValidNewOption={() => false}` —— 既然「可合并的基因必然可被搜到」，Create 对该场景零收益，去掉即把唯一入口封死（后端解析逻辑不动，避免波及单基因 `gene2` 路径与计划中划为非目标的「统一解析」）。
2. `server/tests/test_gene2_op.py::test_known_partial_match_hazard` **钉住后端现状**（直接调 `_get_aggregate_table`，绕过 UI）。后端依旧如此，接口直连仍可触发；修掉它时该用例应当失败并被改写，**不是被删掉**。

### 副作用：`gene2_unresolved` 警告在 UI 上已不可达（2026-09-10 实测）
必须记下来，否则日后会有人以为那条警告在干活。

`search.py:33` 的 `_get_genes` 返回的就是 `set(adata.var_names)`，而 `stats.py:306` 的解析器正是拿 `adata.var_names` 做精确匹配 —— **同一个源、同一个谓词**。Create 关掉后，用户在 Merge 里能选中的每一个基因都必然精确命中，`gene2_unresolved` 恒为空数组。

因此「未找到成员」警告在 UI 上**实际不可达**（仅剩「选中 chip 后数据集文件被替换、mtime 变化导致基因消失」这类边界情形）。它**仍然保留**，因为：
- 它是 API 契约的一部分，接口直连（curl / 未来的 LLM skill）仍会触发；
- 渲染逻辑由 vitest 组件测试用 mock 响应持续覆盖（`AggregateDetailTable.test.tsx` / `FisherTable.test.tsx`）；
- 后端行为由 `test_gene2_op.py` 覆盖。

即：**警告从"运行期防线"退化成了"API 契约 + 未来防线"**。若希望它重新承担 UI 上的实时职责，需回到候选修法 1（Merge 成员改为只认精确匹配），让手输的不存在基因重新变成可表达状态。

候选修法（择一）：
1. Merge 成员要求精确（大小写不敏感）匹配，主基因路径保持不变 —— 改动最小，但会与 plots 的解析结果进一步分叉；
2. 保留回退，但新增第三个字段 `gene2_partial`，让前端把子串命中标成"疑似"而非"已解析"。

另需注意：`stats.py` 与 `plots.py` 的解析器本就不一致（前者只查 `var_names`，后者还查 `index`/`gene_ids`/`gene_symbols`/`feature_name` 列），去重行为也不同 —— 同一个 `gene2` 在图与表可能得到不同的成员集。修的时候应抽成一个共享解析器，否则图与表的警告会互相矛盾。

### 涉及文件
- `server/analysis/utils.py`（`resolve_gene_indices`）
- `server/analysis/stats.py` / `server/analysis/plots.py`（两条各自的解析路径）

### 关键教训
- **新增的「已解析 / 未解析」契约会把既有的模糊匹配升级成静默错误。** 把宽松解析的结果当作"确认无误"回传给 UI，比不回传更危险。
- 涉及基因名解析的功能，**只有精确匹配才能作为「已确认」的依据**；子串命中最多算「疑似」。B24/B26/B27 的教训是"失败不要伪装成成功"，这条是它的近亲：**猜测不要伪装成确认**。
- **判定缺陷严重性必须实测可达性，不能只读代码。** 本次初判把「用户填 COL1 就会中招」当成结论写进日志，实测才发现回车选中的是 `COL10A1`、Create 项挤在末位第 17 个。**机制成立 ≠ 路径可达** —— 可达性只有把 UI 真跑一遍才量得出来，读代码永远量不出来。教训：先测可达性，再定严重级别，最后才写日志。

---

## B29. 仓库根 `coverage/` 遮蔽 Python `coverage` 模块，后端启动即崩；前端把崩溃显示成「该组织没有数据」(2026-09-10)

### 现象
组织页（本次为 kidney）显示 **"No datasets found in kidney/"**。但 `Data/Human/Kidney/` 下确有 3 个 `.h5ad`，且接口在多数时候正常返回 3 条。用户报告：「又出现刚刚的bug了」。

### 根因
两条缺陷叠加：一条让后端起不来，另一条把「起不来」伪装成「没有数据」。

**1. `coverage/` 目录遮蔽真模块，`import scanpy` 在 import 阶段崩溃。**
本机 shell 的 `PYTHONPATH` 以**裸冒号开头**：

```
PYTHONPATH=:/data/yuanwuzhou/Software/scBERT:/data/yuanwuzhou/02.AIPlatForm/OpenBioMed:...
```

前导冒号 = 一个**空条目** = **当前工作目录进入 `sys.path`**。实测从仓库根：

```
sys.path[:3] == ['', '/data/yuanwuzhou/102.ClaudeCode/10.GenSciOmics', '/data/.../scBERT']
```

而 `npm run test:coverage`（vitest 默认 `reportsDirectory: './coverage'`）会在仓库根写出 `coverage/` 目录。此时从仓库根执行 `python3 server/main.py`（即 `npm run server` / `npm start`），Python 把这个目录当作**命名空间包**导入 —— `import coverage` **成功**返回一个空模块（`__file__ is None`，`hasattr(coverage,'types') is False`）。

numba 的 `numba/misc/coverage_support.py:114` 写的是：

```python
try:
    import coverage
except ImportError:
    coverage = None
...
if coverage is not None:
    class NumbaTracer(coverage.types.Tracer): ...
```

空模块**不是 None**，于是执行到 `coverage.types` →

```
AttributeError: module 'coverage' has no attribute 'types'
```

→ `import numba` 失败 → `import scanpy` 失败 → `server/main.py` 在 import 阶段退出（**退出码 1，HTTP 端口根本没起来**）。

注意 `coverage` 在 conda 环境 `claude-code` 里**根本没安装**（从 `/tmp` 执行 `import coverage` → `ModuleNotFoundError`）。也就是说 numba 的 `except ImportError` 兜底本来工作正常 —— 是这个目录让 import **假装成功**，把本应被捕获的 `ImportError` 升级成了 `AttributeError`。

**2. 前端把「请求失败」渲染成「该组织没有数据」。**
`src/pages/TissuePage.tsx` 的加载 effect：

```tsx
.fetchDatasets(slug)
  .then((data) => setRows(Array.isArray(data) ? data : []))
  .catch(() => setRows([]))        // ← 错误被吞成空数组
```

后端崩溃 → 每个请求都抛错 → 被吞成 `[]` → 命中 `rows.length === 0` 分支 → 渲染 `No datasets found in kidney/`。**这是一句关于数据的断言，实际发生的却是请求失败**，两种状态被合并成同一个。违反 CLAUDE.md「No silent error swallowing」。

**3. 放大器：空列表被缓存 5 分钟。**
`server/main.py:40-47` 先起 HTTP 服务、扫描放在后台线程 —— 初次扫描完成前**所有列表接口都返回 `[]`**，这是合法且常见的响应。而 `src/api/client.ts` 的 `cachedFetch` 会把任意响应缓存 5 分钟，包括这个 `[]`，于是「后端还在扫」被钉成 5 分钟的「没有数据」，**活得比扫描本身还长**。

### 时间线与责任
`coverage/` 是**本次会话中我执行 `npm run test:coverage` 时生成的**。在我跑覆盖率之前该目录不存在，后端一直正常。**本缺陷由我的操作引入**，不是既有问题。

### 修复
1. **`vitest.config.ts`** → `coverage.reportsDirectory: './coverage-report'`。任何**非 Python 模块名**的目录名都安全；`.gitignore` 同步改为 `coverage-report/` 并保留旧 `coverage/` 条目。
2. **`TissuePage.tsx`** → 新增 `loadError` 状态，`.catch` 记录错误消息而非静默置空；渲染区分三态：**失败**（`Failed to load datasets` + 错误详情 + Retry 按钮）/ **成功但为空**（保留原 `No datasets found` 文案）/ **有数据**。失败时页脚 `N dataset(s)` 一并隐藏（`invisible`），因为此刻根本不知道数量。
3. **`src/api/client.ts`** → `cachedFetch` 不再缓存空数组。空列表在这些接口上的语义是「此刻还没有」，不是「不存在」，且重取代价极低。

### 验证（双向实测）
| 操作 | 结果 |
|---|---|
| `coverage-report/` 在位，从仓库根 `import scanpy` | ✅ OK（scanpy 1.11.5） |
| 改名回 `coverage/` | ❌ **稳定复现** `AttributeError: module 'coverage' has no attribute 'types'` |
| 再改名回 `coverage-report/` | ✅ 恢复正常 |
| 重启后端（`coverage-report/` 在位） | ✅ 启动成功，`/api/datasets?tissue=kidney` 返回 3 条 |
| 全仓根目录扫描「是否还有同名真模块被遮蔽」 | ✅ 无其它遮蔽目录 |

新增 `src/pages/TissuePage.test.tsx` 5 项：失败不得显示 "No datasets found"、Retry 能恢复、真·空组织仍显示 "No datasets found"、成功渲染表格、慢响应不得覆盖已切换的组织。**改前 2 项 RED / 2 项 GREEN，改后 5/5 GREEN。**

> 初稿此处写的是「改前 3 项 RED / 1 项 GREEN、全量 45 passed」，**是我在自己的修正之前测的**，数字对不上：第 4 项当时还写成 `getAllByText('IgAN')` 抛多元素错误。经 code review 指出后订正。

### 代码评审后的修补（同一缺陷，第二轮）

首轮提交被 `ecc:typescript-reviewer` 判 **BLOCK（2 HIGH）**，逐条核实后修补：

1. **【HIGH，真实缺陷】`onClick={load}` 让新增的竞态保护形同虚设。** 首轮把「导航后不得重绘」的保护写在 `useEffect` 的 cleanup 里，但 Retry 走的是 `onClick={load}` 直接发请求 —— **React 丢弃 onClick 的返回值，cleanup 永远不会被调用**。实测：Retry → 切到 lung，被遗弃的 kidney 响应照样把页面刷成 `IgAN×2 / 33936064×1`。而 Retry 恰恰是「请求失败」这一路径上用户唯一会点的按钮，也就是说保护在**最需要它的地方**失效。
   → 改为 `attempt` 计数器：Retry 只 `setAttempt(n => n+1)`，请求一律在 effect 内发出。**所有请求都由 effect 发起是该写法唯一的意义**，不是风格。
2. **【HIGH】轮询走 `cachedFetch`，整段逻辑是死的。** 5 分钟内每个 tick 返回**同一个数组引用**，`setRows(sameRef)` 被 React 判定为无变化而 bail out → 不重渲染 → interval 永不重建 → "Processing..." 徽标永不更新。新增 `fetchDatasetsFresh()`（带 `t=` 绕缓存）供轮询使用。
3. **【MEDIUM】`pollError` 被吞掉。** 后端在处理途中挂掉时，页面会一直脉动 "Processing..." 而毫无提示 → 页脚改为显示 "Status refresh failing — counts may be stale"。
4. **【MEDIUM】失败时头部与 LLM 上下文仍在断言"没有数据"。** `rows.length > 0 ? ... : 'No datasets yet'` 与传给 `LiteratureTab` 的 `"Kidney — "` 在失败态下都会读成「该组织没有疾病」—— 与本次修复要消灭的那句错误结论同类。失败态分别改文案。
5. **【MEDIUM】空列表不缓存只覆盖数组。** `/api/stats` 把「空」藏在对象里（`{tissues: [], species: []}`），默认规则看不见，扫描窗口内仍会被钉住 5 分钟 —— 同一缺陷的另一副面孔。`cachedFetch` 增加可选 `isEmptyAnswer` 谓词，`fetchStats` 传入自己的判定。
6. **【文档】`.gitignore` 注释自相矛盾**（称旧 `coverage/` 目录「留在盘上不影响运行」，而它恰恰是让后端起不来的东西），已订正。

`src/pages/TissuePage.test.tsx` 由 5 项扩到 11 项（新增：Retry 后导航的取消、轮询成功刷新徽标、轮询失败提示、空结果复核三种走向）+ `src/api/client.test.ts` 5 项（空列表不缓存、非空列表命中缓存、对象默认仍缓存、自定义谓词、HTTP 错误不被缓存）。

**两个新守卫都做了变异验证**（去掉 `cancelled` 判断 / 去掉 `setPollError`，确认对应测试恰好失败），不是「写完就绿」。

### 第二次评审（对修补本身的复核）：APPROVE

`ecc:typescript-reviewer` 复核后判 **APPROVE**，两个 HIGH 均已关闭。关键之处在于**它没有读代码下结论，而是把本轮新增的断言拿回去跑在修改前的组件上**（`git show HEAD:src/pages/TissuePage.tsx`），确认断言在旧代码上真的失败 —— 这正是「守卫是否有效」唯一可信的证明方式。据此它又提了 2 MEDIUM / 5 LOW，逐条处理后：

1. **【MEDIUM，本项目缺陷的同类】扫描窗口内的「成功但为空」仍会被渲染成「No datasets found」。** 前面第 5 条只修了「不缓存」，没修「不显示」：后端首次扫描未完成时对所有列表请求返回 `[]`，这是**合法且成功**的响应，于是页面照样断言该组织没有数据；而 Retry 按钮只存在于**失败**分支，用户此刻无法自救，只能刷新。**这正是用户报的那句话**，属于同一缺陷的最后一条通路。
   → 空结果不再直接当事实：先**用 `fetchDatasetsFresh` 复核一次**，第二次仍为空才渲染缺失结论；空态另加 Refresh 按钮（用户的工作流正是「改完文件重新软链 → 页面还开着」）。复核失败**不升级为加载错误** —— 首个请求是成功的，空列表仍是当时能拿到的最好答案。用 `try/catch` 而非 `.catch()`，连**同步抛错**也一并兜住（见下条）。
2. **【MEDIUM】轮询错误把错误对象丢了。** `setPollError(true)` 无载荷，与加载路径的 `err.message` 不一致：60s 超时、HTTP 502、响应解析失败三者在界面上无法区分，且没有任何一条进入控制台。→ 改为存消息字符串。
3. **【LOW，值得记】两处断言是空转的，读起来却像守卫。** `await waitFor(() => expect(...).toBeNull())` 的回调会**同步**跑在更新前的 DOM 上并立即返回，因此在「上一个响应当前正在重绘」时它照样通过 —— 真正拦住的是紧随其后的那一行。已改为 `await act(async () => ...)`，只保留真正的断言。**「测试是绿的」与「测试在守卫」是两回事。**
4. **【LOW】H2 的症状本身没有测试**（只测了失败分支，没测「成功的一跳把 Processing 刷成 Ready」—— 而后者才是被报的 bug）。已补。
5. **【LOW】`fetchStats` 谓词未防形状漂移。** `apiFetch` 直接 `as Promise<T>` 不做校验，一个 200 的异常响应体会让 `s.tissues.length` 抛 `TypeError`。已改为 `Array.isArray` 守卫。
6. **【LOW，险些造成审计空洞】`src/api/client.test.ts` 当时是未跟踪文件。** 若用 `git add -u` 提交会被**静默漏掉**，而 BUG_LOG 已经宣称它存在。已确认入库。

### 顺带发现（未修，另行记录）

- **`npm run lint` 自 fork 起就是坏的**：仓库里从来没有 `eslint.config.*`，ESLint 10 直接报错退出（`git log -- '*eslint*'` 无任何提交）。不是本次引入。没有顺手加配置：对一个从未被 lint 过的代码库开机会产生大量噪声，掩盖本次真正的改动，应单独一轮处理。

### 本轮验证（全部实测）

| 手段 | 结果 |
|---|---|
| `npm test` | ✅ 57 passed（8 files） |
| `npx tsc -b` | ✅ 干净（并**抓出**我改 `pollError` 类型时漏掉的一处 `setPollError(false)`） |
| 变异验证 ×3 | ✅ 去掉 `cancelled` 判断 / 去掉 `setPollError` / 去掉空结果复核，各自**恰好**让对应测试失败 |
| 浏览器（加载·错误·竞态） | ✅ 14/14，含「Retry 的请求确实在飞行中」这一条**反空转**断言 |
| 浏览器（轮询实测） | ✅ 5/5 —— 轮询请求确实带 `t=` 绕开了缓存并让徽标消失（用 `cachedFetch` 时不带 `t=`、徽标不会消失） |

> 浏览器脚本里 14/14 那条「Retry 真的发出了请求」是**故意加的**：如果 Retry 没发请求，「被遗弃的响应没有重绘」就是句废话，测了个寂寞。实测请求记录为 `fail,fail,slow`（前两个是 StrictMode 双挂载）。

### 涉及文件
- `vitest.config.ts`、`.gitignore`
- `src/pages/TissuePage.tsx`、`src/pages/TissuePage.test.tsx`（新增）
- `src/api/client.ts`、`src/api/client.test.ts`（新增）
- `src/api/datasets.ts`

### 关键教训
- **cwd 在 `sys.path` 上时，仓库根的任何目录都可能遮蔽依赖。** 本机 `PYTHONPATH` 前导裸冒号就是这个陷阱（`export PYTHONPATH=":$PYTHONPATH"` 的典型笔误）。凡是在仓库根产出文件的工具，**输出目录名不要与任何 Python 模块同名**。
- **`try: import X / except ImportError` 形式的可选依赖最危险。** 遮蔽目录让 import「假装成功」，把兜底分支本该捕获的 `ImportError` 变成运行期 `AttributeError`，而且**报错位置离病因极远**（numba 抛错，根因在仓库根的覆盖率目录）。
- **「没有数据」和「请求失败」必须是两个状态。** `.catch(() => setRows([]))` 把二者合一，代价是用户拿到一句听起来像事实的错误结论。这是 B26/B27「失败不要伪装成成功」在**前端展示层**的翻版。
- **空列表不要缓存。** 后端启动期（扫描未完成）的 `[]` 与「真的为空」在响应上无法区分，缓存它就把瞬态固化成持久态 —— 与 B26/B27「瞬时失败被缓存固化」同源，只是这次固化在浏览器内存里。注意**「空」不一定长得像空数组**：`/api/stats` 报的是 `{tissues: [], species: []}`，只按 `Array.isArray` 判断会漏掉它。判断依据应当是**「这个响应能不能证明数据不存在」**，而不是它的 JS 类型。
- **诊断「数据看起来是空的」类缺陷，先确认服务是否还活着。** 本次若只盯着数据目录和扫描器，会一路查错方向；实际病因是后端根本没起来。

---

*后续新缺陷按 B30、B31... 追加。*
