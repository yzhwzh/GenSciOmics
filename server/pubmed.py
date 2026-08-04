#!/usr/bin/env python3
"""EuropePMC abstract fetching with caching."""

import html
import json
import re
import sys
import urllib.request

from config import HTTP_PROXY


# Cache: key = pmid, value = dict
_EUROPE_PMC_CACHE: dict[str, dict] = {}


def _fetch_abstract(pmid: str) -> dict:
    """Fetch abstract and metadata from EuropePMC, cached by PMID.
    Also tries to extract Methods from PMC full text if available."""
    if pmid in _EUROPE_PMC_CACHE:
        return _EUROPE_PMC_CACHE[pmid]

    info = {'title': '', 'abstract': '', 'journal': '', 'authors': '', 'year': '',
            'doi': '', 'methods': '', 'results': ''}

    # Try EuropePMC first
    candidates = [
        f'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=ext_id:{pmid}&resultType=core&pageSize=1&format=json',
        f'http://www.ebi.ac.uk/europepmc/webservices/rest/search?query=ext_id:{pmid}&resultType=core&pageSize=1&format=json',
        f'https://www.ebi.ac.uk/europepmc/api/search?query=EXT_ID:{pmid}&resultType=core&format=json',
    ]

    pmcid = None
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            try:
                resp = urllib.request.urlopen(req, timeout=6)
            except Exception:
                # Fallback: explicit proxy handler
                proxy_handler = urllib.request.ProxyHandler(
                    {'http': HTTP_PROXY, 'https': HTTP_PROXY}
                )
                opener = urllib.request.build_opener(proxy_handler)
                resp = opener.open(req, timeout=8)

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
                }
                pmcid = r.get('pmcid', '')
                if pmcid:
                    info['pmcid'] = pmcid
                break
        except Exception:
            continue

    # Try to get Methods & Results from PMC full text
    if pmcid:
        try:
            url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid}&retmode=xml'
            req = urllib.request.Request(url, headers={'User-Agent': 'GenSci/1.0'})
            try:
                resp = urllib.request.urlopen(req, timeout=8)
            except Exception:
                proxy_handler = urllib.request.ProxyHandler(
                    {'http': HTTP_PROXY, 'https': HTTP_PROXY}
                )
                opener = urllib.request.build_opener(proxy_handler)
                resp = opener.open(req, timeout=10)

            xml_text = resp.read().decode('utf-8')

            def _extract_sec(xml: str, title: str, max_len: int = 5000) -> str:
                """Extract text from a <sec> with given title, handling nested <sec> properly."""
                # Find section title - search for keyword anywhere in <title>text</title>
                pat = re.compile(
                    r'<title>[^<]*' + re.escape(title) + r'[^<]*</title>\s*',
                    re.IGNORECASE
                )
                m = pat.search(xml)
                if not m:
                    # Partial match (first 5 chars) anywhere in <title>text</title>
                    pat = re.compile(
                        r'<title>[^<]*' + re.escape(title[:5]) + r'.*?</title>\s*',
                        re.IGNORECASE
                    )
                    m = pat.search(xml)
                if not m:
                    return ''
                start = m.end()
                # Depth-track to find matching </sec>
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
                # Keep sub-section headers with bold-like markers
                content = re.sub(r'<title>(.*?)</title>', r'\n▸ \1\n', content, flags=re.DOTALL)
                # Strip remaining XML tags
                content = re.sub(r'<[^>]+>', '', content)
                content = html.unescape(content)
                content = re.sub(r'\n\s*\n', '\n\n', content).strip()
                return content[:max_len]

            methods = _extract_sec(xml_text, 'Methods', 100000)  # full text
            results_text = ''

            # Also try extracting from abstract subsections if full text sections not found
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
            print(f'[GenSci] PMC fetch error: {pmc_err}', file=sys.stderr)
            import traceback
            traceback.print_exc()

    _EUROPE_PMC_CACHE[pmid] = info
    return info
