#!/usr/bin/env python3
"""EuropePMC abstract fetching with caching. Proxy-first, short timeouts."""

import html
import json
import re
import sys
import urllib.request

from config import HTTP_PROXY
from supplementary import parse_supplementary, supplementary_note


# Cache: key = pmid, value = dict
_EUROPE_PMC_CACHE: dict[str, dict] = {}

# Reusable proxy opener — proxy first, no direct-attempt fallback
_proxy_handler = urllib.request.ProxyHandler({'http': HTTP_PROXY, 'https': HTTP_PROXY})
_proxy_opener = urllib.request.build_opener(_proxy_handler)


def _fetch_abstract(pmid: str) -> dict:
    """Fetch abstract and metadata from EuropePMC, cached by PMID.
    Proxy-first with short timeouts. PMC full text is best-effort."""
    if pmid in _EUROPE_PMC_CACHE:
        return _EUROPE_PMC_CACHE[pmid]

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
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            resp = _proxy_opener.open(req, timeout=8)
            raw = resp.read()
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
        except Exception:
            continue

    # PMC full text — best-effort, short timeout
    pmc_error = False
    xml_text = ''
    xml_ok = False  # 全文 XML 是否真的拿到了（决定补充材料是「没有」还是「没查成」）
    if pmcid:
        try:
            url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid}&retmode=xml'
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            resp = _proxy_opener.open(req, timeout=10)
            xml_text = resp.read().decode('utf-8')
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

    # 只缓存"有记录/已完整"的结果：若整次抓取为空(网络/代理瞬时失败)或 PMC 全文抓取出错，
    # 不写缓存、下次请求重试——否则一次瞬时故障会让该 PMID 永久返回空(需重启服务才恢复)。
    has_record = bool(info['title'] or info['abstract'] or info.get('pmcid'))
    if has_record and not (pmc_error and not info['methods']):
        _EUROPE_PMC_CACHE[pmid] = info
    return info
