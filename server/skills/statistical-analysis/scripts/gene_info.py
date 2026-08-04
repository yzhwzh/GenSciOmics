"""Query gene function via MyGene.info API.
Usage: python3 gene_info.py <gene1,gene2,...> [species]
"""
import sys, urllib.request, json, urllib.parse
genes = sys.argv[1]
species = sys.argv[2] if len(sys.argv) > 2 else 'human'
query = urllib.parse.quote(genes.replace(',', ' '))
url = f'https://mygene.info/v3/query?q={query}&fields=symbol,name,summary,pathways,uniprot&species={species}'
try:
    resp = urllib.request.urlopen(url, timeout=15)
    for hit in json.loads(resp.read()).get('hits', []):
        pw = hit.get('pathways', {})
        paths = list(set(v.get('name','') for src in pw.values() for v in (src if isinstance(src, list) else [src])))
        print(f"{hit.get('symbol')}: {hit.get('name')}")
        print(f"  Summary: {(hit.get('summary') or 'N/A')[:300]}")
        print(f"  Pathways: {', '.join(paths[:5]) if paths else 'N/A'}")
        print(f"  UniProt: {hit.get('uniprot',{}).get('Swiss-Prot','N/A')}")
except Exception as e:
    print(f'Error: {e}')
