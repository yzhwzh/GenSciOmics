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

## B28. 基因名被子串回退静默解析成别的基因 (2026-09-10 首报，2026-09-11 修正可达性，**后端仍未修复；UI 侧只封了「手输」这一条入口** —— 原标题的「全部入口已封堵」与实测不符，2026-09-11 二次修正，见 B34)

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

即：**警告从"运行期防线"退化成了"API 契约 + 未来防线"**。若希望它重新承担 UI 上的实时职责，需回到候选修法 1（Merge 成员改为只认精确匹配），让手输的不存在基因重新变成可表达状态。**该修法已于 2026-09-11 落地，见下方补记 —— 但落点不是 Merge 选择器。**

候选修法（择一）：
1. Merge 成员要求精确（大小写不敏感）匹配，主基因路径保持不变 —— 改动最小，但会与 plots 的解析结果进一步分叉；
2. 保留回退，但新增第三个字段 `gene2_partial`，让前端把子串命中标成"疑似"而非"已解析"。

另需注意：`stats.py` 与 `plots.py` 的解析器本就不一致（前者只查 `var_names`，后者还查 `index`/`gene_ids`/`gene_symbols`/`feature_name` 列），去重行为也不同 —— 同一个 `gene2` 在图与表可能得到不同的成员集。修的时候应抽成一个共享解析器，否则图与表的警告会互相矛盾。

### 涉及文件
- `server/analysis/utils.py`（`resolve_gene_indices`，**根因，未改**）
- `server/analysis/stats.py` / `server/analysis/plots.py`（两条各自的解析路径）
- `src/components/analysis/geneInput.ts`（新增，精确匹配守卫）
- `src/components/analysis/BoxPlotContainer.tsx` / `ExpressionChartContainer.tsx`（3 处文本框接入）
- `src/components/analysis/ExpressionChartContainer.tsx`（Merge 选择器，2026-09-10 已封）
- `server/search.py`（新增 `rank_gene_matches`）/ `server/routes.py`（`handle_search_genes`）

### 关键教训
- **新增的「已解析 / 未解析」契约会把既有的模糊匹配升级成静默错误。** 把宽松解析的结果当作"确认无误"回传给 UI，比不回传更危险。
- 涉及基因名解析的功能，**只有精确匹配才能作为「已确认」的依据**；子串命中最多算「疑似」。B24/B26/B27 的教训是"失败不要伪装成成功"，这条是它的近亲：**猜测不要伪装成确认**。
- **判定缺陷严重性必须实测可达性，不能只读代码。** 本次初判把「用户填 COL1 就会中招」当成结论写进日志，实测才发现回车选中的是 `COL10A1`、Create 项挤在末位第 17 个。**机制成立 ≠ 路径可达** —— 可达性只有把 UI 真跑一遍才量得出来，读代码永远量不出来。教训：先测可达性，再定严重级别，最后才写日志。

### 2026-09-11 补记：真正的宽入口是三个**自由文本框**，不是 Merge 选择器

前一轮只封了 Merge 选择器。今天逐行读代码，发现同一批「基因输入」里还有 **3 个纯文本输入框**，它们的下拉只是**提示**，不是约束：

| 位置 | 文件:行 |
|---|---|
| Tab 2 Gene | `BoxPlotContainer.tsx:51-52` |
| Tab 3 Gene | `ExpressionChartContainer.tsx:217-218` |
| Tab 3 GENE2（single 模式） | `ExpressionChartContainer.tsx:249-250` |

三处逐字相同：

```jsx
onKeyDown={(e) => { if (e.key === 'Enter' && geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); ... } }}
onBlur={() => { if (geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); setGeneSearchInput('') } }}
```

`geneSearchInput.trim()` 是**用户打的原文**，从未与 `geneSuggestions` 比对过。`onBlur` 尤其宽：**不用按回车**，鼠标点到任何别处即提交。

对照 2026-09-10 那轮的结论 —— 那次实测的是 `AsyncCreatableSelect`（必须点击候选项）。文本框不要求点击，所以「用户眼前有真选项，Create 被挤到末位」这层保护**在这里根本不成立**。这正是「机制成立 ≠ 路径可达」的反向教训：**可达性不能只测一次就外推到所有入口。**

#### 实测（Lung IPF，33,694 基因，后端进程内直调）

```
COL1   -> COL16A1                    CD3    -> ABCD3
A1     -> VWA1                       col1a1 -> COL1A1（大小写不同，正确命中）
NOTAGENE -> 未找到
```

`CD3 → ABCD3` 最能说明问题：图上、表头写的都是 `ABCD3`，数值完全合理，读者只会觉得「CD3 表达怎么这么怪」。

#### 修法（用户选定方案 A）

新增 `src/components/analysis/geneInput.ts`：

- `exactGeneMatch(typed, candidates)` —— 只认**忽略大小写后完全相等**，并返回**候选的拼写**（打 `egfr` 存 `EGFR`）。
- `resolveGeneChoice(typed, listed, search)` —— 先查下拉；未命中再查一次服务端（下拉有 200ms 防抖，一个词一次打完时列表还停在上一拍，直接拒绝会误杀真基因）；仍不命中则 `reject`，**绝不回落成"那就用它"**。
- `unknownGeneMessage(typed)` —— 提示文案的唯一来源，组件与测试共用。本轮就踩过这个坑：先写死 `/not a gene/i` 去匹配 "No gene named …"，断言空过。

`commitGene` / `commitGene2` 接到上述三处，未命中时**保留用户输入**并显示提示，不再静默提交。Merge 选择器的 `isValidNewOption={() => false}` 保持不变。

#### 连带发现：真实基因 `F2` / `T` 会被挤出自己的搜索结果

`/api/search-genes` 先按字母序排序、再截断到 100 条。IPF 里有 2 个基因（`T`、`F2`）的名字包含于 >100 个其它基因名，按字母序排在 100 名之外 —— **它们不在自己的搜索结果里**（`F2` 是凝血因子 II，真实且常用）。

修 A 之前：打 `F2` 回车 → 静默变成别的基因。修 A 之后：变成**选不了**。两个方向都不能接受，所以这不是可选项 —— 修 A 不带上它就是引入一个能力回归。

`server/search.py` 新增 `rank_gene_matches()`：**精确命中排在截断之前**；`routes.py:279` 改用它。实测 IPF：`q=F2` → 首位 `F2`（原为 0 命中）、`q=T` → 首位 `T`、`q=CD3` → 26 项且无精确命中（提示正常出现）、`q=COL1A1` → 1 项精确。

#### 验证

- vitest **87 passed (12 files)**（本轮前 71）；`npx tsc --noEmit` 干净。
- **变异验证**（两次，均被抓住）：把 `exactGeneMatch` 改回"永远提交原文" → **12 个用例失败**；去掉服务端兜底 → **5 个失败**，其中包含两个既有的「正常选中基因」用例 —— 证明兜底是承重的，不是装饰。
- `server/tests/test_gene_search_rank.py` 9/9；其余后端脚本 66/0、9/0、31/0。
- 顺带修正两处**恒真的既有断言**：`BoxPlotContainer.test.tsx` 原来用 `getByTestId('plot-image')` 判断「基因选中了」，而该元素只要有 `realPath` 就永远在 DOM 里 —— 改为断言 `placeholder`（它镜像 `selectedGene`，是唯一能区分"选中了"和"什么都没发生"的判据）。

#### 仍未修复

后端 `utils.py:124` 的子串回退**原样保留**：接口直连、手改 URL/bookmark、以及 Free Analysis 里 LLM 自行调工具这三条路径仍可触发。`test_gene2_op.py::test_known_partial_match_hazard` 继续钉住该现状 —— **修它时该用例应当失败并被改写，不是被删掉。**

#### 2026-09-11 三次修正：上面的「全部入口已封堵」是错的

`resolveGeneChoice` 只挡住了用户**当场打字**这一条路径。同样能决定「往后端发哪个基因」的还有两条，都没接它：

| 路径 | 位置 | 状态 |
|---|---|---|
| 手输文本框（前面那轮封的） | 3 处 `commitGene`/`commitGene2` | 已封 |
| **从 sessionStorage 恢复** | 5 个基因键的读取点 | **从未封** —— 见 B34 |
| **UMAP / Bulk 的提交** | `UmapPlot.tsx:184-187`（裸 `onChange`，每次击键即提交）、`BulkAnalysisTab.tsx:263 selectGene` | **从未封** |

恢复路径尤其致命：用户上次输入过的 `CD3` 一直躺在 `sessionStorage` 里，每次打开对应 tab 都被原样读回并**自动取数、自动出图**，用户没有任何机会看到那句 `No gene named "CD3"` —— 因为那句话只在提交时才会出现。B34 就是这个。

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

## B30. 「坏文件会让扫描线程永久空转」——原判定经实测**证否**；但查出一条真实的静默降级 (2026-09-11)

### 缘起：一条我说错了两遍的结论

起因是这句话：**「`scan_datasets()` 逐文件没有 try/except —— 一个坏文件会让整个扫描线程静默死掉（`main.py:42` 也没兜底），datasets 从此永久为空。」** 每个子句都经不起实测。先写在最前面，因为这条已经对用户复述过两次。

### 实测：三个子句逐条证否

1. **「没有 try/except」→ 循环体本身确实没有，但它调的每一个逐文件函数各自都有。**
   `_read_obs_stats`(:165)、`resolve_bulk_table`(:280)、`_extract_path_fields`(:227)、`_get_annotation_info`(:77) 全部自带 `try/except`。损坏的 `.h5ad` 在 `_read_obs_stats` 内就被接住 —— 该守卫是 **B27 加的**，返回 `_read_failed: True` 占位值，并向 stderr 打一行 `Error reading obs stats from <path>`。守卫在正确的层级上，只是不在我以为的那一层。

2. **「datasets 从此永久为空」→ `datasets.clear()` / `extend()` 写在函数末尾**，所以真有异常逃逸时列表**停在上一轮的值**，不是被清空成 `[]`。这不是疏漏，**这个写法本身就是故障原子性**。已用故障注入钉死（见下）。
   启动期的「上一轮」确实是 `[]` —— 但见第 3 条。

3. **「扫描线程死掉」→ 有两层兜底。** `scanner_loop`(:585) 每 30s 重扫一次且自带 `try/except` + traceback（`main.py:50` 起的是**另一个线程**）；`_initial_scan`(`main.py:42`) 即使整个挂掉，也只损失首次扫描，30s 后由循环线程补上。**「永久为空」不成立。**

逐个失败模式实测（`/tmp/probe_scanner_escape.py`，五种全部 contained，无一逃逸）：

| 注入的失败 | 扫描是否抛异常 |
|---|---|
| 损坏的 `.h5ad`（纯文本 / 截断） | 否 |
| 符号链接自环（重新软链链错） | 否 |
| 断链（指向不存在的目标） | 否 |
| 目录符号链接成环 | 否 |
| `mode 000` 的文件 | 否 |
| 非法 UTF-8 的 bulk 表（csv） | 否 |

残余的无守卫点只有 `resolve_h5ad` 里的 `real.stat()`（`Path.stat()` 不像 `exists()` 那样内部吞 `OSError`）。但 `exists()` 刚成功过，要触发只能是两次调用之间文件被删/被卸载的 TOCTOU 竞态。**没有找到现实的触发路径**，因此不构成一条可报的缺陷。

### 但查出一条真实缺陷：读失败被洗成合法的「0 计数」行

`_read_failed` 标记在离开 scanner 前被 `_strip_read_failed()`(:181) **剥掉**（`:361` / `:482`），接口层于是拿到一条计数全 0、与其他行毫无区别的记录。**前端因此无法区分「这个文件读不出来」与「这个数据集真的是 0 个病人 / 0 个细胞」**，唯一信号是后端 stderr 里的一行 —— 而用户看不到后端 stderr。

这正是**用户最初那句「我有的数据有问题，修改之后，再链接过去，很容易就出 bug」**的另一半：坏文件不会让页面变空，而是让页面**安静地显示一行全 0 的数据**，看起来像一份合法的、只是比较空的数据集。与 B26/B27 同源 —— **失败不要伪装成成功**，只不过 B27 修好了「不要持久化」，没修「不要伪装成合法数据」。

### 用户的实际症状，完整链路

用户的原话是「**当我修改了原数据，然后前端显示一行全 0 的数据**」。把上面两条拼起来，每一步都有出处：

| # | 环节 | 代码位置 | 结果 |
|---|---|---|---|
| 1 | 改数据 → 文件在一个窗口内读不出来 | `_read_obs_stats` :170 捕获 | 返回全 0 占位 |
| 2 | 失败标记被抹掉 | `_strip_read_failed` :181 → :479 | 接口层看不到「这次失败了」 |
| 3 | 状态被硬编码 | `status = 'ready'` :416（`if age_s < 60: pass` 是空壳） | **`status: 'ready'` + 全 0** |
| 4 | 前端认为无需轮询 | `rows.some(r => r.status !== 'ready')` 为 false | **轮询永不启动** |
| 5 | 渲染 | 绿色 Ready 徽标 + `0 / 0 / 0` | 看起来像合法但很空的数据集 |

后端 ≤30s 后自愈，**但第 4 步让前端永远不回头问**，所以那行 0 会一直挂着到手动刷新。**第 3 步单独拿出来看是无害的，第 4 步也是；是它们相乘才让 0 永久驻留。**

### 修复（2026-09-11）

失败必须自带状态，不能靠"看起来是 0"来表达。改动很小，因为它只需要打断第 3 步 —— 第 4 步的轮询条件本来就写对了（`status !== 'ready'`），只是从来没被 `error` 触发过。

- **`server/scanner.py`**：新增 `_row_status(obs_stats)`，读失败时返回 `'error'`。`resolve_h5ad` 与 `resolve_bulk_table` 两处出参状态改用它（`resolve_bulk_table` 原先同样硬编码 `'ready'`，是同一个 bug 的第二份拷贝）。`_read_failed` 本身仍不外泄。
- **`server/scanner.py`**：`_read_obs_stats` 补一道守卫 —— 读成功但 `obs_columns` 为空时一并按读失败处理。HDF5 没有事务性读取，文件写到一半时 `open` 可能"成功"返回一个句柄而 obs 表仍为空：**不抛异常，只是 0 行 0 列**，于是照样是一行绿色 `Ready` 配 `0/0/0`。`_is_valid_cache_entry` 早就认定这种条目不可用，`status` 必须同意。实测 102 条缓存条目无一受影响（全部有 obs 列，`n_obs` 最小 35）。
- 顺带删掉 `resolve_h5ad` 里一句**死代码**：`status = 'ready'` + `if age_s < 60: pass`（注释声称在处理"文件刚被修改、可能还在上传"）。它从未生效，却让读者以为这个 case 已经处理了 —— 也正因为如此，上面 `_row_status` 的参数才一直是个空契约。改为无参，`age_s` 一并删除。
- **`src/pages/TissuePage.tsx`**：三态徽标（Ready / **Read failed** / Processing）；`error` 行的 Patient / Sample / Cells 三列显示 `—` 而非 `0`（**0 是一个测量值，对一个读不出来的文件我们并没有这个测量值**）；页脚把 `error` 与 `processing` 分开，不再把读失败叫成 "Processing..."；CSV 导出同样不落 0。行数统计 `errorRows` / `processingRows` 在组件内派生。
- **`src/pages/SearchPage.tsx`**：**同一件事的第二个页面**。`server/search.py:94` 用 `**ds` 把整行扫描结果展开进每一条命中，所以读失败的数据集会带着 `status: 'error'` 和三个 0 抵达搜索页；表格照旧渲染 `0 / 0 / 0`，而 PMID 链接（`:175` 早写着 `disabled={row.status !== 'ready'}`）被灰掉却**没有任何解释**——读起来像"一个很小、但就是打不开"的数据集。改为同样的 `—` 占位 + `Read failed` 徽标。这是 review 查出来的，不在原计划里。
- **`src/pages/TissuePage.tsx`（页脚计数口径）**：`errorRows` / `processingRows` 改为从 `displayRows` 派生。原来从 `rows` 派生，于是**看不见的行**（另一个 omics tab、或被过滤掉）也会触发"1 dataset(s) could not be read"。页脚就贴在表格下面，读起来是对表格的陈述，指的是表格里没有的东西。轮询仍然看全部 `rows`（`:119`），所以隐藏的失败照样自愈，只是不再从屏幕外喊。
- **`src/api/types.ts`** 未改：`status` 本就是 `string`，无需扩联合类型。

**端到端实测**（真实后端 :6001，非 mock）：埋入一个损坏的 `.h5ad` → 第 20s 扫描到，接口返回 `status=error patient=0 n_obs=0`（修复前这里是 `status=ready`）；把文件改回合法 h5ad → 第 24s 接口返回 `status=ready patient=2 n_obs=40`。**自愈是真的，只是修复前前端从不去看。**

### 顺带发现

- **`Path.rglob()` 在 Python 3.10 会静默吞掉 `OSError`。** 实测：一个 `mode 000` 的目录，其下的 `.h5ad` **不报错、不告警、直接消失**。权限问题因此表现为「数据集少了几条」，而非任何形式的失败。这是本次唯一一个**真正无信号的静默丢失**通路，比原来担心的那条严重。**已修**：`scan_datasets` 的遍历换成 `os.walk(data_dir, onerror=_report_walk_error)`，进不去的目录会往 stderr 写一行。等价性已实测：`Data/` 下无目录软链，`os.walk(followlinks=False)` 与 `rglob` 在同一份数据上给出**逐字节相同**的文件集合（96 = 96，差集为空）。测试 `[8]` 用 `mode 000` 目录锁住这条：可读目录照常入列、不可读目录确实扫不到（前置条件）、且必须出现在 stderr。
- **就地覆写已入库的 `.h5ad` 会失败。** 写测试时踩到 `OSError: Unable to synchronously create file (unable to truncate a file which is already open)` —— 扫描后文件仍被共享 backed 句柄（`core.adata_cache`，B24 引入）持有。用户「改文件再重链」的实际工作流走的是**新路径**，所以不受影响；但就地改数据文件的任何操作都会撞上这一点。

### 验证手段

**后端** `server/tests/test_scanner_resilience.py`（自包含，无 pytest，失败退出码非 0）：**31 passed / 0 failed / 0 known gap**。
B27 回归 `server/tests/test_scanner_obs_cache.py`：**9 / 0 通过**，未被本次改动破坏。
真实数据全量扫描：**96 行，0 行非 ready**，与改动前一致。

- 第 [6] 节用**故障注入**（monkeypatch `_extract_path_fields` 抛 `RuntimeError`）钉住原子性 —— 不是读代码断言「clear 在末尾所以安全」，而是真的制造一次逃逸。
- **变异验证 ×2**：① 把 `datasets.clear()` 从函数末尾挪到开头，[6] 立刻失败并复现出原文担心的症状（`前 ['11111111','22222222'] → 后 []`），其余项目不受影响；② 把前端轮询条件改成忽略 `error` 行，**恰好**只有 `auto-recovers an unreadable row` 一条失败。两个断言都是承重的。
- 另锁死：失败不落盘（B27 规则，查 `.scanner_cache.json` 里确实没有坏文件条目）、修复后下一轮认到真实数值（`n_obs=40`）。

**前端** `npx tsc --noEmit -p tsconfig.app.json` 干净；`npx vitest run` **64 passed（9 files）**。新增 7 项：

- `error` 行不得渲染成 `0 / Ready`（并断言三个 `—`）；`error` 行必须在 5s 轮询后自愈成 Ready + 真实计数。
- 页脚必须称读失败为 "could not be read"，而不是 "Processing"。
- 不在当前 tab 的读失败行**不得**出现在页脚警告里（切到它的 tab 才出现——同一份数据、同一个页脚，只有可见行变了，这是本项的阳性对照）。
- CSV 导出里读失败行不得落 0（断言 Patient/Sample/CellTypes 三段恰为 `-`）。
- 搜索页：读失败命中不得渲染成 0（断言三个 `—`）；可读命中照常显示真实计数（阳性对照，否则上面那条在"整列不渲染了"时也会通过）。

**变异验证 ×5**（后三条是本轮 review 指出的"无守卫"项，逐一补上并证明其承重）：页脚删掉 "could not be read" → 2 项失败；CSV 三元还原 → 1 项失败；`errorRows` 改回作用于全部 `rows` → 1 项失败；SearchPage 还原 0 渲染 → 1 项失败。加上此前的轮询变异与 `datasets.clear()` 位移，共 5 处断言被证明是承重的，不是摆设。

### 涉及文件
- `server/scanner.py` —— `_row_status`、两处出参状态、`_read_obs_stats` 的 obs_columns 守卫、`os.walk` 替换 `rglob`、删死代码
- `src/pages/TissuePage.tsx` —— 三态徽标、`—` 占位、页脚分流（含计数口径）、CSV
- `src/pages/SearchPage.tsx` —— 同一漏洞的第二个界面：`—` 占位 + `Read failed` 徽标
- `server/tests/test_scanner_resilience.py`（新增，未跟踪）、`src/pages/TissuePage.test.tsx`、`src/pages/SearchPage.test.tsx`（新增，未跟踪）

### 关键教训
- **不要拿「函数里没有 try/except」推断「会崩」。** 守卫可以在被调用方内部；本次四个被调函数全都有。判断容错性要看**失败实际在哪里被接住**，不是看某一段源码长什么样。
- **「没有守卫」与「清空状态」要分开看。** 这里恰恰是：循环没有守卫，但 `clear()` 放在末尾让无守卫变得无害。**故障原子性来自赋值的位置，不来自 catch 的数量。**
- **最危险的不是崩溃，是降级成一个看起来正常的值。** 崩溃会有人报，`0 patients / 0 cells` 不会 —— B26、B27、B29、B30 是同一条线的四次现身，每次换一层（网络缓存 / 持久缓存 / 浏览器缓存 / 接口契约）。
- **一句话结论要先证伪再复述。** 这条我在没有实测的情况下说了两遍，用户又拿它回来问「修了吗」。写测试的成本远低于把错误结论写进缺陷库的成本。

---

## B31. 首页 Tissue Atlas：三个物种 tab 共用一份数据集映射，Mouse/Monkey 显示的是 Human 计数 (2026-09-11)

### 现象
用户报告：首页示意图切到 Monkey / Mouse，器官上显示的数值没有分物种，把人的数据也算进去了。（同源清理见 B30 的 search 页与 tissue 页。）

### 根因
`src/components/TissueAtlas.tsx` 的 `useEffect` 建映射时**完全没看 `d.species`**：

```tsx
for (const d of data) {
  const t = d.tissue?.toLowerCase() || ''
  if (!map[t]) map[t] = []
  const e = map[t].find(x => x.name === d.disease)
  if (e) e.count++; else map[t].push({ name: d.disease, count: 1 })
}
```

一份**全物种**映射，三个 tab 共用（`liveDiseases = tissueDiseases[hoveredSlug]`）。而 `organShapes.ts` 里 Mouse / Monkey 的器官 slug 与 Human 的 tissue 名**逐字相同** —— `kidney` / `lung` / `liver` / `colon` / `spleen` / `heart` / `stomach` / `brain` —— 小写化后撞进同一个 key。切物种只换了身体轮廓，数值没换。

### 实测影响（真实数据，非推演）
96 条数据集 = **93 Human / 1 Mouse / 2 Monkey**。修复前切到 Mouse tab 悬停 Kidney（小鼠本无肾脏数据）：显示 `IgAN:1, Health:2, CKD:1` —— 4 条人类数据。因为 Human 占 97%，两个非 Human tab 上看到的**几乎全是人类数字**。

修复后按物种归拢，同一份数据变为：
- Mouse：仅 `ear: Health 1`，其余器官 "No datasets yet"
- Monkey：`lung: Health 1`、`multi-organ: Multi-organ 1`

### 修复
映射加一层 species key（`SpeciesTissueMap` = `Record<species, Record<tissue, {name,count}[]>>`），取值改为 `tissueDiseases[species]?.[hoveredSlug]`。仍是**单次 fetch + 10s 轮询**，切 tab 不重新请求。

### 验证
新增 `src/components/TissueAtlas.test.tsx` —— 该组件此前**零覆盖**，`src/components/` 下此前没有任何测试文件。先 RED：`AssertionError: expected <span></span> to be null`，失败的正是「Mouse tab 上冒出了 Human 的 IgAN」。修复后 GREEN。
**变异验证**：把 species 那一层摊平回扁平 map，两项测试**恰好**全失败 —— 守卫承重。
全量 `npx vitest run` **66 passed（10 files）**，`tsc --noEmit -p tsconfig.app.json` 干净。

### 涉及文件
- `src/components/TissueAtlas.tsx` —— `SpeciesTissueMap` + 建映射 + 取值
- `src/components/TissueAtlas.test.tsx`（新增）

### 关键教训
- **「撞名」在没有类型系统兜底的地方是静默的。** 三个物种的器官 slug 用同一套词，程序上完全合法，没有任何地方会报错 —— 只有把两个 tab 并排看一眼才会发现。**跨实体的 key 必须自带实体前缀**，这跟 B30 的「失败必须自带状态」是同一条：不要让两个不同的东西长得一样。
- **占比悬殊会掩盖串号。** 93:1:2 之下，非 Human tab 显示的几乎全是 Human 数据，反而「看起来很合理」。如果三个物种数据量相当，一眼就能看出不对。

---

## B32. 分析页从 URL 直入时绕过「未就绪」检查，读不到的文件照样当数据加载 (2026-09-11)

### 现象
B30 修复后，Tissue 表的 PMID 链接已对未就绪的数据集置灰。但**直入 URL 仍然进得去**：手输地址、书签、浏览器后退、以及 `SearchPage` 之外任何拼出 `/analysis/:tissue/:disease/:pmid` 的地方。进去之后页面照常发起 `analysis-info` / `umap-data` / `plot` 等一系列请求，全部打在扫描器**已经判定读不了**的文件上。

### 根因
`src/pages/AnalysisPage.tsx` 的取数 effect **只看 `real_path` 在不在，完全没看 `status`**：

```tsx
findDataset(tissue, disease, pmid).then((ds) => {
  if (ds?.real_path) {          // ← 未就绪的行同样有 real_path
    setRealPath(ds.real_path)
    …
  } else setError('Dataset not found')
})
```

`scanner.py` 对未就绪的行**照样返回 `real_path`**：
- `status: 'error'`（读失败）→ `resolve_h5ad:493` 的 `_row_status(obs_stats)`，`real_path` 指向那个坏文件；
- `status: 'importing'`（bulk 转换中）→ `resolve_bulk_table:349`，`real_path` 指向**尚未生成的**缓存 h5ad。

两者都满足 `ds.real_path` 为真，于是守卫形同不存在。

### 与 B30 的关系
B30 堵的是**展示层**（表格把 0 印成 0），B32 是**同一个错误的第二个入口**：数据根本没到展示层，页面直接拿着 `real_path` 去要数据。同一个「错误值伪装成合法值」在这里表现为「错误数据集伪装成可加载数据集」。

### 修复
1. `findDataset` 回包先判 `ds.status !== 'ready'`，未就绪则**在设置 `realPath` 之前返回**，因此 `realPath` 保持 `''`，下游 `fetchAnalysisInfo` / `fetchUmapData` / 各 plot 的 effect 全部依赖 `realPath`，**一个请求都不会发出去**。
2. 拒绝条件与表格的置灰条件**逐字对齐**（`status !== 'ready'`，不是 `!== 'error'`）—— 这样 `importing` 也一并拦住。两边一旦分叉，必有一边是错的。
3. 错误页加 **Retry**：读失败是自愈的（扫描器每 30s 重扫），死胡同式的错误页逼用户手动刷新。retry 只递增 `attempt` 触发 effect 重跑；**不清 `error`**，于是重试期间错误页保持挂载，重试又失败时屏幕无任何闪动。
4. 「找不到数据集」是**终结态**，不给 Retry —— 否则按钮点一辈子也不会变。

### 验证
新增 `src/pages/AnalysisPage.test.tsx`（5 项，子组件全部 mock 成 `null`，只测守卫）。RED 证据：`status: 'error'` 的数据集渲染出的是**正常分析界面**（DOM 里出现 `Back` / `IgAN` / `PMID:`），断言 `findByText(READ_FAILED_RE)` 失败。

**变异验证 ×4，全部被捕获**：

| 变异 | 结果 |
|---|---|
| 删掉 `status !== 'ready'` 守卫（改成 `if (false)`） | 3 failed / 2 passed |
| Retry 按钮恒显示（`canRetry &&` → `true &&`） | 1 failed（「找不到数据集不给 Retry」） |
| effect deps 去掉 `attempt` | 1 failed（「Retry 后能打开」） |
| 未就绪时不再 `setCanRetry(true)` | 1 failed（同上） |

全量 `npx vitest run` **71 passed（11 files）**，`npx tsc --noEmit` 干净。

### 涉及文件
- `src/pages/AnalysisPage.tsx` —— 守卫 + `canRetry` / `attempt` state + Retry 按钮 + 两条文案常量
- `src/pages/AnalysisPage.test.tsx`（新增）

### 关键教训
- **入口有几个，守卫就得有几个。** 修 B30 时只封了 Tissue 表和 Search 页两个**展示**入口，却漏了这个**跳转**入口 —— 而跳转入口的危害更大：展示层顶多印错数字，跳转入口会让下游一连串请求全部打在坏文件上。修完一处务必把「还有谁能到达这里」问一遍。
- **同一条不变量分散在两个文件里，就是迟早要分叉的信号。** 「未就绪不可进入」这条规则现在同时写在 `TissuePage.tsx`（置灰链接）和 `AnalysisPage.tsx`（守卫）里，靠本条目第 2 点的注释维持一致。真正干净的做法是把 `status !== 'ready'` 抽成一个共享谓词，一处定义两处引用。
- **自愈的失败要配可重试的 UI。** `status: 'error'` 30 秒后会自己好，但一个只有「Go Back」的错误页会把它变成一个需要人工刷新的死胡同 —— 用户看到的现象就退化成「这个数据坏了」。错误信息里写上「后端每 30 秒重扫一次」比只说「读不了」有用得多。

---

## B33. 10 处分析取数绕过 per-file 锁：`get_adata()` 被当成「读元数据」用，实际每次都在裸读 HDF5 (2026-09-11)

### 现象
没有用户可见的稳定复现 —— 这正是它一直没被抓住的原因。它表现为**偶发**的请求挂起 / h5py 并发报错，用户看到的往往是「这个图加载不出来，刷新一下又好了」，与 B24 / B27 同源。

### 根因
`server/core/adata_cache.py` 的 `get_adata()` 文档字符串写得很明确：

> *"Thread-safe cache, but **callers MUST serialise access themselves** (use `locked_backed_adata()`)."*

而 8 个分析函数直接裸调 `get_adata()`，从未在锁内。实测（给 `h5py.Dataset.__getitem__` 打桩计数）说明了两件事：

| 访问 | 实际 HDF5 读次数 |
|---|---|
| `read_h5ad(path, backed='r')`（即缓存未命中时的 `get_adata`） | **8** |
| `adata.obs[...]` / `.var_names` / `.n_obs` / `adata.X`（只取句柄） | 0 |
| `adata[:, i].X` / `X[:, i]` | **1~3** |
| 其后的 `.toarray()` / `np.asarray(...)` | 0 |

所以裸调 `get_adata()` 有**两处**都在锁外：(1) 缓存未命中时它自己开文件读 8 次；(2) 紧跟着的 `X[:, i]` 切片。讽刺的是，多数调用点看起来像「只是读元数据」，于是被理所当然地认为不需要锁。

第二个容易踩的点：**`X = adata.X` 单独一行不读盘**，读发生在后面的 `X[:, i]`。所以把 `X = adata.X` 留在锁外等于让 backed 句柄逃逸 —— 锁必须一直覆盖到最后一个切片。

### 修复
8 个函数改为 `with locked_backed_adata(...) as adata:`，锁窗口**由实测的读盘点决定**，而不是整函数上锁：重型计算（matplotlib、Fisher、MU 检验、CSV 拼装）一律出块执行，与 `plots.py:941 _generate_marker_dotplot` 的既有范式一致。

| 文件:函数 | 真正读盘的行 | 锁窗口 | 出块后的重型工作 |
|---|---|---|---|
| `plots.py:_generate_plot` | 63 | 37–70 | 72–185 matplotlib |
| `plots.py:_generate_celltype_composition` | 230, 252, 280 | 209–283 | 284–351 matplotlib |
| `plots.py:_generate_cell_ratio_plot` | 无（只读 obs） | 367–387 | 388–573 pandas/matplotlib |
| `plots.py:_generate_umap_ratio_plots` | 无（只读 obs） | 586–619 | 621–898 seaborn/scipy |
| `stats.py:_get_per_sample_table` | 75 | 29–79（列提取上提） | 81–106 聚合 |
| `stats.py:_get_per_sample_mutest` | 173 | 138–174 | 176–238 MU 检验 |
| `stats.py:_get_aggregate_table` | 387（经 394/431/439 调用） | 307–443 | 445–496 emit + Fisher |
| `stats.py:_get_raw_expression` | 579 | 544–587 | 589–603 CSV 拼装 |
| `expression.py:_get_expression_stats` | 80, 112, 136 | 36–81（列提取上提） | 83–160 三趟聚合 |

两处顺带改动，都是为了「列必须在锁内落地」这条硬约束：
- `stats._get_per_sample_table` / `expression._get_expression_stats` 原本在**每个循环里重复切片**同一个基因列（expression 里是 3 趟循环各切一次）。上提为 `dense_by_gene` 字典后，每个基因列在锁内只读一次 —— 既满足锁边界，又少读 2 次。
- `stats._get_raw_expression` 原本只有 `get_adata` 一行在 `try` 内，函数其余部分抛错会直接 500。为**逐字保留这一语义**，用 `ExitStack` 把锁的进入点单独包在原来的窄 `try` 里，而不是把 `with` 套在整个函数上（那会把一个解析 bug 重新标记成 `Failed to read h5ad`）。

### 死锁核查（非可重入锁，必须查）
`locked_backed_adata` 用的是普通 `threading.Lock`。已确认 9 个函数**只被 `routes.py` 直接调用**，没有任何调用方已持锁，函数之间也互不调用 → 无嵌套、无死锁。（`grep` 结果：每个函数恰好一个调用点，全在 routes.py。）

### 验证
1. **后端自包含脚本全绿**：`test_scanner_obs_cache.py` 9/0、`test_scanner_resilience.py` 31/0、`test_gene2_op.py` 66/0。
2. **A/B 等价性对拍**：把改动前后两个版本分别在独立进程里跑同一份真实数据（Lung IPF, 89326 cells），对 11 个函数取**全部返回值**，把 base64 PNG 换成「尺寸 + 像素 md5」后逐字节比较 —— **11 项中 8 项完全一致，3 项仅 boxplot 像素不同且尺寸相同**。
3. **那 3 项是既有的不确定性，不是本次引入**：同一进程内连跑 3 次，原版与新版**各自都**给出 3 个不同的 boxplot 像素哈希，而 barplot 在两版上都是**同一个**哈希。定位到 `plots.py:121/532` 的 `sns.stripplot` —— 散点抖动走 numpy 全局 RNG（`np.random.seed(0)` 后即稳定）。**这条另记：boxplot 出图不可复现，任何基于图像比对的测试都不能用它做基准。**
4. **HTTP 端到端**：改动前先在旧进程上抓 12 个端点的响应基线，重启后再打一遍 —— 9 个确定性端点**逐字节相同**。

### 未覆盖（明确留白，不谎称已全覆盖）
- `analysis/umap.py:21 _get_umap_data` 与 `analysis/expression.py` 同属一类，但它的两处基因切片在 `if color_by == 'Gene'` 的两个分支内部，锁窗口要跨分支重构，风险高于收益 —— **本次未改**，留待单独一轮。
- `search.py:32 _get_genes` 是**事后才发现的第 11 处**，同样裸调 `get_adata()`。缓存未命中时它会走完整的 8 次 HDF5 读，随后读 `var_names`。修法同样是就地包一层 `locked_backed_adata`（3 行，返回值是已物化的 `set[str]`，锁窗口极小），但**不在本次「方案 A」范围内，未改**。触发表面：任何一次 `/api/search-genes` 冷缓存调用。
- `core/adata_cache.py:69` 的 LRU 淘汰在 `_cache_lock` 下 `old_adata.file.close()`，不检查是否有别的线程正持该文件的 per-file 锁读同一个句柄。这是 per-file 锁**之外**的竞态，未修。
- `_get_file_lock(path)` 以**传入的 path 字符串**为键。同一次请求链路里 routes 传的是同一个 `real_path` 字符串（锁有效），但若日后有调用方传符号链接路径或 `../` 变体，会拿到不同的锁、从而失去互斥 —— 未加规范化。

### 涉及文件
- `server/analysis/plots.py` —— 4 处加锁；移除已无用的 `get_adata` import
- `server/analysis/stats.py` —— 3 处加锁 + `_get_raw_expression` 的 `ExitStack`；新增 `contextlib.ExitStack` import
- `server/analysis/expression.py` —— 加锁 + 三趟循环的列上提

### 关键教训
- **「只是读元数据」是个危险的直觉。** 这 9 个函数里有 6 个的注释/写法都暗示自己在读小东西，但 `get_adata()` 本身在缓存未命中时就是要读 8 次 HDF5。**判断要不要加锁，要看被调用函数的契约，不要看调用点看起来有多轻。**
- **锁的边界应该由测量决定，不是由审美决定。** 「整函数上锁」最省事但会把 matplotlib 和 Fisher 检验也串行化；「只锁 `adata = ...` 那一行」则完全没用。这次先给 `h5py.Dataset.__getitem__` 打桩数出真实读盘点，再定窗口 —— 每一处的边界都能指到具体某一行。
- **`adata.X` 是句柄不是数据。** 任何「把 `X = adata.X` 放在锁外、切片放在锁内」的写法都是错的：句柄一旦逃逸，锁就失效了。
- **副作用是意外收益。** expression.py 的三趟循环原本各切一次同样的列，上提到锁内后每个基因只读一次 —— 这次改动的收益不只是并发安全，还有少了 2/3 的列读取。

---

## B34. 持久化的基因选择跨数据集泄漏；后端把「实际画了哪个基因」藏起来 (2026-09-11)

### 现象

用户原话：

> 好像有个bug耶，当我第一次在Boxplot页面输入CD3 然后显示No gene named "CD3" in this dataset，但我切到Barplot，GENE已经默认是CD3了，并且还有图

BoxPlot tab 输入 `CD3` → 正确出现 `No gene named "CD3" in this dataset`；切到 BarPlot tab → **GENE 框里已经是 `CD3`，而且图已经画好了**。

### 根因（三层，缺一层都解释不了现象）

1. **CD3 是怎么进 `gensci_agg_gene` 的 —— 不是 BoxPlot 泄漏过去的。**
   两个组件分处不同挂载位（`AnalysisPage.tsx:205` / `:213`），键不同，无 prop 共享。决定性证据：`git log -S "gensci_agg_gene" -- src/components/analysis/BoxPlotContainer.tsx` **为空** —— BoxPlot 从未写过 BarPlot 的键。CD3 在用户切过去之前就已经在存储里了，两件事是先后关系，不是因果。
   真正的写入者是 B28 修复（`2a51c2d`）**之前**的旧 bundle：`2a51c2d^:ExpressionChartContainer.tsx:217-218` 里 `setSelectedGene(geneSearchInput.trim())`，无条件把原文提交。用户此前在 BarPlot 打过一次 `CD3`，就永久留下了这个值。

2. **B28 的守卫只加在「提交」路径上，「恢复」路径从未校验。**
   `ExpressionChartContainer.tsx:74` 把它原样读回来，直接进 `PlotImage` 的 `gene` prop，随即取数。

3. **后端把未知 token 按子串回退解析，并且从不回传它实际用了哪个基因。**
   `analysis/utils.py:124`（`plots.py` 内有一份同样的内联实现，`bulk.py` 的 `_resolve_gene` 同形）。实测 Lung IPF（33,694 基因）：

   ```
   CD3  → ABCD3        COL1 → COL16A1        A1 → VWA1
   ```

   `ABCD3` 是真实基因，图、表、数值全部自洽 —— 看的人没有任何办法发现。

**第 4 条独立可达，与脏值无关**（这才是本轮修的主因）：**这 5 个基因键都不按数据集作用域。** 在数据集 A 选好基因 → 打开缺该基因的数据集 B → B 原样恢复、立刻取数、静默画成别的基因。任何用户切一次数据集就会碰上。

### 修复

分三层，对应上面 1/2/3。

#### 存储层：键带上数据集路径

新增 `src/components/analysis/useStoredGene.ts`，键形如 `` `${baseKey}::${realPath}` ``，与既有先例 `gensci_free_msgs_${realPath}`（`FreeAnalysisTab.tsx:37`）同形。5 个消费方全部改用：

| 键 | 消费方 |
|---|---|
| `gensci_boxplot_gene` | `BoxPlotContainer.tsx` |
| `gensci_agg_gene` | `ExpressionChartContainer.tsx` |
| `gensci_gene_name` / `gensci_gene_name2` | `AnalysisPage.tsx`（UMAP 双基因） |
| `gensci_bulk_gene` | `BulkAnalysisTab.tsx` |

**旧的不带作用域的键一律不再读取** —— 存量脏值（包括用户那个 `CD3`）自然失效，不做迁移。迁移只会把污染搬进新键。

两个必须写下来的设计点，都是「只改键名」会踩的坑：

- **必须加「先认领槽位、再允许写入」的闸门。** `AnalysisPage` 换数据集时**不重新挂载子组件**（`realPath` 由 `[tissue,disease,pmid,attempt]` 的 effect 刷新，`AnalysisPage.tsx:77-103`），容器实例存活。此时写 effect 会带着**上一个数据集**的基因、按**新**路径写入新键 —— 把 A 的基因写进 B 的槽位。这比原缺陷更糟：原缺陷是「读到旧值」，这是「主动写入错误值」。
  闸门比对的是 **`storedGeneKey(baseKey, realPath)` 这个完整槽位，不是 `realPath`** —— 只比对路径的话，同一个数据集换框（baseKey 变）不会重新认领，旧框的基因会被写进新框的槽位，正是这个 hook 存在的意义所在。
  诚实交代可达性：**常规点路径走不到这个竞态** —— 进入分析页的路由来自 `TissuePage.tsx:348` / `SearchPage.tsx:182`，都是不同 route，`AnalysisPage` 会先卸载。真正能触发的只有**在同一 route 下回退/前进**（两个相邻的分析页 URL 之间）。也就是说闸门是**防御性的**，不是当前线上必然触发的。仍然加，原因有二：它是三行状态、不是架构；且「这一层不再可能出错」比「这一层今天恰好没错」更适合作为长期不变量。
- **UMAP 的基因初值在 `realPath` 还是 `''` 时就读了。** 若写 effect 在路径未知时落盘，会用 `''` 把存储**清空**。同一个闸门正好挡住（认领前不写）。

两点合起来意味着读/写必须成对且带状态 —— 所以在 4 个组件里各抄一遍是错的，抽成了 hook。

#### 展示层：后端回传它实际画的基因

`/api/plot`、`/api/composition-plot`、`/api/bulk/boxplot` 三个端点成功返回时新增 `gene_resolved`，前端在 Gene 框下方出一行警告：

```
⚠ "CD3" matched nothing here — showing "ABCD3" instead
```

- `resolvedGeneMessage(typed, resolved)`（`geneInput.ts`）是文案唯一来源；**纯大小写差异（`egfr` → `EGFR`）不出警告**，否则会教用户忽略这条真正重要的行。
- `gene_resolved` **可选**：`cachedFetch` 可能命中改动前缓存的响应（无该字段）。缺失 = 「后端没说」，前端一律按 `?? ''` 容错，不当作「发生了替换」。
- 警告状态存成 **`{asked, resolved}` 对**，渲染前校验 `resolution.asked === selectedGene`。只存 `resolved` 的话，`selectedGene` 一改，上一张图的结论会挂在新基因下面闪一帧错误警告。
- **`PlotImage` / Bulk 的取数加了「丢弃过期响应」的闸门**（这是代码评审抓出来的，不在初版方案里）。每次 `/api/plot` 是一次真实的 matplotlib 渲染，冷缓存要数秒；连点两个基因时，**先发的慢请求可能后到**，把旧图盖在新基因下面。而这个 `{asked, resolved}` 配对守卫会**因为 `asked` 对不上而选择沉默** —— 于是屏幕上是 COL1 的图、基因框写着 TP53、唯一能说明这件事的那行字被自己的守卫抑制掉了，正好是本缺陷的症状被自己的修复复现一遍。加 `let stale = false` + 清理函数，过期响应**整体丢弃**（图与它的结论一起），这个洞才真正关上。
- **composition 那条 fetch 不参与驱动警告**：它走的是 **exact-only** 解析 —— 同一个 `CD3` 在主图里被换成 `ABCD3`、在 composition 里直接报错。让它参与，会把主图刚设好的警告清掉。
- `plots.py:165` 的 `ax.set_title(gene, …)` 一并改为 `actual_gene`。改标题会**改变已有图的像素**（输入与规范名不同的场合），这是有意为之：给一张 ABCD3 的图打上 `CD3` 的标题，正好和新增的警告行自相矛盾。

#### 解析层：**不动**

子串回退原样保留（B28 已决定）。本轮只加回显，**不统一解析** —— 改动解析语义的风险高于本次修的缺陷，与 gene2_op 那轮「只统一标签、不统一解析」的决定一致。

### 验证

1. **TDD 顺序**：先跑出 RED 再实现。RED 两次：前端 `Failed to resolve import "./useStoredGene"` + `resolvedGeneMessage is not a function`；后端 `PASS 10 / FAIL 8`（8 个失败全是缺 `gene_resolved` 字段）。
2. **前端**：`npx vitest run` **112 passed (14 files)**（本轮前 103）；`npx tsc --noEmit` 干净。
   - `useStoredGene.test.ts`（新增 9 例）：旧裸键不被采用、A 数据集的基因在 B 下读不到、`realPath` 变化时采用 B **且不把 A 的值写进 B 的键**、路径未知期间不写入、`resolvedGeneMessage` 的四种输入。
   - `ResolvedGeneNotice.test.tsx`（新增 5 例）：**全部在测「该不该开口」**，包括「结论属于一个已经离开基因框的基因 → 沉默」这条守卫，以及「后端回显为空（改动前的缓存响应）→ 沉默」。本条是代码评审抓出来的：守卫是这个组件存在的全部理由，却一度没有测试。
   - `BoxPlotContainer.test.tsx` 新增 3 例、`BulkAnalysisTab.test.tsx` 新增 4 例（含「后端画的正是所要求的基因时保持静默」—— 防止警告变成恒显）。
3. **后端自包含脚本** `server/tests/test_gene_resolved_echo.py`：**22 / 0**。合成数据集 var.index 含 `ABCD3` 而**不含** `CD3`；另有第二个 fixture（`var.index` 是 Ensembl、符号在 `gene_symbols` 列）覆盖别名分支 —— 这是评审指出的**唯一新增逻辑行却零覆盖**的地方，加上它之后才暴露出上面的 `.iloc` 缺陷。其中两条专抓「只改了一个 return」：`bulk_boxplot` 的 panel 模式与 group 模式（group 分支是 `return _render_group_boxplot(...)` **直通**，只改顶层 return 的话，单疾病数据集——永远走 group 分支——拿不到字段，多疾病数据集能拿到，形成一个只在部分数据集上出现的缺口）。
4. **既有后端脚本不回归**：`test_gene2_op.py` 66/0、`test_gene_column_extraction.py` 26/0、`test_gene_search_rank.py` 9/9。composition 里把 `find_gene_idx` 重构为返回 `(idx, name)` 的 `find_gene` 后 gene2 语义逐字未变，由这 66 例背书。
5. **HTTP 端到端**（重启后端后实测）：

   ```
   GET /api/plot?…&gene=CD3&plot_type=boxplot  → gene_resolved: "ABCD3"   ← 用户报的那一例
   GET /api/plot?…&gene=CD3&plot_type=barplot  → gene_resolved: "ABCD3"
   GET /api/composition-plot?…&gene=ABCD3      → gene_resolved: "ABCD3"
   GET /api/bulk-boxplot?…&gene=COL1           → gene_resolved: "COL10A1"
   GET /api/bulk-boxplot?…&gene=TP53           → gene_resolved: "TP53"
   （端点名是 `/api/bulk-boxplot`，不是 `/api/bulk/boxplot`）
   ```

   `gene_resolved` 与输入不同的那三条，正是过去静默出图的场合。

### 未覆盖（明确留白）

- **UMAP 与 Bulk 的提交路径仍不设防**（本轮只修恢复路径）。Bulk 的静默替换会因回显而变得可见；**UMAP 不会** —— `/api/umap-data` 不在本轮回显范围内，其散点仍可能按别的基因着色。**这是本轮最大的已知缺口。**
- **解析逻辑分散在 7 处且行为不一致。** 初稿写的「4 处」是照着函数名数的，`grep -n "in n.lower()" server/analysis/*.py` 实测是 **6 份逐字相同的子串回退**（`utils.py:124`、`plots.py:54`、`bulk.py:50`、`expression.py:50`、`stats.py:53`、`stats.py:321`）加 `umap.py:49` 一个变体。行为分两类：多数是「精确→子串」，`plots._generate_celltype_composition`（`plots.py:235-243`）是**仅精确**。因此 BoxPlot tab 与 BarPlot tab 的 composition 图对 `CD3` 的判定依旧不一致（一个画图、一个报错）。**本轮只加回显，不统一。**
- **本轮自己引入过一个更隐蔽的错误（代码评审抓出，已修）：别名列取行写成了 `adata.var[col][i]`。** 那是 `Series.__getitem__`，收到整数键时**按标签**解释：pandas 2.x 只发 `FutureWarning`（当前行为仍按位置，结果碰巧正确），pandas 3.x 无条件按标签 —— 对 str 索引就是 `KeyError`，被外层 `except` 吞成 `{'error': ...}`，**整个 composition 端点在这类数据集上全挂**。只有 39/93 个数据集带别名列（`41740941.ACR.h5ad` 一个文件里就有 7,535 行是这样），随手一测碰不到。
  正确写法是 `.iloc[i]`，已改。**但要说清它今天为什么测不出来**：`anndata` 读写时会把整数 var index 强制转成字符串（`Transforming to str index`），所以「整数索引」这个形状**在 `.h5ad` 里根本不存在**，评审最初推演的 KeyError 路径实际不可达。今天唯一可观测的差异就是这个 `FutureWarning` —— 测试因此断言「不发出位置式取用的告警」，而不是断言返回值（两种写法返回值相同）。**变异验证**：改成 `[i]` → 该用例失败；改回 `.iloc` → 通过。
  教训：**返回值相同的两种写法，只能靠副作用（告警/异常/日志）区分。** 测不出来 ≠ 没差别，要先回答「哪个可观测信号能区分它们」。
- **`_generate_celltype_composition` 的回显取的是「命中的那个值」，不是 `adata.var.index[g1_idx]`。** 该函数除 `var.index` 外还会匹配 `gene_ids`/`gene_symbols`/`feature_name` 列，而命中这些列时行标签可能是 Ensembl ID —— 顺着行标签回显会报出一个用户从没打过的名字，而前端「resolved ≠ asked 就警告」的规则会把一次**完全正确的命中**报成警告。与 `_generate_plot` 以 `var.index` 为准的写法**有意不一致**，因为后者只有一条解析路径。
  由此带来一处**同一响应内两个名字不同**：请求同一个基因，作为主基因时回别名、作为 gene2 成员时回 `var.index`（`plots.py:269/297` 未动，保持原契约）。这是有意的折中 —— 统一成任意一边都会错（统一成行标签 = 对别名数据集产生假警告；统一成别名 = 改 gene2 的既有契约）。**该字段目前没有任何前端消费方**（composition 那条 fetch 不驱动警告行），所以这个不一致只影响 API 消费者。
- **Bulk 其余 8 个已持久化选项**（disease / palette / xFactor / hiddenGroups 等）仍未按数据集作用域，本轮只处理基因键。
- `ExpressionChartContainer` —— **用户报的现象就发生在这里** —— 至今没有组件测试。本轮把恢复路径的回归测试加在了 `BoxPlotContainer.test.tsx`（它有现成的 mock 设施），该缺口**未关闭**。
- **`npm run lint` 根本跑不了：仓库里没有 `eslint.config.*` 也没有 `.eslintrc*`**（ESLint 10.5.0 直接 exit 2）。这是既有问题，但对本轮有直接后果：`react-hooks/exhaustive-deps` **从未运行过**，而它正是唯一能挡住「往 `PlotImage` 传一个非稳定 `onResolvedGene`」的规则 —— 那种写法会导致每次渲染都重新取数。当前三个调用方的 `useCallback` 都是稳定的，但没有任何机制保证以后也是。CLAUDE.md 把 `npm run lint` 列为常规命令，实际上它一直是个空操作。
- `PlotImage` 自身仍无测试文件，`onResolvedGene` 的协议（请求开始时回 `''`、成功时回 `gene_resolved`、失败时不调用）由调用方测试间接覆盖，未直接验证。
- **存储无界增长**：每个访问过的数据集 × 5 个基因框各写一个键，且即使用户从未选过也会把默认值（`FAP`/`TP53`）写进去；旧的不带作用域的键也从不清理。`sessionStorage` 满时 `setItem` 抛 `QuotaExceededError`，而 `catch {}` 会**静默**把持久化关掉 —— 用户看到的是「基因框又不记得我的选择了」，日志里什么都没有。
- 警告行渲染在 `div.relative` 内（它就是下拉建议的定位锚点），所以**建议下拉会盖住警告行**。纯视觉问题，未改。
- 本轮**没有浏览器端到端验证**：Playwright 的 chrome 可执行文件不在标准位置，未安装。上面第 5 条是 `curl` 级别的端点验证 + 组件级测试，不等价于真跑一遍 UI。
- `docs/BUG_LOG.md` 的「附录：修复清单总览」**只到 B18**，B19–B33 全缺；B33 标题里「10 处」与正文「8 次」两处失真；`core/adata_cache.py:69` 的 LRU 淘汰竞态 —— 均未处理。

### 涉及文件

- `src/components/analysis/useStoredGene.ts`（新增）+ `.test.ts`
- `src/components/analysis/ResolvedGeneNotice.tsx`（新增）+ `.test.tsx`
- `src/components/analysis/geneInput.ts`（+ `resolvedGeneMessage`）/ `.test.ts`
- `src/components/analysis/PlotImage.tsx`（`onResolvedGene` 回调）
- `src/components/analysis/{BoxPlotContainer,ExpressionChartContainer,BulkAnalysisTab}.tsx`、`src/pages/AnalysisPage.tsx`
- `src/api/types.ts`（`PlotResult.gene_resolved?`）
- `server/analysis/plots.py`（`_generate_plot`、`_generate_celltype_composition`）
- `server/analysis/bulk.py`（`_render_group_boxplot`、`bulk_boxplot` 两处 return + docstring）
- `server/tests/test_gene_resolved_echo.py`（新增）
- `server/routes.py` **未改** —— 三个 handler 都是把 dict 原样 `_json` 出去，新增键天然透传。注意 `_plot_cache` 是**进程内** LRU，**必须重启后端**才会清掉不带新字段的旧条目。

### 关键教训

- **守卫加在「入口」上是不够的，只要还有第二个决定「发什么请求」的地方。** B28 封的是「用户打字」这条入口，而真正决定发哪个基因的还有「从存储恢复」和「UMAP/Bulk 的裸 onChange」。**数入口要数列举状态来源，不是数列输入框。**
- **持久化状态必须和它所描述的对象同作用域。** 一个全局键存一个数据集相关的值，等于默认「所有数据集共享同一套基因」—— 这个假设从未成立过。
- **加作用域时，要问「谁还会写这个键」。** `AnalysisPage` 不重新挂载这一点，让「只改键名」从「修复」变成「引入新的写坏路径」。**改存储的作用域 = 改一个分布式状态机**，读和写必须一起看。
- **静默替换和「未找到」一样危险，因为前者更可信。** `CD3 → ABCD3` 出的是真实基因、真实数值、正常图表；`NOTAGENE` 至少会报错。**能让用户怀疑的前提是他知道自己看的不是自己要的东西** —— 这就是为什么 `gene_resolved` 必须回传，而不是顺手把子串回退关掉。
- **「不确定就沉默」会把不确定本身藏起来。** `{asked, resolved}` 配对守卫的本意是不显示错误警告，但它同时也**抑制掉了「屏幕上的图不知是谁的」这条信息** —— 一旦有过期响应抵达，用户得到的是错误的图 + 空白的警告行。**守卫的沉默必须建立在「没有歧义」之上，而不是「有歧义所以不说」之上**；过期的答案要走并发控制（丢弃），不能走展示逻辑（沉默）。（本条由代码评审发现，不在初版方案里。）
- **本轮没有真跑一遍浏览器。** 记在这里，免得下一轮把「curl 通过 + 组件测试通过」误当成「UI 验过了」。

---

## B35. 摘要把整个「点进数据集」页面拖垮；顺带查出 scanner 快路径从未生效 (2026-09-20)

### 现象

用户原话：

> 为什么32832599 这个数据，点进去 Failed to load info / Go Back

点进 `32832599.IPF.h5ad` 的分析页，等一段时间后整页变成错误屏 —— 只有一句 `Failed to load info` 和一个 `Go Back`。**stats（细胞数/基因数/样本数）本来早就拿到了，也一起丢了。**

### 根因

#### 1. 主因：`/api/analysis-info` 同步调外部抓取，且这次抓取**没有总时限**

`handle_analysis_info`（`routes.py:187`）在冷缓存时同步执行 `pubmed._fetch_abstract(pmid)`，后者要经公司代理发 **3 次**外部 HTTP（EuropePMC ×2 + NCBI PMC 全文 ×1）。旧代码的超时是**写死的单次 socket 超时**：

```
_proxy_opener.open(req, timeout=8)    # EuropePMC 第 1 个候选 URL
_proxy_opener.open(req, timeout=8)    # EuropePMC 第 2 个候选 URL
_proxy_opener.open(req, timeout=10)   # PMC 全文 XML
```

`urllib` 的 `timeout` 是**单个 socket** 的超时，不是整次请求的墙钟上限。代理「连得上、但很慢」时它会一直慢慢吐数据，每次调用都能把 8 秒用满 —— `8+8+10` 只是理论下界，不是上界。

在一个**全新进程**上做冷启动实测（多数据集样本）：

```
124.83s  40112801.Blood.AIDA.h5ad
 67.99s  38548990.ILD.h5ad
 29.01s  39438660.IBD.h5ad
  4.09s  32832599.IPF.h5ad      ← 用户报的那条；在已退化的旧进程上是 104s
```

前端 `apiFetch` 的默认 `timeoutMs = 60_000`（`src/api/client.ts:4`）到点 abort → `.catch` 把 `setError('Failed to load info')`（`AnalysisPage.tsx:116`）。服务器 100 秒后才 `_json(result)`，对端早已断开 → `BrokenPipeError`（`routes.py:243` → `handler.py:82`）。

**单看这三条时间不足以定罪。** 当时我用「响应快到不可能是读了 h5ad」把「读数据慢」这条排除了 —— 见下面第 2 条，这个理由其实是错的。

#### 2. 并存的第二个缺陷：scanner 快路径**从来没生效过**

`routes.py:209`：

```python
if str(real_path) in k or k.endswith(str(real_path).name):   # ← 对**字符串**取 .name
```

`str(real_path).name` 在字符串上取 `.name` → `AttributeError`。而外层是：

```python
    except Exception:
        pass          # ← 一个字都不留
```

于是：**遍历到任何一个不匹配的 key 都会抛异常，直接跳到 `except`**，`stats` 保持 `None`，然后走「读整个 h5ad」的兜底分支。线上 104 个数据集，正确的 key 前面永远排着别人，所以这条为「不读 h5ad」而写的快路径**一次都没有命中过**。

`Path.resolve()` 会跟随符号链接，所以 `real_path.name` 一度被怀疑是链接目标名 —— **不是**：`validate_real_path` 显式返回**未解析的原始 Path**（`routes.py:69-87`，注释写明「Checks the original path (not resolved symlink target)」），所以 `real_path.name == '32832599.IPF.h5ad'`，与 scanner 缓存的 key 逐字吻合。

这条缺陷是在**修主因的过程中**被发现的：把 `except: pass` 换成 `print(..., file=sys.stderr)` 之后，第一行日志就是

```
[GenSci] scanner cache lookup failed for .../32832599.IPF.h5ad: 'str' object has no attribute 'name'
```

修好之后，同样三个数据集的 `/api/analysis-info`：**6.21s → 0.01s、1.65s → 0.01s、1.02s → 0.01s**，且 `cells` 逐一与读 h5ad 得到的值相同（243472 / 450465 / 1265624），说明快慢两条路径结果一致。

#### 3. 前端：慢的那个字段把快的那些一起拖下水

`abstract` 和 `stats` 挤在同一个响应里。stats 走本地 scanner 缓存是**毫秒级**，abstract 要过代理是**秒到分钟级** —— 合并成一个响应，等于让最快的数据陪最慢的数据一起等，且超时后**两者全丢**。这不是「摘要显示不出来」的小问题，是**页面根本打不开**。

### 修复

**拆端点**：`/api/analysis-info` 变成纯本地（只读进程内已缓存的摘要），摘要由新端点 `/api/abstract` 按需抓。

- **`server/config.py`** 新增 `ABSTRACT_DEADLINE_S = 20` —— 整次抓取的墙钟上限。
- **`server/pubmed.py`**
  - `_fetch_abstract(pmid, deadline_s=None)`：`time.monotonic()` 起算，每个 `open()` 拿到的是 `min(剩余预算, 单次上限)`；**预算耗尽就不再发下一个请求**。两处新增常量 `_PER_CALL_TIMEOUT_S = 8` / `_PMC_TIMEOUT_S = 10` 现在只决定「别让一次调用占满全部预算」，不再是整次请求的上界。
    > ⚠️ **这句在写下的当天就被证伪了** —— 它只对「请求之间」成立，对「一次请求内部」不成立。见下方「补记」。真正的上限由 `_read_bounded()` 提供。
  - 新增 `cached_abstract(pmid)`：**只读**缓存，绝不发网络，给 `/api/analysis-info` 用。
  - 缓存策略补上第七条不写路径：`incomplete = (pmc_error and not info['methods']) or pmc_skipped`。B26 的「失败不缓存」原样保留（`pmc_error` 那半条逐字未动），新增的是 `pmc_skipped` —— 预算在 EuropePMC 阶段就烧光时，PMC 全文压根没发出去，这份记录是**残缺**的。若缓存它，前端拿到 `abstract_ready=true` 就再也不会重取，methods 与补充材料清单**永久缺失** —— 正是 B26 那个坑的另一种走法。
  - `except Exception: continue`（EuropePMC 候选循环）→ 记 `type(e).__name__` 与 URL 后 continue。原先这个失败在日志里**一个字都没有**，上层只看到一个空记录，分不清「查无此文」和「网络挂了」。
- **`server/routes.py`**
  - `handle_analysis_info` 去掉网络调用，响应新增 `abstract_ready: bool`。
  - 缓存出栈时与摘要缓存对一次：`ready = cached_abstract(pmid)`，拿到了就把 `{**cached, 'abstract': ready, 'abstract_ready': True}` 写回。不加这一步的话 `_analysis_info_cache` 会把 `abstract_ready=false` **钉死到进程结束**，前端每次访问都白跑一次 `/api/abstract`。（**这一条是测试逼出来的** —— 见下面「验证」第 1 点。）
  - 新增 `handle_abstract` + `('GET', '/api/abstract')` 路由。抓取失败返回 **200 + `abstract_ready: false`**，不是 500：页面其余部分（stats）是好的，摘要是可降级的补充，5xx 会诱导前端把它当成整页失败。
  - `except Exception: pass` → 记日志。**就是这一条让上面第 2 个缺陷现形。**
  - `k.endswith(str(real_path).name)` → `k.endswith(real_path.name)`。
- **前端**
  - `AnalysisPage.tsx` 第二个 effect：`needsAbstract = info != null && info.abstract_ready !== true`，命中就单独 `fetchAbstract(pmid)`，回来后用不可变合并写进 `info`；**`.catch` 是空的** —— 摘要失败不许碰页面级 `error`。
  - `fetchAbstract` 用 `apiFetch(url, undefined, 30_000)`，不共用 60s 默认值。后端硬上限 20s，留一倍余量；沿用 60s 等于把「超时给得太宽」这个成因留在原地。
  - `AbstractInfo | null`（`abstract` 由非空变可空）+ 新增 `AbstractResponse`；`InfoPanel` 全部解引用加守卫，并区分**「还在取」**（转圈）与**「取回来是空的」**（`Abstract not available`）—— 只判空的话，取摘要那几百毫秒里会有一瞬间在谎称「这篇没有摘要」。

### 验证

1. **TDD 顺序**：先 RED 后 GREEN。RED 是 `TypeError: _fetch_abstract() got an unexpected keyword argument 'deadline_s'`（退出码 1）。新增 `server/tests/test_analysis_info_nonblocking.py`，**15 条断言全过**，全程 monkeypatch、不发真实网络请求。
   GREEN 之后仍有 **2 条 FAIL**，暴露的是初版方案的真实缺陷：`_analysis_info_cache` 把 `abstract_ready: false` 钉死了（就是我一开始想「YAGNI 跳过」的那个刷新分支）。测试是对的，加上了。
2. **新测试里真正抓得住 bug 的一条是后来补的**：`[3]` 的假 scanner 缓存**只有一个 key，而它恰好就是被查的那个** —— `str(real_path) in k` 一短路，`k.endswith(...)` 根本不求值，于是它**在改前就是 PASS 的**，完全掩盖了第 2 个缺陷。补了 `[3b]`：把不匹配的条目**排在最前**，复现线上真实形态。**变异验证**：`sed` 改回 `str(real_path).name` → 该条 FAIL（`实际 0`，即退化到读空 h5ad 的兜底返回）；改回 → PASS。
3. **前端**：`npx vitest run` **152 passed (16 files)**（本轮前 149，新增 3）；`npx tsc --noEmit` 干净；`npm run lint` 干净。
   新增的 3 条在 `AnalysisPage.test.tsx`：摘要**永不 resolve** 时页面照常打开、摘要 **reject** 时页面照常打开、以及**正对照** —— stats 自己失败时**必须**出错误屏（没有这条，前两条在「页面干脆不再报错」的实现下也会通过）。
   同时补了 `vi.mock('../api/analysis')` 缺的 `fetchAbstract`：Vitest 的模块 mock 是全量替换，页面新调用的函数不在 mock 里会直接抛错（实测 `Test Files 1 failed`）。
4. **既有后端自包含脚本不回归**：14 个脚本全 PASS（`test_supplementary_parse`、`test_coexpression_table`、`test_drug_stages`、`test_drug_pipeline_events`、`test_handler_post_routes`、`test_results_dir`、`test_pipeline_resilience` 等）。
5. **HTTP 端到端**（重启后端后实测，三个数据集）：
   ```
                      /api/analysis-info      /api/abstract     再次 analysis-info
   32832599.IPF          0.01s (原 104s/4.09s)     3.40s        0.00s, ready=True
   38548990.ILD          0.01s (原  67.99s)        2.88s        0.00s, ready=True
   40112801.Blood.AIDA   0.01s (原 124.83s)        1.72s        0.00s, ready=True
   ```
   `scanner cache lookup failed` 在后端日志里从「每次都出现」变成 **0 条**。
6. **浏览器端到端真跑了**（`playwright-core` 驱动本机 chromium，无 DISPLAY 故用 headless；注意本会话应使用 `playwright` MCP，ECC 自带的那个在本机因找不到系统 Chrome 而不可用）：
   ```
   32832599.IPF       tab 出现 336ms，摘要 443ms，无错误屏，stats 显示 243.5K，无 console/page error
   40112801.AIDA      tab 出现 315ms，无错误屏，stats 正常，无 console/page error
   ```
   修复前用户看到的 `Failed to load info / Go Back` 在两次运行中都没有出现（`go_back` 按钮计数为 0）。
7. **一次诚实的踩坑记录**：第一次浏览器验证报 `abstract_title_ms: null` + `Abstract not available`，我一度以为是新代码的问题。实际是**两个各自独立的假象**：
   - `playwright` 的 strict mode —— 标题同时出现在顶栏和 `h4` 两处，`getByText` 匹配到多个元素直接抛错，被我自己 `try/catch` 吞成了 `null`。换成 `locator('h4', {hasText})` 后正常。
   - 那一次**恰好**赶上冷缓存下 EuropePMC 抓取失败，后端按 B26 策略**不缓存**，页面如实降级成 `Abstract not available`（这正是设计行为）；几秒后同样的请求就成功了。**是这次留下的日志缺失（上面新增的 EuropePMC 失败留痕）让这次失败变成不可解释**，所以才补了那条 stderr。

### 补记：第一版修复没修住，是代码评审揪出来的（2026-09-20 当天，同一轮内）

按 CLAUDE.md 第 4 阶段跑了两个语言评审（`ecc:python-reviewer`、`ecc:typescript-reviewer`），**各报一个 HIGH，且都是「第一版加的防护在真实故障形态下不成立」**。两条都经我独立复现确认，已修。

#### 1. [HIGH] 「总时限」是假的 —— 预算管得住「几次请求」，管不住「一次请求内部」

这是我第一版最要命的地方，也是最讽刺的地方：**我为了修「per-socket 超时管不住总时长」而加的预算，本身也只作用在请求之间。**

`urllib` 的 `timeout` 是**单次 socket 操作**（connect + 每次 recv）的超时。`resp.read()` 会一直 recv 到 EOF，而对端只要慢到「每个 recv 间隔内吐得出一个字节」，超时就永远不触发 —— `min(budget, 8)` 那个约束完全落空。**B35 记录的 125s 正是这个形态**，也就是说第一版没修住它自己引用的那个案子。

实测（本地滴流服务器：`Content-Length: 60`，每秒吐 1 字节，`_proxy_opener` 重定向到本地）：

```
改前：deadline_s=2 → 59.07s   deadline_s=3 → 59.07s   deadline_s=5 → 59.07s
改后：deadline_s=2 →  2.00s   deadline_s=3 →  3.00s   deadline_s=5 →  5.01s
```

**三个预算跑出同一个 59.07s** —— 预算参数对结果完全没有影响，这就是「不是上限」的铁证。

修复：`_read_bounded(resp, remaining)` —— 用 `resp.read1(chunk)` 保证每次只消费一次 recv，**每次 recv 之间查预算**，耗尽就返回 `None`（body 不完整）。EuropePMC 与 PMC 两处 body 读取都改走它；读不完一律按失败处理（不写缓存）。新增上限常量 `_MAX_BODY_BYTES` 防止无上限 body 撑内存。
**诚实标注**：最坏超时 = 剩余预算 + 一次 socket 操作（≤8s），因为掐表那一刻的 recv 已经在飞、收不回来。所以服务端上界是 28s，前端 30s 仍留了余量 —— 但不等于「正好 20s」。

#### 2. [HIGH] 前端把「取不到」说成了「这篇没有摘要」，而且**没有重试**

`AnalysisPage.tsx` 的 `.catch(() => {})` 是空的，失败后 `abstract_ready` 仍是 `false`、`needsAbstract` 依赖没变、effect 不会重跑 —— 用户看到的是「Abstract not available」（一个关于论文的**事实断言**），而且**没有任何办法重试，只能刷新整页**。服务端本来就按「失败不缓存、下次请求重试」设计（B26），前端把这个机会整个丢掉了；同一轮里后端 `except` 都补了留痕，前端反倒新增了一个静默 `catch`。

修复：`abstractError` 状态 + 「摘要暂时取不到（外部文献库超时或限流）· 重试」按钮（`retryAbstract` 走 nonce 触发 effect 重跑）。

#### 3. [MEDIUM] `abstractPending` 由 effect 里 set 的标志推导 → 每轮冷加载先闪一帧假话

`abstractLoading` 是在 effect **内部** set 的，而 effect 在 commit 之后才跑。所以每次冷加载都会先渲染一帧 `abstractLoading === false && !abstract` → 显示「Abstract not available」—— 正是那段注释声称已经消除的谎话。

修复：**删掉 `abstractLoading` 这个状态**，三种状态全部由数据推导：
```tsx
const abstractMissing   = abstract == null || (!abstract.title && !abstract.abstract)
const abstractPending   = info.abstract_ready !== true && abstractMissing && !abstractError
const abstractUnavailable = info.abstract_ready !== true && abstractMissing && abstractError
```
顺带消掉了「`if (!cancelled)` 守着的唯一一次复位被跳过 → 标志永久卡在 true」这个潜在路径 —— 标志没了，路径也就不存在了。只有 `abstract_ready === true` 且内容为空才说 not available，那才是服务端在说「这就是全部」。

#### 4. [MEDIUM] 代理拦截页被当成「已获取全文」

`xml_ok = True` 原先的含义是「`read()` 返回了」，不是「body 是文章 XML」。代理拦截页 / 限流页 / eutils 的 `<error>` 文档**全是 HTTP 200**，于是「这次没抓成」被缓存成「这篇确实没有补充材料」并当事实讲给用户 —— 与 B26 的「失败不要伪装成成功」直接冲突，而且就发生在本轮重写的那些行里。

修复：`if '<article' not in xml_text[:8192]: raise ValueError(...)` → 走 `pmc_error` 分支，不缓存。已验证真实 PMC 不受影响（`PMC7439502`：methods 28440 字符、15 个补充材料）。

#### 5. [MEDIUM] `abstract_ready` 有两个互相矛盾的定义

`/api/analysis-info` 用 `cached_abstract(pmid) is not None`，`/api/abstract` 另算 `bool(title or abstract or pmcid)`。全文因预算被跳过时，一个说 ready、另一个说 not ready；前端拿着 `ready=true` **永久不再重取**，Methods 与补充材料清单就永久缺失 —— 恰好是本轮特意加 `pmc_skipped` 想防住的那件事，被另一个端点从侧面捅穿了。

修复：判据收敛成一个 —— **「在摘要缓存里」**（`_fetch_abstract` 只在记录完整时才写缓存，所以「在缓存里」== 「服务器认为这是最终答案了」）。两个端点现在共用它。

#### 6. 其余同批修掉的

- `handle_abstract` / `handle_analysis_info` 的 `pmid` 统一 `.strip()`：`'12345 '` 会拼进 URL 也当缓存键，让一个**输入问题伪装成网络问题**。
- `validate_real_path` 的 `except Exception: return None` 补留痕。这是 `handle_analysis_info` 调用链上**最后一处静默**，就在被打开的那处上方 100 行。B35 主因那条教训（去掉静默 → 揪出从未生效的代码）在这里是同一个手法。
- 评审同时指出 `str(real_path) in k` 是**子串**匹配而非相等，且 `k.endswith(real_path.name)` 现在从「死代码」变成了**活代码**。查了线上 `.scanner_cache.json`：104 个 key、0 个 basename 重复，所以是潜在而非现实风险。本轮未改成精确相等 —— 记在「未覆盖」里。
- `CLAUDE.md` 的路由表把 `/api/analysis-info` 描述为「Dataset abstract + stats」，已不准确。（**未改**，与计划文件里的文档改动一起做更合适。）

#### 7. 评审反过来说对了我一个错误做法：两条「假测试」

- 后端：`[3]` 的假 scanner 缓存只有一个 key 且恰好命中，`str(real_path) in k` 一短路，第二条件根本不求值 —— **两个缺陷都在时它照样 PASS**。（这条上一版已经自己发现了，补了 `[3b]`。）
- 但**同一种病我在这轮又犯了一次**：新写的 `[1]` 断言的是「传给 opener 的 timeout ≤ 总预算」。滴流响应**恰恰满足**这条断言（代码确实把 timeout 传小了），却能跑满 59 秒。断言看的是「传下去的参数」，不是「实际花掉的墙钟」。
  补了 `[1b]`：假时钟 + 滴流响应（`read1` 每次推 0.4s 吐 1 字节），断言 **`read1` 调用次数有限**。变异验证 `read1 → read` → `FAIL 实际 10000 次`。
- 还有一个更隐蔽的：新写的「非 XML 200 不被当作全文」那条，**第一次是空过的** —— 旧的 `_Resp` 假响应没有 `read1`，欧洲PMC 阶段直接 `AttributeError`、被吞成「抓取失败」，`epmc_hit` 从未置位，断言 `note != 'none'` 于是自动成立。给 `_Resp` 补 `read1` 后才真正测到。变异验证（删掉 `<article` 检查）→ 2 条 FAIL。
- 前端：`AnalysisPage.test.tsx` 把 `InfoPanel` 整个 mock 成 `() => null`，**全仓库没有第二个文件渲染它**，于是本轮修复「用户看得见的那一半」覆盖率是 0 —— `abstractError` 和重试按钮整段删掉，152 条测试全绿。补了 `InfoPanel.test.tsx`（5 条）与页面级的「请求确实发出去了 / 不会循环重取」2 条。变异验证：把 pending/unavailable 不再由 `abstract_ready` 推导 → 3 条 FAIL；忽略 `abstractError` → 1 条 FAIL；把 `info` 加进 effect 依赖数组（人为造无限循环）→ 循环那条 FAIL。

#### 8. 我自己在排查里栽的两个跟头（比缺陷本身更值得记）

- **第一版复现脚本跑了两次都「PASS」，两次都是无效实验。** 第一次用 `build_opener()` 且**候选 URL 仍指向 ebi.ac.uk** —— 请求压根没到本地服务器；第二次以为绕开了代理，其实还是直奔真实 EuropePMC，还拿回了一条真记录（`Optical study of niobium disilicide...`）却当成「本地滴流没超时」。**是 `hits=[]` 这个我自己加的计数暴露了它** —— 只要我少打一行调试输出，就会拿着一个 PASS 去否定评审的 HIGH。教训：复现脚本必须证明「请求确实走到了被测的那条路上」，否则它与「什么都没测」不可区分。
- **评审给的 7.01s 和我后来的 59.07s 不是一回事，但结论一致。** 数字对不上时不要急着判定谁错 —— 两次都是真的，只是假服务器的吐字节节奏不同。

#### 9. 补记后的实测（重启后端后重跑）

```
                             /api/analysis-info      cells
 32832599.IPF.h5ad                 0.002s          243472   （原 104s）
 32832599.COPD.h5ad                0.002s          165759
 38548990.ILD.h5ad                 0.005s          450465   （原 67.99s）
 40112801.Blood.AIDA.h5ad          0.008s         1265624   （原 124.83s）

                             /api/abstract           methods  supp   note
 32832599                          1.9ms(已缓存)      28440    15
 38548990                          3.44s              16954     4
 40112801                          1.71s                  0     0   'no-pmcid'

 /api/abstract?pmid=<纯空白>  →  HTTP 400（strip 后为空）
 /api/abstract?pmid=PKU001    →  200，空记录并缓存（非 PubMed ID，没有可查的东西）
 后端日志 scanner cache lookup failed / validate_real_path failed  →  0 条
```

同 `pmid` 但不同 basename 的两个数据集（`32832599.IPF` / `32832599.COPD`）stats 分别是 243472 / 165759，**没有串** —— 这是对 basename 回退那条守卫的直接检验。

**浏览器端到端**（`playwright-core` + 本机 chromium，headless）：
```
[正常路径] tab=337ms  abstract_title=3687ms  stats=true  go_back=0  failed_screen=0
[失败路径] 用 route.abort() 掐断 /api/abstract：
           拦截=1  重试按钮=出现
           谎称 "Abstract not available" = 0
           stats 仍在屏幕上 = true
           整页错误屏 = 0   go_back = 0
[重试]     点击后 3370ms 真的取回了摘要
```
失败路径这条是**第一版做不到的**：以前掐断 `/api/abstract`，用户看到的就是「Abstract not available」并且无从重试。

**回归**：`npx vitest run` **159 passed (17 files)**（本轮新增 7 条：InfoPanel 5 + 页面 2）；`npx tsc --noEmit` 干净；`npm run lint` 干净；后端自包含脚本 **14/14 PASS**（按退出码判定）。

### 未覆盖（明确留白）

- **两处评审意见本轮明确未修，留给后续：**
  - **`_EUROPE_PMC_CACHE` 是无界 dict，且新端点让写入变得廉价。** `caches.LRUCache` 是本项目既定模式，这里没用。更要紧的是：`/api/abstract?pmid=xxx` 现在**零网络、无 `real_path` 校验**就能写一条缓存（改前写一次需要合法数据集路径 + 一次慢速外部抓取）。目前只有 per-IP 100 req/60s 限流。本轮未改成 LRU、也未拒绝非数字 pmid —— 因为非 PubMed 数据集（PKU/BALF）本来就走这条路。
  - **预算耗尽导致的「残缺记录」永久不可缓存。** `pmc_skipped` 被当成失败处理，于是坏代理日里某个 pmid 每访问一次就要重发 2 次 EuropePMC + 1 次 PMC。这是 B26 的保守方向（宁可重试也不缓存残缺），**但代价是真实的**：正确的做法是把 EuropePMC 部分与 PMC 全文分开缓存、再加 per-pmid 单飞去重，属重构，本轮没做。
  - **`k.endswith(real_path.name)` 的 basename 回退**现在从死代码变成了活代码（子串匹配 `str(real_path) in k` 也仍在）。线上 104 个 key 无重复 basename，属潜在风险。
- **`ABSTRACT_DEADLINE_S = 20` 是拍板值，不是测出来的。** 依据是多数样本落在 4~14s —— 20s 能让绝大多数请求拿到完整记录，代价是最坏情况多等 20 秒。**但本轮实测的三次 `/api/abstract` 都在 3.4s 以内：预算耗尽这条分支在真实代理上从未触发过**，只在假时钟 + 假滴流响应下验证过（补记第 7 条）。真实高延迟日会走到哪一支、最多等 28 秒用户能否接受，都还不知道。
- **服务端最坏 28s 与前端 30s 之间只隔 2 秒。** 28s = `ABSTRACT_DEADLINE_S`(20) + 一次 socket 操作(≤8)。这两个数字分别写在 Python 和 TypeScript 里，**没有任何东西把它们绑在一起**：把 `ABSTRACT_DEADLINE_S` 调到 25，前端就会抢跑 abort，而客户端 abort 是更坏的结果（没有结构化回答、没有错误原因，见补记第 2 条）。
- **`_analysis_info_cache` 与 `_EUROPE_PMC_CACHE` 的一致性只在读路径上对齐。** 摘要在 `/api/abstract` 里被抓进来后，只对**之后**的出栈生效；已经在 `_analysis_info_cache` 里的条目要在下次请求时才刷新。功能上没问题（前端拿到的值是对的），但「两个缓存谁说了算」没有单一真相源。
- **`_fetch_abstract` 的 EuropePMC 候选循环里，真正的失败原因仍然只能看 stderr。** 本轮补了日志，但没有把这个信息透到 API 响应里 —— 前端依然分不清「这篇确实没摘要」和「这次没抓到」。
- **`/api/abstract` 没有并发去重。** 同一 pmid 被 N 个浏览器同时请求（或同一用户快速刷新）会发 N 次外部抓取。`ThreadingHTTPServer` 下这不是安全问题，但会放大代理压力。当前规模（内网、少用户）不值得加锁，写在这里免得以后当成「已经处理过」。
- **`get_adata()` 兜底分支依旧是无限时的。** `/api/analysis-info` 在 scanner 缓存缺失时仍会读整个 h5ad（Tabula Sapiens 那种文件实测 >240s）。本轮把它从「每次必经」降级为「只在 scanner 缓存真的缺失时」—— **但没有给它加上时限**。同一个页面、同一种失败模式，只是触发条件变得罕见得多。
- **本轮的 0.01s 掩盖了一件事**：scanner 缓存里存的是扫描时刻的快照。修好快路径之后，stats 现在**总是**来自这份快照，不再有机会被 h5ad 实读纠正。快照过期（文件被替换、扫描器 30s 周期未到）时会显示旧数字 —— 这是快路径本来就有的语义，不是本轮引入的，但本轮把它从「几乎不发生」变成了「总是发生」。
- **`/api/analysis-info` 的 `abstract_ready` 是可选字段**（`abstract_ready?: boolean`），前端按 `!== true` 判定。旧的缓存响应里没有这个字段，会被当成「需要再取一次」—— 这是有意的保守方向，但意味着**字段缺失时永远多发一次请求**。
- 浏览器验证覆盖了 2 个数据集 × 1 条路径（直接 URL 进入 Study Info tab）。**没有覆盖**：切数据集、前进/后退、快速连点导致摘要请求交叉、以及在摘要仍在飞行时切走 tab。
- **唯一的运行期观察无法解释**：其中一次实例的 `VmHWM` 到过 66.5 GB，另一次同样负载下只有 6.65 GB。**没有查到原因，也没有证据表明与本轮改动有关**（改动只减少了外部请求与 h5ad 读取）。记在这里，不作结论。

### 涉及文件

- `server/config.py`（`ABSTRACT_DEADLINE_S`）
- `server/pubmed.py`（`_fetch_abstract` 总时限、`cached_abstract`、`pmc_skipped`、EuropePMC 失败留痕）
- `server/routes.py`（`handle_analysis_info` 去网络化 + 摘要缓存回填、`handle_abstract`、`/api/abstract` 路由、`str(real_path).name` → `real_path.name`、两处 `except` 留痕）
- `src/api/types.ts`（`AnalysisInfo.abstract` 可空、`abstract_ready?`、`AbstractResponse`）
- `src/api/analysis.ts`（`fetchAbstract`、`ABSTRACT_TIMEOUT_MS`）
- `src/pages/AnalysisPage.tsx`（第二个 effect + `abstractLoading`）
- `src/components/analysis/InfoPanel.tsx`（可空 `abstract`、`abstractLoading`、转圈/空态分离）
- `src/pages/AnalysisPage.test.tsx`（补 `fetchAbstract` mock + 3 条回归，补记再加 2 条）
- `src/components/analysis/InfoPanel.test.tsx`（**补记新增**，5 条 —— 该组件此前被 mock 成 `null`，全仓库无测试）
- `server/tests/test_analysis_info_nonblocking.py`（新增，**19 条断言**）

### 关键教训

- **「超时」这个词必须问清是哪一个：单次 socket 超时 ≠ 整次操作的总时限。** `8+8+10` 看起来像个上界，实际只是个下界 —— 串行 N 次带超时的调用，任何一次「连得上但很慢」都能把总时长撑到任意大。写超时的时候要连着写**预算**，不是给每一步各配一个 timeout 就完事。这条和 B32（`_stream_sse` 的重试）是同一类错误的两面。
- **两个时延差三个数量级的字段，不该挤在同一个响应里。** 这不是性能优化，是**可用性设计**：合并它们，等于让快的数据陪慢的数据一起超时，超时后**全丢**。判据很简单 —— 只要一个响应里有两个字段的合理时延差了一个数量级以上，就该拆。
- **`except Exception: pass` 会把「从来没能生效的代码」伪装成「一直在正常工作的代码」。** scanner 快路径的 `AttributeError` 被吞了不知道多久，表现出来只是「这一页有点慢」—— 慢到能被归因成网络、磁盘、数据太大，唯独不会被归因成一行取错属性的代码。**去掉一个 `except: pass` 的成本是三行，收益是这一整类 bug 从不可见变成可见。**（CLAUDE.md 设计决策 #4 早就写了不许静默吞异常，这条是它的实证。）
- **一个「只有一个元素」的 fixture 测不出遍历逻辑的 bug。** `[3]` 的假缓存只有一个 key 且恰好命中，`or` 短路让第二个条件根本没求值 —— 于是这条测试**在本轮改动的两个缺陷都存在时照样 PASS**。**测遍历 bug 时，fixture 里必须有不匹配的元素，而且它要排在前面。** 复盘时问一句「这个测试如果把这个功能整个删掉，还会通过吗」，能筛掉一大半假测试。
- **推不对的时候要承认是推的。** 排查阶段我用「响应快到不可能是读 h5ad」排除了读数据这条路径，结论（慢在外部抓取）**碰巧是对的**，理由**是错的** —— 当时无从分辨两条路径，因为两条路径都静默。**推论与结论一致不代表推论成立**；后来日志一开，直接看到的和当初推的并不是同一件事。
- **降级要降在正确的那一层。** 摘要取不到，降的应该是摘要那一块，不是整个页面。`/api/abstract` 失败返回 200 而不是 500 也是同一个判断 —— **5xx 是在说「这个端点坏了」，而它其实是说「这次的补充信息没拿到」**，两者会让前端做出完全不同的处理。

---

## B36. Free Analysis「只输出代码不执行」：模型整轮零工具调用却宣称结果已生成 (2026-09-20)

### 现象

用户原话：

> 有个新bug，agent现在经常只输出代码不执行，是大模型的能力问题吗，前天用Free Analysis还好，今天就进场只出代码不执行了，你先看下，先告诉我原因

模型不调任何工具，直接吐一段文字（常夹着代码块），并声称「图片已重新生成！」「完成了！」，甚至给出一个指向**不存在文件**的图片链接。用户看到的是：一段读起来完整的分析报告，配一个空图框，然后什么都没有。

### 根因

#### 1. 不是回归 —— 先把这条排掉

排查时逐项验证过，全部正常：工具注册表（6 个原生工具）、`iter_tools = tools` 无条件传入（`agent/__init__.py`）、`_stream_sse` 的 OpenAI 分支是 `yield json.loads(ds)` 直通不丢 `tool_calls`、工具结果回填形状正确。scRNA / BulkRNA / Protein 三条组学路径各跑一次端到端，全部产出真实图表。

#### 2. 模型确实在整轮零工具调用

`/tmp/gensci_monitor.db`（`sessions` 表）里 2026-09-20 那段会话 10 轮、**6 轮 `tool_calls=0`**。`iter=0` 的含义是 `for iteration in range(max_iterations)` 的**第一轮**就没调 —— 不是「调了几轮后停下来」。

按前端的确切消息形状重放该会话，复现到原话「图片已重新生成！」并编造文件名 `venn_Merge5_vs_MMP7_unified.png`，那一轮一次工具都没调。

#### 3. 是上下文诱发的，不是模型能力问题

同一条提示（`title保持和上一张图片title一致`）在**空白上下文**里重放 **5/5 正常调工具**；在生产的那段上下文里则 `tools=0`。

已排除：组学类型（Bulk/Protein/scRNA 均正常）、温度（0.2/0.7/1.2 各 3/3 正常）、合成历史形状（前端形状与标准 OpenAI 形状均 3/3、4/4）。

#### 4. 结构性加重因素：历史里没有工具轨迹

前端只发 `{role, content, tool_results}`（`ChatMessage`，`src/api/types.ts:402`），**既没有 `tool_calls` 也没有 `role:'tool'`**；`handle_llm_chat_stream`（`routes.py:766`）原样转发。模型看到的每一个过往轮次都是「用一段文字回答就结束了」—— 一旦有一轮蒙混过关，它就成了可模仿的模板。

### 修复

在 `server/agent/__init__.py` 的两个 ReAct 循环（流式 / 非流式）里加兜底：整轮零工具调用、且正文读起来像「已产出结果」时，注入纠正消息并续跑，上限 `_MAX_EXECUTION_NUDGES = 2` 次。

**判定闸门只有一条，且是本修复最关键的部分**：必须 `all_tool_results` 为空。正常收尾那一轮同样没有 `tool_calls`，但那时工具已经跑过，正文里的「已生成」是实话 —— 拿它当证据会把**每一轮正常收尾**都判成撒谎并无限续跑。测试 `[2]` 专门锁这条。

#### 检测器第一版**没修住**，是端到端重放揪出来的

第一版按「枚举中文完成副词」判（`已生成|已完成|已保存|…`）。端到端重放时**连续两轮漏判**，同一故障换了两种措辞：

```
「完成了！现在两个散点图的标题格式一致」                        ← 一个「已」字都没有
「![…](/api/results?file=merge5_coexpression_f14c2a8b9d3e.png)」← 图片链接不是副词
```

**靠枚举措辞是打地鼠。** 于是改成按「这段文字是否指向了一个已经存在的产物」判 —— 那是**可证伪**的：本轮一次工具都没跑，被引用的文件不可能存在。

判据分三档，返回值决定要不要给用户挂可见提示：

| 档 | 依据 | 挂可见提示？ |
|---|---|---|
| `artifact` | markdown 图片 / `/api/results?file=` / 带产物扩展名的文件名 | **挂** —— 文件不存在是硬事实，不会冤枉人 |
| `claim` | 完成声明的措辞 | 不挂 —— 「……这样就完成了」这类正常解释也可能命中 |
| `code` | 代码块里有可执行特征 | 不挂 |

可见提示之所以必须存在：`message` 事件是**追加**到最后一条 assistant 气泡（`FreeAnalysisTab.tsx:119`），前端只认 `message`/`tool_result`/`error`，**没有「撤回」事件**。已经流出去的假话撤不回来，只能紧接着声明它不作数。

### 验证

**单元 / 集成**（`server/tests/test_unexecuted_guard.py`，新增，31 条断言）：9 个分组覆盖 检测→纠正→真的调到工具、不该纠正时不纠正、贴代码也判、纯解释不判、纠正次数封顶、非流式端点同样装闸。

**变异**（每一处修复都要能被一条失败抓住）：

- 把**流式**守卫改成 `if False:` → **8 项失败，exit=1**
- 把**非流式**守卫改成 `if False:` → **3 项失败**，其中一条直接暴露旧行为：幻觉正文被当作最终结果返回
- 把检测器**换回第一版**（运行时补丁，不改文件）→ **6 项失败**，其中正是逐字捕获的那两版真实故障原文。即：这条测试确实抓得住当初漏掉的那个 bug。

**端到端**（真实网关 + 真实数据集 `32832599.IPF.h5ad`，7 轮真实会话经 HTTP SSE 重放）：

```
[1] tools=4 ok
[2] tools=5 ok
[3] tools=1 ok
[4] tools=1 守卫触发  'title保持和上一张图片title一致'   ← 连续 3 次重放里这一轮都复现
[5] tools=1 ok
[6] tools=4 ok
[7] tools=5 ok
RESULT guard_fired_turns=[4]
```

第 4 轮的过程：模型编造「图片已重新生成！」+ 不存在的图片链接 + 假统计表（0 工具）→ 守卫挂出「上面引用的文件/图片并没有真正产生（本轮未调用任何工具），正在重新执行…」→ 模型改口「您说得对，我需要实际执行脚本来生成图片」→ 调用 `shell` → **真的执行了**。其余 6 轮无误伤。

**回归**：后端 15 个自包含脚本全绿（按退出码）、`npx tsc --noEmit` 干净、`npm run lint` 干净、`vitest` 159/159。

### 未覆盖（明确留白）

- **前端历史仍不含 `tool_calls` / `role:'tool'`**（上面「根因 4」）。这一条是结构性的，但合成 A/B 测试（两种历史形状）都得到 3/3、4/4 **测不出差异**，所以本轮**没有改**。它没有被证伪，也没有被证实。
- **`claim` 档不挂可见提示**，所以那一档触发时，用户仍会先看到一段假表格，紧随其后才是真结果。选择这样是因为措辞判据可能失准，不能拿一句未必成立的话去指责模型。
- **纯知识性回答会被多问一轮**。纠正语里给了明确的出口（只回复「无需执行」），但代价是一次额外的 LLM 调用 —— 这是有意接受的假阳性成本：多一次调用 vs. 用户把编造的分析当真。
- **生产 ~60% 的故障率 vs. 本地重放 ~14% 的差距没有解释清楚。** 重放能复现（3 次里第 4 轮 3 次都中），但不是每次全中；这个差距我无法定量归因。
- 只测了 `32832599.IPF.h5ad` 一个数据集、scRNA 一条组学路径的端到端。

### 涉及文件

- `server/agent/__init__.py`（`_RESULT_ARTIFACT_RE` / `_UNEXECUTED_CLAIM_RE` / `_EXEC_FENCE` 等判据、`_execution_nudge_reason`、`_looks_like_unexecuted_work`、`_needs_execution_nudge`、`_EXECUTION_NUDGE`、`_MAX_EXECUTION_NUDGES`；`process_chat` 与 `process_chat_streaming` 两处 nudge 分支）
- `server/tests/test_unexecuted_guard.py`（**新增**，含逐字捕获的真实故障原文作回归样本）

### 关键教训

- **「先告诉我是大模型的能力问题吗」值得认真回答，而且答案是「不是」。** 用户第一时间把锅归给模型，排查也确实一路指向模型（monitor.db 里 `tool_calls=0` 是硬证据）。但「模型发出零个工具调用」和「模型没有这个能力」是两回事 —— 同一条提示换空白上下文 5/5 正常。**把「模型这次的表现」和「模型的能力」分开，才知道该修提示词、修上下文，还是修循环。** 这里三者都不是，是循环里缺一条兜底。
- **枚举措辞的检测器，会在第一次遇到新说法时失效 —— 而那是必然的。** 第一版正则写完时，单测 6 条全过。是端到端重放在真实模型身上连续两轮漏判才暴露的。**被测对象是模型输出时，测试用例必须包含真实产出的原文，不能只有自己编的样本** —— 我自己编的样本恰好都用「已」，于是测试绿得很安心。
- **判据要挑「可证伪」的那种。** 「已生成」是措辞，措辞会被换；「引用了一个不存在的文件」是事实，事实换不掉。同样是启发式，后者不会因为模型换了种说法就整个失效。
- **假阳性与假阴性的代价不对称时，要按不对称来设计。** 这里的假阳性 = 多一次 LLM 调用；假阴性 = 用户把一份编造的分析当成真的读了。差着数量级，所以闸门内宁可偏向多问一轮 —— 但仍要留明确出口（「无需执行」），不能让合理行为被惩罚。
- **可见提示只能挂在硬事实上。** 同一个检测器，`artifact` 档挂提示、`claim` 档不挂 —— 因为提示一旦挂出去就是**在指控模型撒谎**，拿一个可能失手的判据去指控，等于用一个 bug 换另一个 bug。
- **已经流出去的文本撤不回来，这应该影响设计，而不是被忽略。** 前端没有「撤回」事件是硬约束；要么改协议，要么接受「在同一条气泡里紧接着声明它不作数」。选了后者，但把它写在注释里 —— 否则下一个人会以为那句提示是可有可无的装饰。
- **概率性故障也要有确定性的验证手段。** 这个 bug 在生产 ~60%、本地重放 ~14%，永远不能靠「再跑一次看看好没好」来收口。收口靠的是：逐字捕获一版真实故障原文 → 拿它当回归样本 → 变异回退必须失败。

---

## B37. 10 个 skill 被宣传成调不通的名字：`scan_skills()` 用 frontmatter `name`，`SKILL_REGISTRY` 用目录名 (2026-09-21)

### 现象

Free Analysis 的系统提示词「可用技能」列表里列着某些 skill，模型照着调却必然失败。
`skill(name)` 返回：

```json
{"error": "Skill not found: omicverse-single-cell-annotation",
 "available_skills": [...]}
```

**前端不显示任何异常，后端也不报错** —— 列表里有它、调用说没有它，两边各自都「正常」。

### 根因

同一件事有两套实现，各写各的，谁都没校验对方：

| 消费者 | 位置 | 名字取自 |
|---|---|---|
| 生成 prompt 的技能列表 | `skills/_loader.py:40` `scan_skills()` | **frontmatter 的 `name`** |
| 执行 `skill(name)` | `skills/__init__.py:191` `SKILL_REGISTRY` | **目录名** |

`agent/prompt.py:227-229` 据此告诉模型「call skill("name")」，而
`tools/SkillTool/__init__.py:21-26` 拿这个名字**查 `SKILL_REGISTRY`**、并**按它拼
`skills/<name>/SKILL.md` 的路径** —— 所以两边必须恰好相等。

实测 82 个 `SKILL.md` 里 **10 个**不等，全部是 omicverse 上游移植的遗留
（目录名被裁短、frontmatter 里留着原名）。

官方手册与 Claude Code 都要求 `name` 等于目录名：Claude Code 只把 frontmatter 的
`name` 当 `displayName`，正式名始终取目录名
（`08.claude-code-source/src/skills/loadSkillsDir.ts:452`）。所以错的是 `_loader.py`
那一侧 —— 但**改目录名会牵动** `llm_proxy.py:20-25` 的 `OMICS_SKILL_FILTERS`
（按目录名前缀分派，这 10 个全落在 `single-*`），故选择改 frontmatter，零风险方向。

### 修复

1. 10 个 `SKILL.md` 的 frontmatter `name` 改为等于目录名（各 1 行）。
2. `skills/statistical-analysis/SKILL.md:97-100` 正文里那 4 个同类断链一并改掉 ——
   它是 prompt 之外的第二条断链：模型读完 statistical-analysis 再照做，同样查不到。
3. 新增 `server/tests/test_skill_spec_conformance.py`，把 `drug-*` 早有的那条局部断言
   （「frontmatter name 等于目录名」）推广到全仓 82 个 skill，并补上手册其余硬性约束
   （kebab-case、≤64 字符、description ≤1024、无保留词），外加一条**契约级**断言：
   `scan_skills()` 的每个名字都必须能在 `SKILL_REGISTRY` 里查到。
4. 删掉 `test_drug_stages.py` 里那条局部断言（已被全量覆盖），并加 `npm run test:py` ——
   否则 20 个后端脚本仍只能人手跑，删掉的那条覆盖会落进「没人跑的文件」。

### 验证

- **RED → GREEN**：改名字**之前**先跑新测试，失败清单恰好是那 10 个（`[2]` 与 `[6]`
  各命中 10）；改完 14/14 绿。先看到红，才说明测试不是空跑。
- 活体（重启后端）：`/api/skills` 88 条；`scan_skills()` 的 88 个名字与
  `SKILL_REGISTRY` 的 88 个键完全对齐，「宣传了但查不到」为空。
- 用**真入口** `SkillTool.skill()` 实调 5 个原名，全部返回 7813–13217 字符正文
  并带 `Base directory for this skill:` 前缀。
- **反例对照**：旧名 `omicverse-single-cell-rna-velocity` 与不存在的名字仍正确返回
  `Skill not found` —— 证明不是把所有名字都放行了。

### 教训

- **同一件事有两份实现时，两边都会「按自己的理解」实现，而谁都不会去校验对方。**
  这条断言本该在第二套解析出现时就写上；它当时只写在了 `drug-*` 上，于是覆盖之外的
  10 个沉默了很久。**局部断言会给人一种「已经管住了」的错觉。**
- **新写的断言必须能被证伪 —— 本次新测试自己先踩了一次。** 一条「description ≤1024」
  的断言，遇到 YAML 块标量（`description: |`）时两个解析器都把值读成字面串 `'|'`
  （长度 1），于是在一条实际 2000 字的描述上**全绿** —— 而写长描述最自然的写法
  恰好就是 `|`。已在测试里显式识别块标量；**没有**去改生产解析器（那会动运行时行为）。
  写断言时要问：**它会在什么情况下给出假绿？**

---

*后续新缺陷按 B38、B39... 追加。*
