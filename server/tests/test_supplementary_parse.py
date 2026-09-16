#!/usr/bin/env python3
"""补充材料（supplementary）解析回归测试 —— 全程离线，不碰网络。

背景：Study Info 页面要显示「这篇文献有没有公开的样本信息表」。附件清单来自
PMC 全文 XML 里的 <supplementary-material>，而那份 XML 是 pubmed._fetch_abstract
为了提取 Methods 已经下载过的 —— 所以解析本身零额外网络成本。

但解析结果会直接决定页面上给用户看什么，写错了会静默误导：

  · 判据太松 → 满屏 ★，等于没判；
  · 判据太窄 → 真正的患者表被埋在一堆 figure 里；
  · 去重漏了 → 同一份文件显示两遍（PMC 的 XML 里确实存在重复条目，
    PMC10306289 有 4 个 <supplementary-material> 但只有 2 个文件）。

因此下面的 fixture 全部取自真实抓到的 XML，包括一个**反例**：
`aba1972_Table_S9.xlsx` 名字里带 "Table"，打开却是 motif 表，
而 `mmc2.xlsx` 才是真正的患者信息表。文件名不可靠这件事必须锁进测试。

运行：python3 server/tests/test_supplementary_parse.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

_failures = 0


def check(label: str, got, want) -> None:
    global _failures
    if got == want:
        print(f'  ok   {label}')
    else:
        _failures += 1
        print(f'  FAIL {label}\n       got  {got!r}\n       want {want!r}')


# ── fixture：真实抓到的 XML 片段 ──────────────────────────────
# 形态照抄 PMC7439444（Science Advances），caption 在 <title> 里。
XML_ABA = '''
<body>
<supplementary-material id="PMC_1" content-type="local-data" position="float">
  <caption><title>aba1972_Table_S9.xlsx</title></caption>
  <media mimetype="application" mime-subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet"
         xlink:href="aba1972_Table_S9.xlsx"/>
</supplementary-material>
<supplementary-material id="PMC_2" content-type="local-data" position="float">
  <caption><title>aba1972_Table_S2.csv</title></caption>
  <media mimetype="text" mime-subtype="plain" xlink:href="aba1972_Table_S2.csv"/>
</supplementary-material>
<supplementary-material id="PMC_3" content-type="local-data" position="float">
  <caption><title>aba1972_SM.pdf</title></caption>
  <media mimetype="application" mime-subtype="pdf" xlink:href="aba1972_SM.pdf"/>
</supplementary-material>
<supplementary-material id="PMC_4" content-type="local-data" position="float">
  <media mimetype="image" mime-subtype="gif" xlink:href="aba1972-F1.gif"/>
</supplementary-material>
</body>
'''

# 形态照抄 PMC10306289：caption 在 <p> 里，且同一文件重复出现两次
# （第二次的 id 带 db_ds_..._reqid_ 后缀）—— 去重如果漏了就会显示两遍。
XML_DUP = '''
<supplementary-material id="supplementary-material2" position="float">
  <caption><p>Data files S1 to S6</p></caption>
  <media xlink:href="sciadv.abq7599_tables_s1_to_s6.zip" mimetype="application"/>
</supplementary-material>
<supplementary-material id="db_ds_supplementary-material2_reqid_" position="float">
  <caption><p>Data files S1 to S6</p></caption>
  <media xlink:href="sciadv.abq7599_tables_s1_to_s6.zip" mimetype="application"/>
</supplementary-material>
'''

# 真正的「样本信息表」：三种真实 caption 写法各一条
XML_SAMPLE = '''
<supplementary-material id="s1"><caption><p>Table S1. Patient and sample information, related to Figure 1</p></caption>
  <media xlink:href="mmc2.xlsx" mimetype="application"/></supplementary-material>
<supplementary-material id="s2"><caption><title>Table S1. Donor summaries.</title></caption>
  <media xlink:href="NIHMS1856632-supplement-SUPPL_TABLE_1.xlsx" mimetype="application"/></supplementary-material>
<supplementary-material id="s3"><caption><p>Demographic and biochemical characteristics of patients with IgAN</p></caption>
  <media xlink:href="Table_1.xlsx" mimetype="application"/></supplementary-material>
<supplementary-material id="s4"><caption><p>Clinical characteristics of samples analyzed by scRNA-seq</p></caption>
  <media xlink:href="NIHMS1754019-supplement-2.xlsx" mimetype="application"/></supplementary-material>
'''

# 反例：名字里有 Table，内容是 motif 表，不是样本信息
XML_NOT_SAMPLE = '''
<supplementary-material id="n1"><caption><title>aba1972_Table_S9.xlsx</title></caption>
  <media xlink:href="aba1972_Table_S9.xlsx" mimetype="application"/></supplementary-material>
<supplementary-material id="n2"><caption><title>SOX_motifs</title></caption>
  <media xlink:href="aba1983_Data_S5.txt" mimetype="text"/></supplementary-material>
'''

# PMC8085501（IgAN，真实数据集 Data/Human/Kidney/IgAN 那一篇）的**原样 caption**。
# 这组是加 SAMPLE_EXCLUDE 的原因：只用正向词时 12 条里有 9 条命中，
# 其中 6 条是 DEG 表，因为它们的 caption 里都有 "…control subjects"。
# 星标 75% 命中 = 没有信号，所以这里把「必须不命中」的逐条锁死。
XML_IGAN_REAL = '''
<supplementary-material id="r1"><caption><p>Demographic and biochemical characteristics of patients with IgAN.</p></caption>
  <media xlink:href="Table_1.xlsx"/></supplementary-material>
<supplementary-material id="r2"><caption><p>Number and viability of cells in kidney from each sample.</p></caption>
  <media xlink:href="Table_2.xlsx"/></supplementary-material>
<supplementary-material id="r3"><caption><p>DEGs in cell subtypes of glomerulus comparing IgAN and control subjects.</p></caption>
  <media xlink:href="Table_3.xlsx"/></supplementary-material>
<supplementary-material id="r4"><caption><p>DEGs in tubular cells from IgAN and control subjects.</p></caption>
  <media xlink:href="Table_4.xlsx"/></supplementary-material>
<supplementary-material id="r5"><caption><p>DEGs in different cell clusters of kidney from IgAN patients with overt proteinuria.</p></caption>
  <media xlink:href="Table_6.xlsx"/></supplementary-material>
<supplementary-material id="r6"><caption><p>Top 20 marker genes of each cell type shown in heatmap</p></caption>
  <media xlink:href="Table_7.xls"/></supplementary-material>
<supplementary-material id="r7"><caption><p>Cell number of distinct clusters in kidney from each subject</p></caption>
  <media xlink:href="Table_8.xlsx"/></supplementary-material>
<supplementary-material id="r8"><caption><p>Detailed information about DEGs in each cell cluster in kidney from IgAN and control subjects.</p></caption>
  <media xlink:href="Table_9.xls"/></supplementary-material>
<supplementary-material id="r9"><caption><p>Gene ontology enrichment analysis for individual cell types performed with the cluster Profiler R package.</p></caption>
  <media xlink:href="Table_11.xlsx"/></supplementary-material>
<supplementary-material id="r10"><caption><p>Kyoto encyclopedia of genes and genomes (KEGG) enrichment analysis for individual cell types performed with the cluster Profiler R package.</p></caption>
  <media xlink:href="Table_12.xlsx"/></supplementary-material>
'''

# 这一篇里**应该**打星的（逐条核对过内容是样本信息）
IGAN_SHOULD_STAR = {'Table_1.xlsx', 'Table_2.xlsx', 'Table_8.xlsx'}

# XML 实体必须解码，否则页面上会直接显示 &amp;
XML_ESCAPED = '''
<supplementary-material id="e1">
  <caption><p>Clinical &amp; demographic data for donors &lt;18 yrs</p></caption>
  <media xlink:href="supp1.xlsx" mimetype="application"/>
</supplementary-material>
'''

XML_NO_SUPP = '<body><sec><title>Methods</title><p>We did things.</p></sec></body>'

# 截断的 XML：真实场景下的网络半包。不能抛异常，只能少给几条。
XML_TRUNCATED = '''
<supplementary-material id="t1"><caption><p>Table S1</p></caption>
  <media xlink:href="a.xlsx"/>
<supplementary-material id="t2"><caption><p>Table S2</p></caption>
'''

print('parse_supplementary')

from supplementary import (  # noqa: E402
    parse_supplementary, supplementary_note, _safe_member_name, read_table_file,
    is_valid_lookup, MAX_ROWS,
)

items = parse_supplementary(XML_ABA)
check('提取到 4 条附件', len(items), 4)
check('name 取自 href 的文件名', items[0]['name'], 'aba1972_Table_S9.xlsx')
check('caption 取自 <title>', items[0]['caption'], 'aba1972_Table_S9.xlsx')
check('xlsx 判为 table', items[0]['kind'], 'table')
check('csv 判为 table', items[1]['kind'], 'table')
check('pdf 判为 file', items[2]['kind'], 'file')
check('gif 判为 figure', items[3]['kind'], 'figure')
check('无 caption 时不崩、caption 为空串', items[3]['caption'], '')

print()
print('caption 在 <p> 里（另一种真实形态）')

dup = parse_supplementary(XML_DUP)
check('同一文件名出现两次只保留一条', len(dup), 1)
check('保留的是第一次出现的条目', dup[0]['name'], 'sciadv.abq7599_tables_s1_to_s6.zip')
check('caption 取自 <p>', dup[0]['caption'], 'Data files S1 to S6')

print()
print('is_sample_hint —— 正例')

for it in parse_supplementary(XML_SAMPLE):
    check(f'样本表命中: {it["name"]}', it['is_sample_hint'], True)

print()
print('is_sample_hint —— 反例（文件名不可靠，必须不漏判也要不过判）')

for it in parse_supplementary(XML_NOT_SAMPLE):
    check(f'非样本表不命中: {it["name"]}', it['is_sample_hint'], False)

print()
print('is_sample_hint —— 真实数据集 PMC8085501（IgAN）的原样 caption')

real_items = parse_supplementary(XML_IGAN_REAL)
check('12 条里解析出 10 条', len(real_items), 10)
for it in real_items:
    check(f'  星标判定: {it["name"]}', it['is_sample_hint'], it['name'] in IGAN_SHOULD_STAR)
starred = [it['name'] for it in real_items if it['is_sample_hint']]
check('命中数收敛到 3（原为 9，等于没信号）', sorted(starred), sorted(IGAN_SHOULD_STAR))
check('一条都没被隐藏', len(real_items), 10)

print()
print('XML 实体解码')

esc = parse_supplementary(XML_ESCAPED)
check('caption 里的 &amp; 被解码', esc[0]['caption'], 'Clinical & demographic data for donors <18 yrs')

print()
print('无附件 / 畸形 XML')

check('没有 <supplementary-material> 时返回空列表', parse_supplementary(XML_NO_SUPP), [])
check('空字符串不崩', parse_supplementary(''), [])
check('截断的 XML 不抛异常', isinstance(parse_supplementary(XML_TRUNCATED), list), True)

print()
print('supplementary_note —— 三种「没有」必须可区分')

check('无 PMCid → no-pmcid（我们没能力检查）', supplementary_note(False, False, 0), 'no-pmcid')
check('抓取失败 → error（可以重试）', supplementary_note(True, False, 0), 'error')
check('拿到了但确实没有 → none', supplementary_note(True, True, 0), 'none')
check('有附件 → 无提示', supplementary_note(True, True, 3), '')

print()
print('_safe_member_name —— 路径穿越守卫')

check('普通文件名放行', _safe_member_name('Table_1.xlsx'), 'Table_1.xlsx')
check('带连字符/下划线放行', _safe_member_name('aba1972-Table_S9.xlsx'), 'aba1972-Table_S9.xlsx')
check('拒 .. 相对穿越', _safe_member_name('../../etc/passwd'), None)
check('拒中间夹 .. ', _safe_member_name('a/../../etc/passwd'), None)
check('拒绝对路径', _safe_member_name('/etc/passwd'), None)
check('拒带斜杠的相对路径', _safe_member_name('sub/Table_1.xlsx'), None)
check('拒反斜杠', _safe_member_name('sub\\Table_1.xlsx'), None)
check('拒空串', _safe_member_name(''), None)
check('拒 . 开头（隐藏文件）', _safe_member_name('.htaccess'), None)

print()
print('is_valid_lookup —— 路由靠它决定回 400 还是 200')

check('正常组合放行', is_valid_lookup('PMC7439444', 'Table_1.xlsx'), True)
check('pmcid 少了 PMC 前缀 → 拒', is_valid_lookup('7439444', 'Table_1.xlsx'), False)
check('pmcid 混入路径 → 拒', is_valid_lookup('../../etc', 'Table_1.xlsx'), False)
check('pmcid 为空 → 拒', is_valid_lookup('', 'Table_1.xlsx'), False)
check('附件名穿越 → 拒', is_valid_lookup('PMC7439444', '../../etc/passwd'), False)
check('附件名带斜杠 → 拒', is_valid_lookup('PMC7439444', 'a/../../b.xlsx'), False)
check('附件名为空 → 拒', is_valid_lookup('PMC7439444', ''), False)

print()
print('read_table_file —— csv')


def csv_bytes(rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerows(rows)
    return buf.getvalue().encode()


basic = read_table_file('t.csv', csv_bytes([
    ['SampleID', 'Group', 'Age'],
    ['IgAN-01', 'Case', '32'],
    ['IgAN-02', 'Control', '41'],
]))
check('csv 单 sheet', len(basic['sheets']), 1)
check('sheet 名取文件名', basic['sheets'][0]['name'], 't')
check('首行作表头', basic['sheets'][0]['columns'], ['SampleID', 'Group', 'Age'])
check('数据行数正确', len(basic['sheets'][0]['rows']), 2)
check('数据行内容正确', basic['sheets'][0]['rows'][0], ['IgAN-01', 'Case', '32'])
check('未截断', basic['truncated'], False)

big = read_table_file('big.csv', csv_bytes(
    [['id', 'v']] + [[str(i), str(i * 2)] for i in range(MAX_ROWS + 25)]
))
check(f'超过 {MAX_ROWS} 行被截断', len(big['sheets'][0]['rows']), MAX_ROWS)
check('截断被如实标注（不静默）', big['truncated'], True)

empty = read_table_file('empty.csv', b'')
check('空 csv 不崩', empty['sheets'][0]['rows'], [])

print()
print('read_table_file —— xlsx（内存里现造，不落盘）')

from openpyxl import Workbook  # noqa: E402


def xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = 'Patient'
    ws.append(['SampleID', 'Group', 'Age'])
    ws.append(['IgAN-01', 'Case', 32])
    ws.append(['IgAN-02', 'Control', 41])
    ws2 = wb.create_sheet('Sample')
    ws2.append(['Sample', 'Cells'])
    ws2.append(['S1', 1200])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


xl = read_table_file('t.xlsx', xlsx_bytes())
check('xlsx 两个 sheet 都保留', [s['name'] for s in xl['sheets']], ['Patient', 'Sample'])
check('sheet 名取自工作簿', xl['sheets'][0]['name'], 'Patient')
check('xlsx 表头正确', xl['sheets'][0]['columns'], ['SampleID', 'Group', 'Age'])
check('xlsx 数值保持数值类型', xl['sheets'][0]['rows'][0], ['IgAN-01', 'Case', 32])
check('第二个 sheet 独立', xl['sheets'][1]['rows'], [['S1', 1200]])

print()
print('read_table_file —— 不支持的类型给错误，不抛')

unsupported = read_table_file('paper.pdf', b'%PDF-1.4 junk')
check('不支持的扩展名返回 error 而非抛异常', 'error' in unsupported, True)
check('error 有可读文案', bool(unsupported.get('error')), True)

bad = read_table_file('broken.xlsx', b'not really an xlsx')
check('损坏的 xlsx 返回 error 而非抛异常', 'error' in bad, True)

print()
if _failures:
    print(f'{_failures} check(s) failed')
    sys.exit(1)
print('all checks passed')
