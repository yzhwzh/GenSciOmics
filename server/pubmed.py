#!/usr/bin/env python3
"""EuropePMC abstract fetching with caching. Proxy-first, short timeouts."""

import html
import json
import re
import sys
import time
import urllib.request

from config import HTTP_PROXY, ABSTRACT_DEADLINE_S
from supplementary import parse_supplementary, supplementary_note


# Cache: key = pmid, value = dict
_EUROPE_PMC_CACHE: dict[str, dict] = {}

# 单次 socket 操作的超时。**它管不住整次请求** —— 这是 per-recv 的，对端只要
# 慢到「每个 recv 间隔内吐得出一个字节」就能让它永远不触发。实测 60 字节 / 1 B/s
# 的滴流响应，在 deadline_s=2 下照样跑满 59s（BUG_LOG B35）。
# 真正封顶的是 _read_bounded()：它逐次 recv 地查预算，预算用完就放弃本次 body。
_PER_CALL_TIMEOUT_S = 8   # EuropePMC 单次
_PMC_TIMEOUT_S = 10       # NCBI PMC 全文单次

_READ_CHUNK_BYTES = 64 * 1024
_MAX_BODY_BYTES = 8 * 1024 * 1024   # 正常 body（含 PMC 全文 XML）都 < 1MB，这是防呆上限


def _read_bounded(resp, remaining) -> bytes | None:
    """分块读 body，每次 recv 之间查预算。预算耗尽返回 None（body 不完整）。

    为什么不能用 resp.read()：urllib 的 timeout 是**单个 socket 操作**的超时，
    不是整个 body 的。对端持续滴流时 read() 会一路读到底，`min(budget, 8)` 那点
    约束完全落空。read1() 保证每次只消费一次 recv，循环才有机会真正查预算。

    最坏超时 = 剩余预算 + 一次 socket 操作（≤ _PER_CALL_TIMEOUT_S），
    因为掐表的那次 recv 已经在飞了、收不回来。
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        if remaining() <= 0:
            return None
        buf = resp.read1(_READ_CHUNK_BYTES)
        if not buf:
            return b''.join(chunks)
        total += len(buf)
        if total > _MAX_BODY_BYTES:
            return b''.join(chunks)
        chunks.append(buf)


def cached_abstract(pmid: str) -> dict | None:
    """**只读**摘要缓存，绝不发网络。未命中返回 None。

    给 /api/analysis-info 用：那个端点必须立刻返回（前端 60s 就 abort），
    摘要改由 /api/abstract 按需抓。见 BUG_LOG B35。
    """
    return _EUROPE_PMC_CACHE.get(pmid)

# Reusable proxy opener — proxy first, no direct-attempt fallback
_proxy_handler = urllib.request.ProxyHandler({'http': HTTP_PROXY, 'https': HTTP_PROXY})
_proxy_opener = urllib.request.build_opener(_proxy_handler)


def _fetch_abstract(pmid: str, deadline_s: float | None = None) -> dict:
    """Fetch abstract and metadata from EuropePMC, cached by PMID.
    Proxy-first. PMC full text is best-effort.

    deadline_s —— **整次抓取**的墙钟上限（秒），None 则用 config.ABSTRACT_DEADLINE_S。
    每个 open() 拿到的是 `min(剩余预算, 单次上限)`，预算耗尽就不再发下一个请求。
    为什么不能只靠 socket timeout：代理「连得上但很慢」时单次 timeout 拦不住，
    而这里最多串 3 次请求，8+8+10 只是理论下界 —— 实测单次抓到过 125s（BUG_LOG B35）。
    """
    if pmid in _EUROPE_PMC_CACHE:
        return _EUROPE_PMC_CACHE[pmid]

    if deadline_s is None:
        deadline_s = ABSTRACT_DEADLINE_S
    _t0 = time.monotonic()

    def _remaining() -> float:
        return deadline_s - (time.monotonic() - _t0)

    info = {'title': '', 'abstract': '', 'journal': '', 'authors': '', 'year': '',
            'doi': '', 'methods': '', 'results': ''}

    # Skip non-PubMed IDs (PKU, BALF, brain-map, etc.)
    if not pmid or not pmid.strip().isdigit():
        _EUROPE_PMC_CACHE[pmid] = info
        return info

    # EuropePMC — proxy first, single attempt per URL
    candidates = [
        f'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=ext_id:{pmid}&resultType=core&pageSize=1&format=json',
        f'https://www.ebi.ac.uk/europepmc/api/search?query=EXT_ID:{pmid}&resultType=core&format=json',
    ]

    pmcid = None
    epmc_hit = False  # EuropePMC 是否真的返回了记录（区别于「查了但没查到」）
    for url in candidates:
        budget = _remaining()
        if budget <= 0:
            print(f'[GenSci] EuropePMC fetch skipped for {pmid}: 预算耗尽', file=sys.stderr)
            break
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            resp = _proxy_opener.open(req, timeout=min(budget, _PER_CALL_TIMEOUT_S))
            raw = _read_bounded(resp, _remaining)
            if raw is None:
                # 预算在读 body 的过程中耗尽。这条不能当成「查无此文」——
                # 它只是没读完，下一次请求要重来（B26：不写缓存）。
                print(f'[GenSci] EuropePMC body read aborted for {pmid}: 预算耗尽', file=sys.stderr)
                break
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            data = json.loads(raw)

            results = data.get('resultList', {}).get('result', [])
            if not results:
                results = data.get('results', [])
            if not results and 'entries' in data:
                results = [data['entries']]

            if results:
                r = results[0] if isinstance(results, list) else results
                info = {
                    'title': r.get('title', ''),
                    'abstract': r.get('abstractText', '') or r.get('abstract', ''),
                    'journal': r.get('journalTitle', '') or r.get('journal', ''),
                    'authors': r.get('authorString', '') or r.get('authorString', ''),
                    'year': str(r.get('pubYear', '') or r.get('year', '')),
                    'doi': r.get('doi', ''),
                    'methods': '',
                    'results': '',
                    # 补充材料清单占位。真正的内容要等全文 XML 拿到后才填，
                    # 但这两个键必须先存在 —— 否则「查过、确实没有」和
                    # 「这个字段这个版本还没有」在返回值上无法区分。
                    'supplementary': [],
                    'supplementary_note': '',
                }
                pmcid = r.get('pmcid', '')
                if pmcid:
                    info['pmcid'] = pmcid
                epmc_hit = True
                break
        except Exception as e:
            # 不静默：EuropePMC 抓取失败时，上层只会看到一个空记录 +
            # abstract_ready=false，看不出是「查无此文」还是「网络挂了」。
            # 这条日志是唯一能分辨两者的地方（CLAUDE.md 设计决策 #4）。
            print(f'[GenSci] EuropePMC fetch failed for {pmid} '
                  f'({url.split("?")[0]}): {type(e).__name__}: {e}', file=sys.stderr)
            continue

    # PMC full text — best-effort, bounded by whatever budget is left
    pmc_error = False
    pmc_skipped = False  # 预算在 EuropePMC 阶段就烧光了，全文那一步压根没发出去
    xml_text = ''
    xml_ok = False  # 全文 XML 是否真的拿到了（决定补充材料是「没有」还是「没查成」）
    if pmcid and _remaining() <= 0:
        pmc_skipped = True
        print(f'[GenSci] PMC full text skipped for {pmid}: 预算耗尽', file=sys.stderr)
    if pmcid and not pmc_skipped:
        try:
            budget = _remaining()
            url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid}&retmode=xml'
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            resp = _proxy_opener.open(req, timeout=min(budget, _PMC_TIMEOUT_S))
            body = _read_bounded(resp, _remaining)
            if body is None:
                raise TimeoutError('PMC 全文读取超出预算')
            xml_text = body.decode('utf-8', errors='replace')
            # 只有**看起来像文章 XML** 才算拿到全文。xml_ok 以前的含义是
            # 「read() 返回了」—— 代理拦截页、限流页、eutils 的 <error> 文档
            # 全都是 HTTP 200，于是「这次没抓成」被缓存成了「这篇确实没有
            # 补充材料」，还顺手写进 supplementary_note 当事实讲给用户。
            # 这与 B35 的成因同类：失败必须留下失败的痕迹。
            if '<article' not in xml_text[:8192]:
                raise ValueError(f'PMC 返回的不是文章 XML（前 120 字节: {xml_text[:120]!r}）')
            xml_ok = True

            def _extract_sec(xml: str, title: str, max_len: int = 5000) -> str:
                """Extract text from a <sec> with given title."""
                pat = re.compile(
                    r'<title>[^<]*' + re.escape(title) + r'[^<]*</title>\s*',
                    re.IGNORECASE
                )
                m = pat.search(xml)
                if not m:
                    pat = re.compile(
                        r'<title>[^<]*' + re.escape(title[:5]) + r'.*?</title>\s*',
                        re.IGNORECASE
                    )
                    m = pat.search(xml)
                if not m:
                    return ''
                start = m.end()
                depth, pos = 1, start
                while depth > 0 and pos < len(xml):
                    ot = xml.find('<sec', pos)
                    ct = xml.find('</sec>', pos)
                    if ct == -1:
                        break
                    if ot != -1 and ot < ct:
                        depth += 1
                        pos = ot + 4
                    else:
                        depth -= 1
                        pos = ct + 6
                if depth != 0:
                    return ''
                content = xml[start:pos - 6]
                content = re.sub(r'<title>(.*?)</title>', r'\n▸ \1\n', content, flags=re.DOTALL)
                content = re.sub(r'<[^>]+>', '', content)
                content = html.unescape(content)
                content = re.sub(r'\n\s*\n', '\n\n', content).strip()
                return content[:max_len]

            methods = _extract_sec(xml_text, 'Methods', 100000)
            results_text = ''

            # Fallback: extract from abstract subsections
            if not methods or not results_text:
                abs_text = info.get('abstract', '')
                sec_pattern = re.compile(
                    r'(?:^|\n)\s*(Methods?|Results?|Background|Introduction|Discussion|Conclusions?)\s*[:.]?\s*\n?(.*?)(?=\n\s*(?:Methods?|Results?|Background|Introduction|Discussion|Conclusions?)\s*[:.]?|\Z)',
                    re.IGNORECASE | re.DOTALL
                )
                for m in sec_pattern.finditer(abs_text):
                    sec_title = m.group(1).lower()
                    sec_content = re.sub(r'\s+', ' ', m.group(2)).strip()
                    if sec_content:
                        if not methods and 'method' in sec_title:
                            methods = sec_content[:2000]
                        elif not results_text and 'result' in sec_title:
                            results_text = sec_content[:2000]

            info['methods'] = methods
            info['results'] = results_text
        except Exception as pmc_err:
            pmc_error = True
            print(f'[GenSci] PMC fetch error: {pmc_err}', file=sys.stderr)

    # ── 补充材料清单 ─────────────────────────────────────────
    # 零额外网络成本：XML 上面为了提取 Methods 已经下载过了，这里只是
    # 把同一份再解析一遍，挑出 <supplementary-material>。
    # 清单本身只是「有没有」；附件内容要另走 /api/supplementary-table 按需取。
    if epmc_hit:
        try:
            items = parse_supplementary(xml_text) if xml_ok else []
        except Exception as supp_err:
            # 解析失败不该毁掉整条记录（methods 还是好的），但也不能装作没有
            items = []
            print(f'[GenSci] supplementary parse error: {supp_err}', file=sys.stderr)
        info['supplementary'] = items
        info['supplementary_note'] = supplementary_note(bool(pmcid), xml_ok, len(items))

    # 只缓存"有记录/已完整"的结果：若整次抓取为空(网络/代理瞬时失败)、PMC 全文抓取出错，
    # 或全文那一步因预算耗尽压根没发出去，不写缓存、下次请求重试——否则一次瞬时故障
    # 会让该 PMID 永久返回空(需重启服务才恢复)。
    has_record = bool(info['title'] or info['abstract'] or info.get('pmcid'))
    incomplete = (pmc_error and not info['methods']) or pmc_skipped
    if has_record and not incomplete:
        _EUROPE_PMC_CACHE[pmid] = info
    return info
