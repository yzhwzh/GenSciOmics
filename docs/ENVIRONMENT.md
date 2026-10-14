# ENVIRONMENT.md — GenSciOmics 运行环境

> 实测日期 **2026-10-14**。所有版本号来自解释器 `import` 实取，不是从文档抄的。
>
> **本文档存在的首要原因：本仓没有任何依赖清单。**
> `requirements.txt` / `environment.yml` / `pyproject.toml` / `setup.py` / `Pipfile` —— 六个全部不存在。
> 下面这份是从「解释器实测 + 源码 `import`」反推出来的真实环境。换机器部署时按本文操作。

---

## 一、最关键的一条：后端跑在**两个 conda 环境的并集**上

```
主解释器   /data/yuanwuzhou/Software/Anaconda/envs/claude-code/bin/python3     Python 3.10.20
第二注入   /data/yuanwuzhou/Software/Anaconda/envs/OmicVerse/lib/python3.10/site-packages
```

注入点在 `server/skills/_base.py:15-17`：

```python
_CONDA_SITE = Path('/data/yuanwuzhou/Software/Anaconda/envs/OmicVerse/lib/python3.10/site-packages')
if str(_CONDA_SITE) not in sys.path:
    sys.path.insert(0, str(_CONDA_SITE))
```

三个必须记住的性质：

1. **`insert(0, ...)` → OmicVerse 优先级高于 claude-code。** 同名包冲突时用 OV 那份。
2. **只装一个环境跑不起来。** `torch` 只存在于 OV；`anndata` / `scanpy` / `omicverse` 主体在 CC。
3. **这条路径是写死的本机绝对路径，且失效时静默。** OV 目录不存在时 `sys.path.insert` 不报错，
   要等某个 skill 真正用到 torch 才炸 —— 且报错位置离病因很远。**这是本仓最主要的部署地雷。**

> ⚠️ 这条路径是**承重的**，不要「清理」或「规范化」它。见 `docs/BUG_LOG.md`。
> 把它改成 `os.environ.get()` 并在缺失时打 stderr 警告是待办，当前**尚未**做。

---

## 二、后端硬依赖（已实测可 import）

| 类别 | 包 | 实测版本 |
|---|---|---|
| 数据基座 | `numpy` | 2.2.6 |
| | `pandas` | 2.3.3 |
| | `scipy` | 1.15.2 |
| | `h5py` | 3.16.0 |
| | `anndata` | 0.11.4 |
| 单细胞 | `scanpy` | 1.11.5 |
| | `omicverse` | 2.2.3 |
| 绘图 | `matplotlib` | 3.10.9 |
| | `seaborn` | 0.13.2 |
| | `colorcet` | 3.2.1 |
| | `matplotlib_venn` | 1.1.2 |
| | `cycler` | 0.12.1 |
| 统计 / 图论 | `scikit-learn` | 1.7.2 |
| | `statsmodels` | 0.14.6 |
| | `networkx` | 3.4.2 |
| 富集分析 | `gseapy` | 1.3.1 |
| | `upsetplot` | 0.9.0 |
| 文档产出 | `python-docx` | 1.2.0 |
| | `python-pptx` | 1.0.2 |
| | `openpyxl` | 3.1.5 |
| | `xlrd` | 2.0.2 |
| | `PyYAML` | 6.0.3 |
| 图像 | `Pillow` | 12.3.0 |
| **仅在 OmicVerse 环境** | `torch` | 由 `_base.py` 注入后可用 |

`omicverse` 是硬依赖而非可选：`server/skills/_base.py:39 _gpu_init()` 直接 `import omicverse as ov`。

---

## 三、可选依赖 —— 全部在 skill 脚本里，且都被 `try/except ImportError` 包住

**缺了只是功能降级，不会让服务起不来。** 下表是每个包在本仓的**唯一**引用点：

| 包 | 引用点 | 用途 |
|---|---|---|
| `PyMuPDF`（`fitz`） | `server/skills/light-slides/scripts/thumbnail.py:154` | PDF 缩略图 |
| `pypdf` / `PyPDF2` | `server/skills/light-figure-drawing/scripts/figure_export.py:408,411` | 图片导出 PDF |
| `reportlab` | `server/skills/light-file-reading/scripts/pdf_ops.py:148-151` | PDF 生成 |
| `shap` | `server/skills/light-result-analysis/scripts/explain_shap.py`（4 处） | 模型可解释性 |
| `deepchecks` | `server/skills/light-result-analysis/scripts/leakage_overfit_check.py:114` | 数据泄漏 / 过拟合检查 |
| `colorspacious` | `server/skills/light-figure-drawing/scripts/color_palettes.py:114,132` | 色觉安全校色 |

**`pytest` 确实没装**，这是设计而非疏漏：`npm run test:py` 是自包含脚本
（`for f in server/tests/test_*.py; do python3 "$f" || exit 1; done`），不依赖测试框架。

---

## 四、环境变量

### 4.1 有默认值（缺失不影响启动）

| 变量 | 默认值 | 定义处 | 作用 |
|---|---|---|---|
| `GENSCI_RESULTS_DIR` | `/tmp/gensci_results` | `server/config.py:23` | 分析产物落盘目录 |
| `HTTP_PROXY` | `http://10.50.3.122:3128` | `server/config.py:47` | 见 4.4 |
| `EXA_API_KEY` | `''`（空则匿名访问） | `server/config.py:88` | Exa MCP |

### 4.2 外部检索服务凭证（全部可选，缺失即该来源不可用）

| 变量 | 用于 |
|---|---|
| `OPENALEX_API_KEY` | OpenAlex 检索（`light-literature-search`、`light-citation`、`light-ip-application`） |
| `OPENALEX_MAILTO` | OpenAlex 礼貌池标识 |
| `CROSSREF_MAILTO` | Crossref 礼貌池标识 |
| `S2_API_KEY` | Semantic Scholar 检索 / 引文核验 |
| `NCBI_API_KEY` / `NCBI_EMAIL` | NCBI E-utilities |

### 4.3 **无默认值 —— 缺失直接 `KeyError`**

```python
# server/skills/single-cell-scenic/scripts/scenic_smoke.py:53-54
db_glob     = os.environ["SCENIC_DB_GLOB"]
motif_path  = os.environ["SCENIC_MOTIF_PATH"]
```

用 SCENIC skill 前必须设这两个。这是全仓**唯一**用 `os.environ[...]` 硬取值的地方，
其余都是 `.get(...)` 带默认。

### 4.4 代理行为（容易踩）

`server/config.py:47-50` 会在进程内 **`setdefault` 三个代理变量**：

```python
HTTP_PROXY  = os.environ.get('HTTP_PROXY', 'http://10.50.3.122:3128')
os.environ.setdefault('http_proxy',  HTTP_PROXY)
os.environ.setdefault('https_proxy', HTTP_PROXY)
os.environ.setdefault('NO_PROXY',    'localhost,127.0.0.1,10.0.0.0/8,.ai.dgtmeta.com')
```

含义：**即使你不设任何代理变量，后端也会走公司代理。** 内网网关
（`.ai.dgtmeta.com`）和 `10.0.0.0/8` 段已列入 `NO_PROXY` 直连。
`server/routes.py:908` 在需要绕代理的子进程里显式 `pop` 掉这两个变量。

### 4.5 由代码自行设定（不必手工配）

| 变量 | 设定处 | 原因 |
|---|---|---|
| `HDF5_USE_FILE_LOCKING=FALSE` | `server/main.py:13` | 防止多线程并发读同一 `.h5ad` 时挂死 |

---

## 五、外部 CLI 与 MCP

### 5.1 运行时

```
node  v25.2.1
npx   11.6.2
uv    ~/.local/bin/uv
```

### 5.2 tooluniverse

```
~/.local/bin/tooluniverse  →  /home/yuanwuzhou/.local/share/uv/tools/tooluniverse/bin/tooluniverse
（由 uv 管理，不是 pip 装进 conda 环境的）
```

API key 存放：**`~/.tooluniverse/.env`**（不在仓库内、不在任何 git 中）。
经查证需要 4 个：`NCBI_API_KEY`、`NVIDIA_API_KEY`、`BIOGRID_ACCESS_KEY`、`FDA_API_KEY`。
`server/config.py:118` 注释写明以 `--global` 参数启动，即读该文件而非 cwd。

> ⚠️ 该目录当前权限为 `0755`（组/他人可列目录），`.env` 本身是 `0600`（内容受保护）。
> 建议 `chmod 700 ~/.tooluniverse` 收紧。

### 5.3 后端作为 MCP 客户端的连接（`server/config.py:84-121`）

| 名称 | 类型 | 启动方式 |
|---|---|---|
| `exa` | http | `https://mcp.exa.ai/mcp`（key 走 `EXA_API_KEY`） |
| `context7` | stdio | `npx -y @upstash/context7-mcp@2.1.4` |
| `sequential-thinking` | stdio | `npx -y @modelcontextprotocol/server-sequential-thinking@2025.12.18` |
| `github` | stdio | `npx -y @modelcontextprotocol/server-github@2025.4.8` |
| `playwright` | stdio | `npx -y @playwright/mcp@0.0.69 --extension` |
| `tooluniverse` | stdio | `~/.local/bin/tooluniverse --global` |

> 注：这里的 `playwright` 与 Claude Code 侧的浏览器工具**不是同一个**。
> 本机 Claude Code 侧（`~/.claude.json`）只配了 `playwright` 一项。
> 两者的选型坑见 `CLAUDE.md` 的「本机环境注意事项」。

---

## 六、前端

Node 侧依赖全部声明在 `package.json`，无需反推。要点：

| 层 | 关键包 |
|---|---|
| 框架 | React 19、TypeScript 6、Vite 8 |
| 样式 | Tailwind CSS 4（`@tailwindcss/vite`） |
| 可视化 | ECharts 6 |
| 路由 | react-router-dom 7 |
| 测试 | Vitest 4、Testing Library、jsdom |
| E2E | Playwright 1.61 |

`package.json` **未声明 `engines`**，Vite 8 本身要求 Node ≥ 20.19，实测环境为 v25.2.1。

前端**目前不读任何 `import.meta.env`** —— 全仓 `src/` 内无该用法。

---

## 七、端口与网络

| 项 | 值 | 定义处 |
|---|---|---|
| Vite 开发服务器 | `0.0.0.0:5180` | `vite.config.ts:10-11` |
| HMR | `10.243.163.51:5181` | `vite.config.ts:5,14-16` |
| Python API | `0.0.0.0:6001`（可用 `--port` 覆盖） | `server/config.py:26-27` |
| `/api` 代理 | `5180 → 127.0.0.1:6001` | `vite.config.ts:29-34` |
| CORS 白名单 | `127.0.0.1` / `localhost` / `10.243.163.51` 的 5180、5181 | `server/config.py:30-34` |

`allowedHosts` 也硬编码为 `10.243.163.51` / `localhost` / `127.0.0.1`（`vite.config.ts:18`）。

---

## 八、从零复现（干净机器）

```bash
# 1. 两个 conda 环境都要有
conda create -n claude-code python=3.10
conda create -n OmicVerse   python=3.10
# 2. 按第二节表格装硬依赖（claude-code 装主体；torch 单独确认在 OmicVerse 里）
# 3. 可选依赖按第三节表格装，缺了也能跑
# 4. 前端
npm install
# 5. 外部 CLI
#    uv tool install tooluniverse   → 并创建 ~/.tooluniverse/.env（见 5.2 四个变量）
# 6. 启动
npm run start        # = python3 server/main.py & vite   （:6001 + :5180）
```

启动后**先看后端日志有没有报错**，再验证
`curl http://127.0.0.1:6001/api/datasets | head -c 200` 能返回数据。

---

## 九、已知的不可复现风险（按优先级）

| # | 风险 | 现状 | 建议 |
|---|---|---|---|
| 1 | **`_base.py:15` 写死本机绝对路径**，且失效时静默 | 未处理 | 改 `os.environ.get('OMICVERSE_SITE_PACKAGES')` + 缺失时 stderr 警告 |
| 2 | **无任何依赖清单 / 无版本锁** | 未处理 | 本文档是当前唯一记录 |
| 3 | 内网 IP 硬编码（`10.243.163.51` @ `vite.config.ts:14,18`、`playwright.config.ts:8`、`e2e/verify-hmr-port.spec.ts:3`、`server/config.py:33`） | 未处理 | 与 Vite 端口变更叠加时会导致 HMR / E2E 静默失效 |
| 4 | `SCENIC_DB_GLOB` / `SCENIC_MOTIF_PATH` 无默认值 | 设计如此 | 用 SCENIC 前显式设置 |

---

## 十、相关文档

- `CLAUDE.md` — 架构、命令、开发流程、本机环境注意事项
- `docs/BUG_LOG.md` — 缺陷日志（含 `_base.py` 承重路径相关条目）
- `server/config.py` — 所有常量的唯一来源
