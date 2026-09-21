#!/usr/bin/env python3
"""药物流水线阶段注册表 —— 完整性回归测试。

盯的是「注册表说的」与「磁盘上真有的」对不对得上。这类表最容易出的不是逻辑错，
而是**手滑**：某个阶段写了个 `drug-doe-response`（实际目录叫 `drug-dose-response`），
或者移植了 skill 却忘了挂进任何阶段。前端渲染卡片不会报错，agent 也照跑不误 ——
只是那一阶段静默地少了一个 skill。所以这里逐条核对目录。

另一组盯的是流水线端点**在入参非法时给可读错误而不是崩**。药物页是新建的，
前端传参还没被真实使用验证过，空 stage_ids / 非法 id / 空 query 三条路径都要覆盖。

运行：python3 server/tests/test_drug_stages.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = SERVER_DIR / 'skills'
PROJECT_ROOT = SERVER_DIR.parent

sys.path.insert(0, str(SERVER_DIR))

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        PASS.append(label)
        print(f'  ✓ {label}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(label)
        print(f'  ✗ {label}  {detail}')


def _load_port_manifest() -> list[tuple[str, str]]:
    """从移植脚本里读 MANIFEST —— 而不是在这里再抄一份。

    抄一份的话这个测试就永远通过（它只跟自己比），也就测不出「移植脚本改了、
    注册表没跟」这种漂移。
    """
    src = (PROJECT_ROOT / 'scripts' / 'port_tooluniverse_skills.py').read_text(encoding='utf-8')
    m = re.search(r'^MANIFEST.*?=\s*\[(.*?)^\]', src, re.DOTALL | re.MULTILINE)
    if not m:
        raise RuntimeError('在 scripts/port_tooluniverse_skills.py 里找不到 MANIFEST')
    return re.findall(r"\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", m.group(1))


def run() -> None:
    import drug_stages as ds
    import llm_proxy

    # ── 1. 注册表自身完整性 ────────────────────────────────────────
    print('\n[1] 注册表结构')
    stages = ds.DRUG_STAGES
    ids = [s['id'] for s in stages]
    orders = [s['order'] for s in stages]
    check('阶段数为 6', len(stages) == 6, f'得到 {len(stages)}')
    check('阶段 id 唯一', len(ids) == len(set(ids)), f'ids={ids}')
    check('order 唯一', len(orders) == len(set(orders)), f'orders={orders}')
    check('order 从 1 连续到 6', sorted(orders) == list(range(1, len(stages) + 1)),
          f'orders={sorted(orders)}')
    check('STAGE_IDS 与 DRUG_STAGES 一致', ds.STAGE_IDS == tuple(ids))
    for s in stages:
        need = {'id', 'label', 'summary', 'focus', 'gap', 'skills'}
        check(f'{s.get("id", "?")} 字段齐全', need <= set(s), f'缺 {sorted(need - set(s))}')

    # ── 2. 声明的 skill 目录真实存在 ───────────────────────────────
    print('\n[2] 阶段声明的 skill 目录都存在且有 SKILL.md')
    declared = sorted({n for s in stages for n in s['skills']} | set(ds.DRUG_BASE_SKILLS))
    missing_dir = [n for n in declared if not (SKILLS_DIR / n / 'SKILL.md').is_file()]
    check(f'{len(declared)} 个声明的 skill 目录都存在', not missing_dir, f'缺失: {missing_dir}')
    # 再逐阶段报一遍，便于直接定位是哪一段写错了
    for s in stages:
        bad = [n for n in s['skills'] if not (SKILLS_DIR / n / 'SKILL.md').is_file()]
        check(f'阶段 {s["id"]} 的 {len(s["skills"])} 个 skill 都存在', not bad, f'缺失: {bad}')

    # ── 3. 阶段间 skill 不重复 ─────────────────────────────────────
    print('\n[3] 阶段之间不重复占用同一个 skill')
    seen: dict[str, str] = {}
    dupes = []
    for s in stages:
        for n in s['skills']:
            if n in seen:
                dupes.append(f'{n}（{seen[n]} + {s["id"]}）')
            seen[n] = s['id']
    check('没有 skill 同时挂在两个阶段', not dupes, '; '.join(dupes))
    check('常驻 skill 不与任何阶段重叠', not (set(ds.DRUG_BASE_SKILLS) & set(seen)),
          f'重叠: {sorted(set(ds.DRUG_BASE_SKILLS) & set(seen))}')

    # ── 4. 移植脚本的 MANIFEST 与注册表对得上 ──────────────────────
    print('\n[4] 移植 MANIFEST ↔ 注册表')
    # 早年手工移植的 skill —— 不在本次 MANIFEST 里，但阶段可以引用它们。
    # 列成显式名单而不是「忽略所有未知」：否则注册表里写错一个名字会被静默放过。
    _PRE_EXISTING = {'protein-modification-analysis'}
    try:
        manifest = _load_port_manifest()
        locals_ = {local for _, local in manifest}
        wired = set(declared)
        never_wired = sorted(locals_ - wired)
        not_ported = sorted(wired - locals_ - _PRE_EXISTING)
        stale = sorted(_PRE_EXISTING - wired)
        check(f'MANIFEST 的 {len(locals_)} 个落点都挂进了某个阶段', not never_wired,
              f'移植了但没挂进任何阶段: {never_wired}')
        check('注册表引用除既有 skill 外都在 MANIFEST 里', not not_ported,
              f'注册表引用了未移植的名字: {not_ported}')
        check('既有 skill 例外名单没有过期条目', not stale,
              f'已不再被任何阶段引用: {stale}')
    except Exception as e:
        check('能读到移植脚本的 MANIFEST', False, str(e))

    # ── 5. 移植产物的适配头与 frontmatter ──────────────────────────
    print('\n[5] 移植产物带适配头、name 已改写')
    drug_dirs = sorted(p for p in SKILLS_DIR.glob('drug-*') if p.is_dir())
    check(f'落点有 29 个 drug-* 目录', len(drug_dirs) == 29, f'得到 {len(drug_dirs)}')
    no_header = [d.name for d in drug_dirs
                 if '⚠️ GenSci 执行适配' not in (d / 'SKILL.md').read_text(encoding='utf-8')]
    check('每个 drug-* 都带「⚠️ GenSci 执行适配」头', not no_header, f'缺头: {no_header}')

    # 「frontmatter name 等于目录名」已移入 test_skill_spec_conformance.py ——
    # 那边覆盖全部 82 个 skill（含这 29 个 drug-*），此处不再重复一份。

    readme = SKILLS_DIR / 'drug-README.md'
    check('drug-README.md 记录来源与许可证',
          readme.is_file() and 'Apache-2.0' in readme.read_text(encoding='utf-8'))

    # ── 6. 过滤器 ────────────────────────────────────────────────
    print('\n[6] skill 过滤器')
    check("OMICS_SKILL_FILTERS 有 'Drug' 条目", 'Drug' in llm_proxy.OMICS_SKILL_FILTERS,
          f'现有的: {sorted(llm_proxy.OMICS_SKILL_FILTERS)}')

    # 复刻 agent/__init__.py:244-250 的 _match_filter，验证 'drug-*' 确实命中所有落点。
    # 它是 process_chat_streaming 里的闭包，取不到，只能复刻 —— 所以下面同时断言
    # 「阶段锁定确实比通配符窄」，万一那边改了语义这里能察觉到退化。
    def _match_filter(name: str, filters) -> bool:
        for f in filters:
            if f.endswith('*') and name.startswith(f[:-1]):
                return True
            if name == f:
                return True
        return False

    all_names = {d.name for d in drug_dirs}
    glob_hits = {n for n in all_names if _match_filter(n, llm_proxy.OMICS_SKILL_FILTERS['Drug'])}
    check("'drug-*' 命中全部 29 个落点", glob_hits == all_names,
          f'漏掉: {sorted(all_names - glob_hits)}')

    for s in stages:
        flt = ds.skills_filter_for(s)
        check(f'阶段 {s["id"]} 的 filter = 本阶段 skill + 常驻',
              set(flt) == set(s['skills']) | set(ds.DRUG_BASE_SKILLS), f'{flt}')
    check('每个阶段的 filter 都比全量 drug-* 窄（阶段锁定有意义）',
          all(len(ds.skills_filter_for(s)) < len(drug_dirs) for s in stages))

    # ── 7. resolve_stages ────────────────────────────────────────
    print('\n[7] resolve_stages')
    picked, unknown = ds.resolve_stages(['safety', 'target'])
    check('顺序无关：按 order 排成 target → safety',
          [s['id'] for s in picked] == ['target', 'safety'],
          f'得到 {[s["id"] for s in picked]}')
    check('合法的 id 不产生 unknown', unknown == [], f'unknown={unknown}')

    picked, _ = ds.resolve_stages(['target', 'target', 'design'])
    check('重复 id 去重', [s['id'] for s in picked] == ['target', 'design'],
          f'得到 {[s["id"] for s in picked]}')

    picked, unknown = ds.resolve_stages(['target', 'nope', 'alsonope'])
    check('非法 id 收进 unknown 且不静默丢弃',
          unknown == ['nope', 'alsonope'] and [s['id'] for s in picked] == ['target'],
          f'picked={[s["id"] for s in picked]} unknown={unknown}')

    picked, unknown = ds.resolve_stages([])
    check('空列表返回空阶段、无 unknown', picked == [] and unknown == [])
    picked, unknown = ds.resolve_stages(None)
    check('None 不崩', picked == [] and unknown == [])

    # ── 8. build_stage_message ───────────────────────────────────
    print('\n[8] 阶段消息组装')
    st = ds.get_stage('target')
    msg = ds.build_stage_message(st, 'EGFR')
    check('含任务原文', 'EGFR' in msg)
    check('含阶段标题与序号', '阶段 1/6：靶点与机制发现' in msg)
    check('含本阶段 focus', st['focus'][:20] in msg)
    check('含本阶段 gap', st['gap'][:20] in msg)
    check('含硬性要求', '【硬性要求】' in msg)
    check('无前序时不出现「前序阶段结论」小节', '【前序阶段结论' not in msg)

    st6 = ds.get_stage('safety')
    msg6 = ds.build_stage_message(st6, 'EGFR', [('靶点与机制发现', '上一阶段的结论正文')])
    check('有前序时带上前一阶段标题与正文',
          '【前序阶段结论' in msg6 and '上一阶段的结论正文' in msg6)
    check('第 6 阶段的 gap 明确排除 IND 申报文档',
          'IND/CTA/eCTD 申报文档撰写' in msg6)

    huge = '甲' * 20000
    msg_big = ds.build_stage_message(st, 'EGFR', [(f'阶段{i}', huge) for i in range(1, 6)])
    check('前序总预算封顶（5×20000 字符不会全带进去）', len(msg_big) < 20000,
          f'得到 {len(msg_big)} 字符')
    check('超额时显式说明省略，不静默截断', '省略' in msg_big)

    trimmed = ds._trim('A' * 1000, 100)
    check('_trim 保留头尾', trimmed.startswith('A') and trimmed.endswith('A')
          and len(trimmed) < 1000, f'长度 {len(trimmed)}')
    check('_trim 未超限时原样返回', ds._trim('短文本', 100) == '短文本')

    # ── 9. stages_payload ────────────────────────────────────────
    print('\n[9] /api/drug/stages 的响应体')
    payload = ds.stages_payload()
    check('顶层三个字段', set(payload) == {'stages', 'baseSkills', 'capabilityNote'},
          f'{sorted(payload)}')
    check('capabilityNote 明确列出 IND 申报文档写不了',
          'IND/CTA/eCTD 申报文档撰写' in payload['capabilityNote'])
    check('payload 可 JSON 序列化', isinstance(json.dumps(payload, ensure_ascii=False), str))
    fields = set(payload['stages'][0])
    check('每个阶段只暴露前端要用的字段',
          fields == {'id', 'order', 'label', 'summary', 'skills', 'gap'}, f'{sorted(fields)}')

    # ── 10. 端点入参校验（不起 HTTP server，直接调 handler） ────────
    print('\n[10] 端点入参校验')

    class _ReachedSSE(Exception):
        """哨兵：handler 走到了发响应头那一步。

        `_stream_sse_response` 一旦 send_response 就没法再改回 JSON 错误了
        （routes.py:647-648 写明了这个约定），所以这里在 send_response 处掐断 ——
        既证明「校验确实跑在发头之前」，又不用真去 mock wfile / connection。
        """

    class _FakeHandler:
        """只记录 _send_error / _json 调用，不碰 socket。"""
        def __init__(self):
            self.errors: list[str] = []
            self.json: list = []
            self._allowed_origins: list[str] = []

        def _send_error(self, message, status=400):
            self.errors.append(message)

        def _json(self, data, status=200):
            self.json.append(data)

        def send_response(self, *a, **k):
            raise _ReachedSSE

    from routes import handle_drug_pipeline_stream, handle_drug_stages
    base = {'api_key': 'sk-test', 'base_url': 'https://api.deepseek.com'}

    h = _FakeHandler()
    handle_drug_pipeline_stream(h, {**base, 'stage_ids': ['target']})
    check('空 query → 可读错误而非崩', h.errors == ['query required'], f'{h.errors}')

    h = _FakeHandler()
    handle_drug_pipeline_stream(h, {**base, 'query': 'EGFR', 'stage_ids': []})
    check('空 stage_ids → 可读错误', bool(h.errors) and 'stage_ids' in h.errors[0], f'{h.errors}')

    h = _FakeHandler()
    handle_drug_pipeline_stream(h, {**base, 'query': 'EGFR'})
    check('缺 stage_ids → 可读错误', bool(h.errors) and 'stage_ids' in h.errors[0], f'{h.errors}')

    h = _FakeHandler()
    handle_drug_pipeline_stream(h, {'query': 'EGFR', 'stage_ids': ['target'],
                                    'api_key': '', 'base_url': 'https://api.deepseek.com'})
    check('缺 api_key 且非本地 → 可读错误', h.errors == ['api_key required'], f'{h.errors}')

    h = _FakeHandler()
    reached = False
    try:
        handle_drug_pipeline_stream(h, {**base, 'query': 'EGFR', 'stage_ids': ['target']})
    except _ReachedSSE:
        reached = True
    check('合法入参不报错、且确实走到了发 SSE 响应头那一步',
          reached and h.errors == [], f'reached={reached} errors={h.errors}')

    h2 = _FakeHandler()
    handle_drug_stages(h2, {})
    check('GET /api/drug/stages 直接返回 payload',
          len(h2.json) == 1 and len(h2.json[0]['stages']) == 6,
          f'返回 {len(h2.json[0]["stages"]) if h2.json else 0} 个阶段')

    # 编排的 SSE 事件序列在 test_drug_pipeline_events.py —— 那是另一个关注点
    # （monkeypatch 内层 LLM、断言事件顺序），不混进这份静态注册表校验里。

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL drug stage CHECK PASSED')


if __name__ == '__main__':
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
