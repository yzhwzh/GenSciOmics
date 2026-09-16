#!/usr/bin/env python3
"""文献补充材料：解析附件清单 + 按需取用其中的表格。

两件事，成本差三个数量级：

1. **清单**（`parse_supplementary`）—— 零网络。XML 是 `pubmed._fetch_abstract`
   为了提取 Methods 已经下载过的那一份，这里只是多正则一遍。
2. **内容**（`fetch_package` / `extract_table`）—— 25–37 MB 整包 ZIP，经代理约 1 MB/s。
   所以只在用户真的点「查看」时才下，下完落盘缓存。

PMC 没有任何「只取单个附件」的接口：`/supplementaryFiles/<file>` 之类的子路径
一律返回整包（实测 200 + 21 MB zip），所以按需 + 缓存是唯一可行的做法。
"""

from __future__ import annotations

import csv
import datetime
import html
import io
import os
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from config import HTTP_PROXY, SUPP_CACHE_DIR, SUPP_CACHE_MAX_MB

# ─── 判据（集中在此，不散落） ─────────────────────────────────

#: 表格类附件：能给用户渲染成表格的扩展名。
TABLE_EXT = re.compile(r'\.(xlsx|xls|csv|tsv|txt)$', re.IGNORECASE)
#: 图片类：论文里的 figure，不是数据，单独归类避免混进表格列表。
FIGURE_EXT = re.compile(r'\.(jpg|jpeg|png|gif|tif|tiff|eps|svg)$', re.IGNORECASE)

#: 疑似「样本/受试者信息」的词。命中只用于**打星标并排前面**，不用于隐藏任何东西。
#:
#: 实测证明文件名不可靠：`aba1972_Table_S9.xlsx` 名字里带 Table，打开是 motif 表；
#: 而 `mmc2.xlsx` 才是真正的患者信息表。所以这里宁可放宽 —— 漏标只是少一颗星，
#: 误标只是多一颗星，都不会让用户看不到附件。
SAMPLE_HINT = re.compile(
    r'sample|donor|patient|subject|clinical|characteristic|demograph'
    r'|covariat|metadata|specimen',
    re.IGNORECASE,
)

#: 反例词：这些 caption 描述的是**基因**，只是顺带提了一句 subjects/patients。
#:
#: 加这条是因为实测数据打脸了纯正向匹配 —— IgAN 那篇（PMC8085501）12 条附件里
#: 9 条被 SAMPLE_HINT 命中，其中 6 条是 DEG 表（"DEGs in tubular cells …
#: comparing IgAN and control subjects"）。命中率 75% 的星标等于没有星标。
#: 剔除基因中心词汇后剩 3 条，逐条核对都是真正的样本表。
#:
#: 仍然只影响打星、不影响是否列出 —— 判错最多少一颗星，不会藏掉任何附件。
SAMPLE_EXCLUDE = re.compile(
    # 注意是 degs? 不是 \bdeg\b —— 真实的 caption 全写成 "DEGs"（复数），
    # 尾部的 \b 卡在 s 上会导致一条都匹配不到。
    r'\bdegs?\b|\bdifferentially\s+expressed|marker\s+gene|enrichment'
    r'|\bkegg\b|\bgene\s+ontology|\bpathway|\bmotif|\bgo\s+term',
    re.IGNORECASE,
)

MAX_ROWS = 5000
MAX_COLS = 100

#: 附件包下载重试。NCBI 实测 5 并发就返回 429，这条不是装饰。
_RETRY_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5

_PMCID_RE = re.compile(r'^PMC\d+$')

# 复用 pubmed.py 的代理写法：走代理，不做直连回退。
_proxy_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': HTTP_PROXY, 'https': HTTP_PROXY})
)

# 每 pmcid 一把锁：多个用户同时点同一篇时，只有一个真的去下载，
# 其余在这里阻塞，醒来时文件已经在了，直接复用。
_pkg_locks: dict[str, threading.Lock] = {}
_pkg_locks_guard = threading.Lock()


def _lock_for(pmcid: str) -> threading.Lock:
    with _pkg_locks_guard:
        return _pkg_locks.setdefault(pmcid, threading.Lock())


# ─── 纯解析（离线可测） ───────────────────────────────────────


def _strip_tags(fragment: str) -> str:
    """去标签 + 解实体 + 压空白，得到能直接显示的一行文本。"""
    text = re.sub(r'<[^>]+>', ' ', fragment)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def _basename(href: str) -> str:
    return href.rstrip('/').rsplit('/', 1)[-1]


def is_sample_hint(name: str, caption: str) -> bool:
    """这条附件像不像「样本/受试者信息表」。

    正向词命中 **且** 没有基因中心词。后者是实测加的：见 SAMPLE_EXCLUDE 的注释。
    只影响排序和星标，不影响是否列出。
    """
    text = f'{name} {caption}'
    return bool(SAMPLE_HINT.search(text)) and not SAMPLE_EXCLUDE.search(caption)


def parse_supplementary(xml_text: str) -> list[dict]:
    """从 PMC 全文 XML 抽 <supplementary-material> 清单。

    返回 [{'name', 'caption', 'kind', 'is_sample_hint'}]，按 XML 中出现顺序，
    **同名条目只保留第一条** —— PMC 会给同一份文件生成两条记录
    （第二条 id 带 `db_ds_..._reqid_` 后缀），不去重页面上就会显示两遍。

    用 split 而非配对正则：真实 XML 在网络半包时是不闭合的，
    配对正则会一条都提不出来，split 至少能把完整的几条留下。
    """
    if not xml_text:
        return []

    items: list[dict] = []
    seen: set[str] = set()

    for block in re.split(r'<supplementary-material\b', xml_text)[1:]:
        # 只在本元素内找 href/caption，别串到后面的内容里去
        end = block.find('</body>')
        if end != -1:
            block = block[:end]

        m = re.search(r'xlink:href="([^"]+)"', block) or re.search(r'\bhref="([^"]+)"', block)
        if not m:
            continue
        name = _basename(m.group(1))
        if not name or name in seen:
            continue

        cap = re.search(r'<caption>(.*?)</caption>', block, re.DOTALL)
        caption = _strip_tags(cap.group(1)) if cap else ''

        if TABLE_EXT.search(name):
            kind = 'table'
        elif FIGURE_EXT.search(name) or re.match(r'\s*fig', caption, re.IGNORECASE):
            kind = 'figure'
        else:
            kind = 'file'

        seen.add(name)
        items.append({
            'name': name,
            'caption': caption,
            'kind': kind,
            'is_sample_hint': is_sample_hint(name, caption),
        })

    return items


def supplementary_note(has_pmcid: bool, fetch_ok: bool, n_items: int) -> str:
    """区分三种「没有补充材料」。

    这三种对用户的含义完全不同，混成一句话就是把「查过确实没有」和
    「我们根本没能力查」说成一回事：

      · no-pmcid —— 该刊未开放全文，我们拿不到，**没检查过**
      · error    —— 抓取失败（限流/超时），重试可能就有了
      · none     —— 拿到了全文，里面确实没有附件
    """
    if not has_pmcid:
        return 'no-pmcid'
    if not fetch_ok:
        return 'error'
    if n_items == 0:
        return 'none'
    return ''


def _safe_member_name(name: str) -> str | None:
    """把用户传进来的文件名收敛成「zip 内部的裸文件名」，不合法则 None。

    这是安全边界：调用方只会拿这个值去 zip 里找成员，永远不落到文件系统路径上。
    因此拒绝了斜杠、`..`、绝对路径、隐藏文件之后，穿越在结构上就不可能发生 ——
    不是靠黑名单挡住已知的攻击串。
    """
    if not name or '\x00' in name:
        return None
    if '/' in name or '\\' in name:
        return None
    if name.startswith('.'):
        return None
    if '..' in name:
        return None
    return name


def is_valid_lookup(pmcid: str, name: str) -> bool:
    """这个 (pmcid, name) 组合是否值得去下载。

    路由用它决定该回 400 还是回 200 —— 把「非法输入」和「下载/解析失败」
    分成两种响应。后者是正常业务流程的一部分（限流、坏文件），
    前者是有人在构造请求，不该混在一个 200 里。
    """
    return bool(_PMCID_RE.match(pmcid or '')) and _safe_member_name(name) is not None


def _cell(value):
    """把单元格值收敛成 JSON 能安全序列化的类型。"""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _rows_to_sheet(sheet_name: str, row_iter) -> dict:
    """把「一行行可迭代的值」转成 {name, columns, rows}，并施加行列上限。"""
    columns: list[str] = []
    rows: list[list] = []
    truncated = False

    for i, raw in enumerate(row_iter):
        values = [_cell(v) for v in raw]
        if i == 0:
            columns = ['' if v is None else str(v) for v in values[:MAX_COLS]]
            if len(values) > MAX_COLS:
                truncated = True
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        if len(values) > MAX_COLS:
            values = values[:MAX_COLS]
            truncated = True
        rows.append(values)

    # read_only 模式下 max_row 常被虚报，尾部会拖一串全空行 —— 只砍尾部，
    # 中间的空行保留（那可能是作者真的有意的分隔）。
    while rows and all(v is None or v == '' for v in rows[-1]):
        rows.pop()

    return {'name': sheet_name, 'columns': columns, 'rows': rows, '_truncated': truncated}


def read_table_file(filename: str, data: bytes) -> dict:
    """把一个附件文件的字节解析成 {sheets, truncated} 或 {error}。

    与网络无关，所以能离线测；`extract_table` 只负责把字节取来。
    解析失败一律返回 error 而不是抛 —— 论文附件里什么都有，
    一个坏文件不该让整个 Study Info 页面挂掉。
    """
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else '').lower()
    try:
        if ext in ('csv', 'tsv', 'txt'):
            text = data.decode('utf-8-sig', errors='replace')
            if not text.strip():
                return {'sheets': [{'name': Path(filename).stem, 'columns': [], 'rows': []}],
                        'truncated': False}
            delimiter = '\t' if ext == 'tsv' else ','
            if ext == 'txt':
                try:  # 单列文件会让 Sniffer 抛异常，回退逗号
                    delimiter = csv.Sniffer().sniff(text[:4096]).delimiter
                except Exception:
                    pass
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            sheet = _rows_to_sheet(Path(filename).stem, reader)

        elif ext == 'xlsx':
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheets = [
                _rows_to_sheet(ws.title, ws.iter_rows(values_only=True))
                for ws in wb.worksheets
            ]
            wb.close()
            return _pack(sheets)

        elif ext == 'xls':
            import xlrd
            book = xlrd.open_workbook(file_contents=data)
            sheets = [
                _rows_to_sheet(sh.name, (sh.row_values(r) for r in range(sh.nrows)))
                for sh in book.sheets()
            ]
            return _pack(sheets)

        else:
            return {'error': f'暂不支持在线预览 .{ext} 文件，请直接下载查看。'}

    except Exception as exc:
        return {'error': f'无法解析 {filename}：{type(exc).__name__}: {exc}'}

    return _pack([sheet])


def _pack(sheets: list[dict]) -> dict:
    truncated = any(s.pop('_truncated', False) for s in sheets)
    return {'sheets': sheets, 'truncated': truncated}


# ─── 网络：下载附件包并取用 ───────────────────────────────────


def _download(url: str, timeout: int = 300) -> bytes:
    """带退避重试的下载。爬 NCBI 遇到 429/5xx 是常态，不是异常。"""
    last: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            with _proxy_opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in _RETRY_CODES or attempt == _MAX_RETRIES:
                raise
            # 尊重 Retry-After，否则指数退避
            wait = _BACKOFF_BASE * (2 ** attempt)
            retry_after = exc.headers.get('Retry-After') if exc.headers else None
            if retry_after:
                try:
                    wait = min(float(retry_after), 8.0)
                except ValueError:
                    pass
            time.sleep(wait)
        except Exception as exc:
            last = exc
            if attempt == _MAX_RETRIES:
                raise
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise last if last else RuntimeError('download failed')


def _prune_cache(keep: Path) -> None:
    """超过总容量上限时按 mtime 淘汰最旧的包。每篇 25–37 MB，不设上限会吃满磁盘。"""
    try:
        files = [p for p in SUPP_CACHE_DIR.glob('*.zip') if p != keep and p.is_file()]
    except OSError:
        return
    limit = SUPP_CACHE_MAX_MB * 1024 * 1024

    def total() -> int:
        return sum(p.stat().st_size for p in files if p.exists())

    if total() <= limit:
        return
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        try:
            p.unlink()
        except OSError:
            continue
        if total() <= limit:
            break


def fetch_package(pmcid: str) -> Path:
    """把该论文的补充材料整包下载到本地缓存并返回路径。

    PMC 没有单文件接口（`/supplementaryFiles/<file>` 也返回整包），
    所以第一次必然要下 25–37 MB；之后走磁盘，秒开。
    """
    if not _PMCID_RE.match(pmcid):
        raise ValueError(f'非法的 PMCID: {pmcid!r}')

    SUPP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = SUPP_CACHE_DIR / f'{pmcid}.zip'

    with _lock_for(pmcid):
        # 拿到锁时先看盘：并发的第二个请求到这里就直接复用了第一份下载结果
        if path.exists() and path.stat().st_size > 0:
            return path

        url = f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles'
        blob = _download(url)

        # 原子写：写 .tmp 再 rename，避免下到一半被别的请求读到半截 zip
        tmp = path.with_suffix('.zip.tmp')
        tmp.write_bytes(blob)
        os.replace(tmp, path)

    _prune_cache(keep=path)
    return path


def extract_table(pmcid: str, name: str) -> dict:
    """取出整包里名为 `name` 的那个附件并解析成表格。"""
    safe = _safe_member_name(name)
    if safe is None:
        return {'error': '非法的附件名'}

    try:
        package = fetch_package(pmcid)
    except Exception as exc:
        return {'error': f'下载补充材料失败：{type(exc).__name__}: {exc}'}

    try:
        with zipfile.ZipFile(package) as zf:
            # 先精确匹配，再退而按 basename 匹配（有些包把文件放进子目录）。
            # 这里同时充当白名单：包里没有的名字自然取不到。
            member = next((n for n in zf.namelist() if n == safe), None)
            if member is None:
                member = next((n for n in zf.namelist() if _basename(n) == safe), None)
            if member is None:
                return {'error': f'补充材料包中没有找到 {safe}'}
            data = zf.read(member)
    except zipfile.BadZipFile:
        return {'error': '补充材料包已损坏，请稍后重试。'}
    except Exception as exc:
        return {'error': f'读取补充材料失败：{type(exc).__name__}: {exc}'}

    return read_table_file(safe, data)
