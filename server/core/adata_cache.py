"""Shared AnnData cache — backed='r', keyed by (path, mtime, size, inode).

All analysis modules share a single adata object per dataset, avoiding
repeated HDF5 open overhead. Memory cost is ~few MB per dataset (metadata
only — backed='r' reads actual data from disk on demand).

Thread safety: a per-file lock serialises access to the shared backed AnnData,
preventing h5py concurrency errors when multiple threads slice into adata.X.

B42 — 就地被改写的文件必须能自愈，否则只能重启进程。

现场：用户改了 `40425564.STGD.h5ad` 的标签、就地重新保存，此后
`/api/analysis-info` 与 `/api/umap-data` 永远回
`'Unable to synchronously open object (bad object header version number)'`，
而**任何一个新进程**都能正常打开同一个文件；重启后端立刻恢复。

成因是两处，各自都能把一次瞬时故障固化下来：

  1. 本缓存按 `path:mtime` 缓存 backed 句柄，而此前只有 LRU 满 8 条时才关掉一条
     —— 没有任何路径会因为「读不出来」而驱逐它。HDF5 没有事务性读，改写期间
     能「成功」打开并交回一个句柄（B30 的注释写过这件事的温和面：no exception,
     just 0 rows）。而且句柄一旦建立就**记着打开那一刻的字节**：实测外部进程就
     地重写同一个 inode 之后，老句柄继续回答旧数据（5 行 vs 新文件的 9 行）
     且**不报任何错** —— 静默的错，比报错更难发现。
  2. 两个 API 响应缓存（`routes._analysis_info_cache` / `_umap_cache`）把**失败
     结果**也存进去，而它们的键里**没有文件身份** → 改写窗口内缓存下来的那条错误
     被一直复用，文件早就好了，接口还在吐旧错。**这才是「必须重启」的主因**：
     第一个请求撞上写窗口把错误存住，此后那个键再也没变过。

因此现在有四条硬约束：

  1. 缓存键带上文件身份（mtime + size + inode），改写或改名换姓都必然 miss，
     不可能拿旧字节上的句柄去服务新内容；
  2. **打开之前**先关掉身份对不上的旧句柄（`_evict_other_identities`）——
     陈旧句柄污染的是整个进程对该文件的 HDF5 视图，只要它还开着，**新开的句柄
     也读不对**。所以驱逐必须发生在打开**之前**，否则用户会先看到一次报错；
  3. 用着用着坏掉的句柄**当场驱逐**（`locked_backed_adata` 失败即 `invalidate`），
     下一次调用重新打开 —— 兜住第 2 条没覆盖到的形态（文件在两次 stat 之间又变了）；
  4. API 层不得把错误响应存进不含文件身份的键（见 routes.py 的两处 `file_identity`）。

**两个被推翻的做法，写在这里免得有人再加回来。**

其一，「打开时先探一下句柄健不健康，只在它答不上话时才拒绝」。它做不到，而且错得
很隐蔽：

  * anndata 在**打开时就把 obs / var / obsm 读进内存**（实测 `read_h5ad(backed='r')`
    之后 `'X_umap' in adata.obsm` 即为真，`.obs` 访问 0 ms），所以任何探针拿到的
    都是缓存里的 Python 对象，根本不碰磁盘 —— 它只会回答「健康」；
  * h5py **不允许 truncate 一个本进程已打开的文件**，所以「打开时文件正在被改写」
    那种坏句柄，探针恰恰探不出来。

其二，「打开失败就驱逐、再重开一次」。方向对，但**不够**，而且不够的方式很有教育
意义：它把第 1 次尝试修好了吗？没有 —— 实测仍然是第 2 次才成功。因为打开本身是
**成功**的，报错发生在之后读到对象的时候（`address of object past end of
allocation`），重试包在 `read_h5ad` 外面根本拦不到。它是第 3 条的一部分（兜底），
不是第 2 条的替代品。别把它当主修复。
"""

import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from collections import OrderedDict

import anndata


_cache: dict[str, 'anndata.AnnData'] = OrderedDict()
_cache_lock = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()
MAX_SIZE = 8


def _get_file_lock(path: str) -> threading.Lock:
    """Get or create a per-file lock for serialising backed access."""
    with _file_locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def file_identity(path: str) -> str:
    """The file's identity as a string: mtime + size + inode.

    Exposed so API response caches can key on it. Without it a cached answer —
    including a cached *error* — outlives the bytes it came from, which is what
    made the B42 symptom need a restart: the first request landed in the middle
    of a rewrite, cached the failure, and the key never changed again.

    An unreadable path yields a constant marker; the read that follows fails
    loudly rather than serving something stale. It is logged rather than
    silently swallowed (CLAUDE.md 设计决策 #4) because "every broken path shares
    one cache key" is exactly the sort of thing nobody would guess from the
    symptom.
    """
    try:
        st = Path(path).stat()
        return f'{st.st_mtime}:{st.st_size}:{st.st_ino}'
    except OSError as e:
        print(f'[GenSci] cannot stat {path} for cache key: {e}', file=sys.stderr)
        return '0'


def _stat_key(path: str) -> str:
    """Cache key — path plus the file's identity.

    mtime alone is too weak to tell "same bytes" from "different bytes": an
    in-place rewrite can land inside one mtime tick, and a write-temp-then-
    rename keeps mtime while swapping the inode. Size and inode make both
    visible, so a handle opened on the previous bytes can never be handed back
    for the new ones.
    """
    return f'{path}:{file_identity(path)}'


def _close_quietly(adata) -> None:
    """Close a handle, logging a failure instead of swallowing it.

    A handle over a half-written file can raise from close() too. There is
    nothing useful to do about that — the caller is already unwinding — but
    静默是禁止的（CLAUDE.md 设计决策 #4），所以留痕。
    """
    try:
        adata.file.close()
    except Exception as e:
        print(f'[GenSci] closing backed AnnData handle failed: {e}', file=sys.stderr)


@contextmanager
def locked_backed_adata(path: str) -> 'anndata.AnnData':
    """Context manager: acquire file lock, yield backed AnnData, release.

    Usage:
        with locked_backed_adata(path) as adata:
            subset = adata[mask].to_memory()
        # lock released — heavy work runs unlocked

    任何异常都驱逐句柄，再原样抛出（B42）。

    代价是：调用方自己抛的普通异常也会多付一次重开（读一遍 obs/var/元数据）。接受
    这个代价 —— 一次多余的 HDF5 打开，换的是「改完数据必须重启后端」这个 bug 不再
    出现。详见模块 docstring 里被推翻的那个「聪明版本」。

    注意 threading.Lock 不可重入：不要在这个 with 体内再对同一个 path 取一次
    `locked_backed_adata`（会自锁）。调用方持有的句柄要么全程用外层这个，要么
    用裸 `get_adata`。
    """
    lock = _get_file_lock(path)
    lock.acquire()
    try:
        adata = get_adata(path)
        try:
            yield adata
        except Exception:
            invalidate(path)
            raise
    finally:
        lock.release()


def invalidate(path: str) -> None:
    """Drop and close every cached handle for this path, whatever its mtime.

    Called whenever a handle proves unreadable. Without this the failure
    outlives the file it came from: the key stops changing once the rewrite
    finishes, so a handle left in place is reused forever.
    """
    prefix = f'{path}:'
    with _cache_lock:
        for key in [k for k in _cache if k.startswith(prefix)]:
            _close_quietly(_cache.pop(key))


def _evict_other_identities(path: str, keep_key: str) -> None:
    """Close handles for this path that no longer match the file on disk.

    B42 的关键一步，而且是唯一能让**改写后第一次请求**也成功的一步。

    实测机理：陈旧句柄不是「自己读不出来」那么简单 —— 它污染的是**整个进程
    对那个文件的 HDF5 视图**。旧句柄还开着的时候，本进程即使**新开**一个句柄读
    新字节，也会在读到对象时抛 `address of object past end of allocation`；
    把旧句柄关掉，同一个文件立刻读得对。这就是「重启进程就好了」的真实成因。

    所以不能等「新句柄读失败再驱逐」——那时用户已经看到一次报错了。必须在
    **打开之前**先把身份对不上的旧句柄关掉。此时机的代价是零：只有当文件身份
    真的变了（mtime/size/inode 任一不同）才会命中，日常查询路径不受影响。
    """
    prefix = f'{path}:'
    with _cache_lock:
        for k in [k for k in _cache if k.startswith(prefix) and k != keep_key]:
            _close_quietly(_cache.pop(k))


def get_adata(path: str) -> 'anndata.AnnData':
    """Get a cached backed='r' AnnData object. Thread-safe cache, but
    callers MUST serialise access themselves (use locked_backed_adata())."""
    key = _stat_key(path)

    with _cache_lock:
        if key in _cache:
            adata = _cache.pop(key)
            _cache[key] = adata  # LRU bump
            return adata

    # 文件身份变了（用户重存了数据）→ 先关掉这张路径下的旧句柄再开新的。
    # 顺序不能反：只要旧句柄还在，新句柄也读不对（见 _evict_other_identities）。
    _evict_other_identities(path, key)

    # Open **outside** _cache_lock. A cold open measures ~0.4 s on a 2.8 GB file
    # and ~13 s on the 171 GB Tabula set, and holding the cache lock across it
    # would stall get_adata for every unrelated dataset in the process. Two
    # threads racing on the same cold key may both open; the loser is closed
    # below and the incumbent handle is returned.
    try:
        adata = anndata.read_h5ad(path, backed='r')
    except Exception as first_err:
        # B42 的兜底。主修复是上面的 `_evict_other_identities`（打开**之前**就
        # 驱逐）；走到这里说明文件在两次 stat 之间又变了 —— 极端但可能：用户保存
        # 的那一刻正好落在这几行之间。那时唯一能做的还是驱逐 + 重开一次。
        #
        # 实测过：光靠这个重试**不够** —— 陈旧句柄还在时，打开本身是成功的，报错
        # 发生在之后读到对象的时候（`address of object past end of allocation`），
        # 包在 read_h5ad 外面的重试拦不到。所以它只是兜底，不是主修复。
        invalidate(path)
        try:
            adata = anndata.read_h5ad(path, backed='r')
        except Exception as retry_err:
            # 重试也失败：不是陈旧句柄的问题（文件本身坏了 / 权限 / 真的在写）。
            # 原样往上抛，并把第一次的错误挂上，别丢线索。
            #
            # 刻意**不**在这里补一条日志：上层（scanner / route）本来就会为这个故障
            # 记一条，这里再补一条会让同一个故障刷两行
            # （tests/test_scanner_resilience.py 断言「一个坏文件恰好一行 stderr」）。
            raise retry_err from first_err
        print(f'[GenSci] stale handle evicted, reopened {path} '
              f'(first open failed: {first_err})', file=sys.stderr)

    with _cache_lock:
        if key in _cache:  # lost the race — keep the handle already in place
            _close_quietly(adata)
            return _cache[key]
        while len(_cache) >= MAX_SIZE:
            old_key, old_adata = next(iter(_cache.items()))
            _close_quietly(old_adata)
            del _cache[old_key]
        _cache[key] = adata
        return adata
