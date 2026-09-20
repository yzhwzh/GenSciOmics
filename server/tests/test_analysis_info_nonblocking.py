#!/usr/bin/env python3
"""`/api/analysis-info` 不得发起外部网络请求，且外部抓取必须有总时限。

自包含（不依赖 pytest），沿用 server/tests/test_pipeline_resilience.py 的骨架：
每条断言打一行 PASS/FAIL，末尾 sys.exit(1) 表明有失败。

运行：python3 server/tests/test_analysis_info_nonblocking.py

为什么要有这个文件
2026-09-20 用户报「点进 32832599 显示 Failed to load info / Go Back」。排查结果：
`handle_analysis_info` 在冷缓存时**同步**调 `_fetch_abstract(pmid)`，后者经公司代理
发 3 次外部 HTTP（2 次 EuropePMC + 1 次 NCBI PMC 全文）。这些只有 per-socket 超时
（8s/8s/10s），**没有总时限**，代理慢时可以拖到几分钟。

在一个全新进程上全量冷扫描 104 个数据集的实测分布（45 条样本）：

    124.83s  40112801.Blood.AIDA.h5ad
     67.99s  38548990.ILD.h5ad
     29.01s  39438660.IBD.h5ad
      4.09s  32832599.IPF.h5ad     ← 用户那次在旧进程里是 104s

前端 `apiFetch` 的 `timeoutMs` 默认 60_000（src/api/client.ts:4），到点 abort →
`.catch` 把 `setError('Failed to load info')`（AnalysisPage.tsx:116）。服务器 100 秒后
才 `_json(result)`，对端早已断开 → BrokenPipeError（routes.py:243 → handler.py:82）。

**全部 45 次都命中了 scanner-cache 快路径，h5ad 兜底分支一次都没跑** —— 所以慢的不是
读数据。唯一剩下的变价步骤就是那次外部抓取。

这里锁住三件事：
  1. `_fetch_abstract` 有**总时限**，预算耗尽就不再发下一次请求（旧的 per-socket 超时
     管不住「连接慢但没断」和「连发 3 次」这两种叠加，8+8+10 只是理论下界）；
  2. `handle_analysis_info` **完全不发网络**，摘要走缓存直读，另由一个端点按需抓；
  3. B26 的「失败不缓存」策略不能被本次改动破坏。

注意：全程 monkeypatch，不发起任何真实网络请求。
"""
import json
import socket
import sys
import tempfile
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

_fail = 0


def check(label: str, cond: bool, detail: str = '') -> None:
    global _fail
    if cond:
        print(f'  PASS  {label}')
    else:
        _fail += 1
        print(f'  FAIL  {label}' + (f'  — {detail}' if detail else ''))


import config
import pubmed
import routes


# ── 假 opener：记录每次请求的 URL 与它收到的 timeout ──────────────
class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def read1(self, n: int = -1) -> bytes:
        # 必须实现 —— 真实 HTTPResponse 有 read1，生产代码也走它。
        # 没有它的话，用这个假响应的用例会以 AttributeError 告终、
        # 被吞成「抓取失败」，断言就变成空的（已经踩过一次）。
        buf, self._payload = self._payload, b''
        return buf


class _FakeOpener:
    """`sleep` 模拟「代理很慢但连接没断」—— 这正是 per-socket 超时管不住的形态。"""

    def __init__(self, payload: bytes = b'{}', sleep: float = 0.0, raises: bool = False):
        self.payload = payload
        self.sleep = sleep
        self.raises = raises
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.timeouts.append(timeout if timeout is not None else -1)
        if self.sleep:
            time.sleep(self.sleep)
        if self.raises:
            raise socket.timeout('timed out')
        return _Resp(self.payload)

    def reset(self):
        self.urls.clear()
        self.timeouts.clear()


_orig_opener = pubmed._proxy_opener
_epmc_payload = json.dumps({
    'resultList': {'result': [{
        'title': 'T', 'abstractText': 'A', 'journalTitle': 'J',
        'authorString': 'X', 'pubYear': '2024', 'doi': 'd', 'pmcid': 'PMC123',
    }]},
}).encode()


# ── 1. 总时限：预算耗尽就不再发请求 ──────────────────────────────
print('\n[1] _fetch_abstract 的总时限（回归：改前 2 次 EuropePMC 各给 8s，无预算概念）')

_fake = _FakeOpener(raises=True)
pubmed._proxy_opener = _fake
try:
    _fake.reset()
    _t0 = time.monotonic()
    pubmed._fetch_abstract('90000001', deadline_s=0)
    _elapsed = time.monotonic() - _t0
    check('预算为 0 → 一次网络都不发', _fake.urls == [], f'实际请求了 {_fake.urls}')
    check('预算为 0 → 立即返回（不等任何超时）', _elapsed < 0.5, f'实际 {_elapsed:.2f}s')

    # 有预算时，opener 收到的 timeout 必须是**剩余预算**，不是写死的 8/10
    _fake.reset()
    pubmed._fetch_abstract('90000002', deadline_s=0.5)
    check('opener 收到的 timeout ≤ 总预算（不是写死的 8/10）',
          bool(_fake.timeouts) and all(t <= 0.5 + 1e-6 for t in _fake.timeouts),
          f'实际收到 {_fake.timeouts}')

    # 预算在 EuropePMC 阶段就烧光 → PMC 全文那一步不该再发
    _slow = _FakeOpener(payload=_epmc_payload, sleep=0.5)
    pubmed._proxy_opener = _slow
    pubmed._fetch_abstract('90000003', deadline_s=0.5)
    check('预算烧光后不再请求 PMC 全文（回归：改前无条件再发一次）',
          not any('eutils.ncbi' in u for u in _slow.urls), f'实际请求了 {_slow.urls}')
finally:
    pubmed._proxy_opener = _orig_opener


# ── 1b. 滴流响应：body 读不完时必须停在预算处 ────────────────────
# [1] 里「opener 收到的 timeout ≤ 总预算」这条**测不出真正的越界**：
# 滴流响应恰恰满足它（代码确实把 timeout 传小了），照样能跑满 59 秒。
# 那条断言看的是「传给 socket 的值」，不是「实际花掉的墙钟」。
print('\n[1b] 滴流响应下真实墙钟仍受预算约束（回归：改前 resp.read() 无上限）')


class _FakeClock:
    """假时钟 —— 不想为了复现 60 秒滴流真的等 60 秒。"""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _DripResp:
    """每次 read1 花 0.4s 吐 1 字节，永不 EOF。

    这正是 B35 里「代理连得上但很慢」的真实形态：per-socket timeout 永远不触发
    （每次 recv 都在超时前拿到数据），旧代码的 resp.read() 于是一路读到底 ——
    实测 60 字节 / 1 B/s 的响应在 deadline_s=2 下跑满 59.07s。
    """

    def __init__(self, clock):
        self.clock = clock
        self.calls = 0

    def read1(self, n):
        self.clock.sleep(0.4)
        self.calls += 1
        return b'x'

    def read(self, n=-1):
        """旧代码走的那条路（resp.read() 无上限）。实现出来，这样把 read1 改回
        read 的变异会被「读了 10000 次」抓住，而不是因为假响应没有 read 而
        以 AttributeError 告终 —— 后者虽然也是 FAIL，但证不出越界这件事。"""
        while self.calls < 10000:
            self.read1(n)
        return b'x' * self.calls


class _DripOpener:
    def __init__(self, clock):
        self.resp = _DripResp(clock)

    def open(self, req, timeout=None):
        return self.resp


_clock = _FakeClock()
_drip = _DripOpener(_clock)
_orig_time_mod = pubmed.time
pubmed.time = _clock
pubmed._proxy_opener = _drip
try:
    pubmed._fetch_abstract('90000010', deadline_s=2)
    # 预算 2s、每次 recv 0.4s → 读完第 5 次时恰好耗尽，应为 5 次左右
    check('滴流下 read1 调用次数有限，不是无限读',
          0 < _drip.resp.calls <= 8, f'实际 {_drip.resp.calls} 次（无限读说明预算失效）')
    check('滴流导致 body 没读完 → 不写缓存（B26）',
          '90000010' not in pubmed._EUROPE_PMC_CACHE, '被污染了')
finally:
    pubmed.time = _orig_time_mod
    pubmed._proxy_opener = _orig_opener


class _HtmlResp:
    """200 + 代理拦截页 —— 不是 XML，但旧代码会把它当成「全文抓到了」。"""

    def read1(self, n):
        return b'<html>Access Denied by proxy policy</html>'

    def read(self):
        return b'<html>Access Denied by proxy policy</html>'


class _HtmlOpener:
    def __init__(self, payload):
        self.payload = payload

    def open(self, req, timeout=None):
        return _Resp(self.payload) if 'europepmc' in req.full_url else _HtmlResp()


_xml_payload = json.dumps({
    'resultList': {'result': [{
        'title': 'T', 'abstractText': 'A', 'journalTitle': 'J',
        'authorString': 'X', 'pubYear': '2024', 'doi': 'd', 'pmcid': 'PMC999',
    }]},
}).encode()
pubmed._proxy_opener = _HtmlOpener(_xml_payload)
try:
    _info = pubmed._fetch_abstract('90000011', deadline_s=10)
    check('非 XML 的 200 响应不被当作「已获取全文」（不再谎称「确实没有补充材料」）',
          _info.get('supplementary_note') != 'none',
          f'实际 note={_info.get("supplementary_note")!r} —— "none" 是在断言这篇真没有附件')
    check('非 XML 响应 → 不写缓存，下次重试',
          '90000011' not in pubmed._EUROPE_PMC_CACHE, '被污染了')
finally:
    pubmed._proxy_opener = _orig_opener


# ── 2. B26 回归：失败仍然不缓存 ─────────────────────────────────
print('\n[2] 「失败不缓存」策略未被破坏（B26 回归）')

_fake = _FakeOpener(raises=True)
pubmed._proxy_opener = _fake
try:
    pubmed._fetch_abstract('90000004', deadline_s=0)
    check('超时/空结果不写入 _EUROPE_PMC_CACHE',
          '90000004' not in pubmed._EUROPE_PMC_CACHE, '被污染了')
finally:
    pubmed._proxy_opener = _orig_opener


# ── 3. handler 完全不发网络 ────────────────────────────────────
print('\n[3] handle_analysis_info 不发起外部抓取（回归：改前同步调 _fetch_abstract）')


class _FakeHandler:
    """只记录 _json / _send_error 调用，不碰 socket。"""

    def __init__(self):
        self.json: list = []
        self.errors: list[str] = []

    def _json(self, data, status=200):
        self.json.append(data)

    def _send_error(self, message, status=400):
        self.errors.append(message)


def _boom(*a, **kw):
    raise AssertionError('handle_analysis_info 不应发起外部抓取')


_tmpdir = Path(tempfile.mkdtemp())
_fake_h5 = _tmpdir / '99999999.IPF.h5ad'
_fake_h5.write_bytes(b'')
_fake_cache = _tmpdir / 'scanner_cache.json'
_fake_cache.write_text(json.dumps({
    str(_fake_h5): {'pmid': '99999999', 'n_obs': 123, 'n_vars': 45,
                    'patient_count': 2, 'sample_count': 3, 'celltype_count': 4},
}))

_orig_validate = routes.validate_real_path
_orig_cache_file = config.SCANNER_CACHE_FILE
_orig_handler_fetch = routes._fetch_abstract
routes.validate_real_path = lambda _s: _fake_h5
config.SCANNER_CACHE_FILE = _fake_cache
routes._fetch_abstract = _boom

try:
    h = _FakeHandler()
    routes.handle_analysis_info(h, {'pmid': '99999999', 'real_path': str(_fake_h5)})
    check('handler 在抓取被禁用时仍能正常返回', len(h.json) == 1 and not h.errors,
          f'json={len(h.json)} errors={h.errors}')
    _payload = h.json[0] if h.json else {}
    check('stats 仍然正确（本地快路径不受影响）',
          (_payload.get('stats') or {}).get('cells') == 123,
          f'实际 {_payload.get("stats")}')
    check('未缓存摘要 → abstract_ready 为 False',
          _payload.get('abstract_ready') is False, f'实际 {_payload.get("abstract_ready")!r}')

    # 已缓存的 pmid 必须直接带出摘要，且不产生任何网络行为
    pubmed._EUROPE_PMC_CACHE['99999999'] = {'title': '已缓存', 'abstract': 'x'}
    h2 = _FakeHandler()
    routes.handle_analysis_info(h2, {'pmid': '99999999', 'real_path': str(_fake_h5)})
    p2 = h2.json[0] if h2.json else {}
    check('已缓存 → abstract_ready 为 True',
          p2.get('abstract_ready') is True, f'实际 {p2.get("abstract_ready")!r}')
    check('已缓存 → 摘要内容随响应返回',
          (p2.get('abstract') or {}).get('title') == '已缓存',
          f'实际 {(p2.get("abstract") or {}).get("title")!r}')
    pubmed._EUROPE_PMC_CACHE.pop('99999999', None)
finally:
    routes.validate_real_path = _orig_validate
    config.SCANNER_CACHE_FILE = _orig_cache_file
    routes._fetch_abstract = _orig_handler_fetch


# ── 3b. scanner 缓存里有**不匹配**的条目时，仍要找得到正确的那条 ────
# 上面 [3] 的假缓存只有一个 key，而它恰好就是被查的那个 —— `str(real_path) in k`
# 一短路，第二个条件根本不求值，于是掩盖了一个真实缺陷：
# 原代码写的是 `k.endswith(str(real_path).name)`，对一个**字符串**取 .name。
# 遍历到任何一个不匹配的 key 都会抛 AttributeError，被 `except: pass` 吞掉，
# stats 退回 None，然后**整个 h5ad 文件被读一遍**（实测 6s~120s+）。
# 线上 104 个数据集，正确 key 前面永远排着别人，所以这条快路径从来没生效过。
print('\n[3b] scanner 缓存含不匹配条目时仍命中（回归：改前 .name 取在字符串上）')

_fake_h5_b = _tmpdir / '88888888.COPD.h5ad'
_fake_h5_b.write_bytes(b'')
_fake_cache_b = _tmpdir / 'scanner_cache_b.json'
# 故意把不匹配的条目排在最前 —— 复现线上「正确 key 前面总有别人」的真实形态
_fake_cache_b.write_text(json.dumps({
    str(_tmpdir / '11111111.OTHER.h5ad'): {'pmid': '11111111', 'n_obs': 7},
    str(_fake_h5_b): {'pmid': '88888888', 'n_obs': 456, 'n_vars': 78},
}))

_orig_cache_file = config.SCANNER_CACHE_FILE
_orig_validate = routes.validate_real_path
config.SCANNER_CACHE_FILE = _fake_cache_b
routes.validate_real_path = lambda _s: _fake_h5_b
try:
    hb = _FakeHandler()
    routes.handle_analysis_info(hb, {'pmid': '88888888', 'real_path': str(_fake_h5_b)})
    pb = hb.json[0] if hb.json else {}
    check('前面有不匹配条目时，仍从缓存取到本条',
          (pb.get('stats') or {}).get('cells') == 456,
          f'实际 {(pb.get("stats") or {}).get("cells")!r}（若为 h5ad 兜底的 0 则说明又快路径失败）')
finally:
    config.SCANNER_CACHE_FILE = _orig_cache_file
    routes.validate_real_path = _orig_validate


# ── 4. 摘要另有端点，且注册在路由表里 ──────────────────────────
print('\n[4] /api/abstract 端点')

check('/api/abstract 已注册', ('GET', '/api/abstract') in routes.ROUTES,
      f'路由表里没有；现有 GET 端点 {sorted(k[1] for k in routes.ROUTES if k[0] == "GET")[:6]}')

_handler = routes.ROUTES.get(('GET', '/api/abstract'))
if _handler:
    _fake = _FakeOpener(raises=True)
    pubmed._proxy_opener = _fake
    try:
        pubmed._EUROPE_PMC_CACHE['90000005'] = {'title': 'T5', 'abstract': 'A5'}
        h3 = _FakeHandler()
        _handler(h3, {'pmid': '90000005'})
        check('缓存命中 → 不发网络，直接返回',
              _fake.urls == [] and (h3.json[0].get('abstract') or {}).get('title') == 'T5',
              f'urls={_fake.urls} json={h3.json}')
        pubmed._EUROPE_PMC_CACHE.pop('90000005', None)

        _fake.reset()
        h4 = _FakeHandler()
        _handler(h4, {'pmid': '90000006'})
        check('缓存未命中 → 走抓取，且 opener 收到的是剩余预算而非写死值',
              bool(_fake.timeouts) and all(t <= config.ABSTRACT_DEADLINE_S + 1e-6
                                           for t in _fake.timeouts),
              f'收到 {_fake.timeouts}，上限 {config.ABSTRACT_DEADLINE_S}')
    finally:
        pubmed._proxy_opener = _orig_opener
else:
    check('端点 handler 可取到', False, 'ROUTES 里没有')

check('config.ABSTRACT_DEADLINE_S 是正数',
      isinstance(getattr(config, 'ABSTRACT_DEADLINE_S', None), (int, float))
      and config.ABSTRACT_DEADLINE_S > 0,
      f'实际 {getattr(config, "ABSTRACT_DEADLINE_S", None)!r}')


print()
if _fail:
    print(f'{_fail} 项失败')
    sys.exit(1)
print('ALL PASS')
