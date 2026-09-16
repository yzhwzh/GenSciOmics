#!/usr/bin/env python3
"""药物流水线编排的 SSE 事件序列 —— 用假 LLM 跑，不碰网络。

`process_drug_pipeline_streaming` 是唯一把「6 个独立 ReAct 循环」缝成一条流水线
的地方，缝错了不会报错，只会静默地错：

  - 内层的 `done` 若不拦，前端会以为整条流水线在第一个阶段就结束了；
  - 上一阶段的结论若没带进下一阶段，第 2 阶段等于从零开始 —— 用户看到的是
    6 段各说各话，而这恰恰是「流水线」相对「6 次独立对话」的全部价值；
  - 内层出错若不中止，后面的阶段会拿着空摘要继续跑，把垃圾结论一路传下去。

这三条都是「看起来在跑、实际白跑」，只能用事件序列断言锁住。

这里**不测**注册表本身的完整性（阶段 id / skill 目录 / 过滤器）——
那是 test_drug_stages.py 的职责。

运行：python3 server/tests/test_drug_pipeline_events.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
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


def run() -> None:
    import agent
    import drug_stages as ds
    import llm_proxy

    _real = agent.process_chat_streaming
    calls: list[dict] = []

    def _events(**kw):
        """跑一次流水线，把 SSE 事件还原成 [(event, payload), ...]。"""
        return [(e['event'], json.loads(e['data']))
                for e in llm_proxy.process_drug_pipeline_streaming(**kw)]

    def _ok_stream(**kw):
        calls.append(kw)
        yield {'event': 'message', 'data': {'content': '假回复'}}
        yield {'event': 'turn_complete', 'data': {'content': '假回复'}}
        yield {'event': 'done', 'data': {'final': True}}

    def _boom_stream(**kw):
        calls.append(kw)
        yield {'event': 'error', 'data': {'error': 'API error: 502'}}

    def _silent_stream(**kw):
        """内层没发 done 就结束了 —— agent 的错误路径就是这么 return 的。"""
        calls.append(kw)
        yield {'event': 'message', 'data': {'content': '半截话'}}

    # ── 1. 入参非法时不推进、也不调 LLM ────────────────────────────
    print('\n[1] 入参非法：不进入任何阶段')
    agent.process_chat_streaming = _ok_stream
    try:
        ev = _events(query='EGFR', stage_ids=['nope'], api_key='sk-test')
        check('非法 stage id → 单个 error 事件',
              len(ev) == 1 and ev[0][0] == 'error' and 'nope' in ev[0][1]['error'], f'{ev}')
        check('非法 stage id → 完全没调内层 LLM', calls == [], f'调了 {len(calls)} 次')

        calls.clear()
        ev = _events(query='   ', stage_ids=['target'], api_key='sk-test')
        check('空白 query → error 事件', len(ev) == 1 and ev[0][0] == 'error', f'{ev}')
        check('空白 query → 没调内层 LLM', calls == [], f'调了 {len(calls)} 次')

        calls.clear()
        ev = _events(query='EGFR', stage_ids=[], api_key='sk-test')
        check('空 stage_ids → error 事件（不是静默空跑）',
              len(ev) == 1 and ev[0][0] == 'error', f'{ev}')
        check('空 stage_ids → 没调内层 LLM', calls == [], f'调了 {len(calls)} 次')

        # 合法与非法混传：整个请求拒绝，不跑合法的那些 —— 半条流水线的结论没有意义
        calls.clear()
        ev = _events(query='EGFR', stage_ids=['target', 'nope'], api_key='sk-test')
        check('合法+非法混传 → 整体拒绝，不跑「能跑的那部分」',
              len(ev) == 1 and ev[0][0] == 'error' and calls == [], f'{ev} 调了 {len(calls)} 次')

        # ── 2. 正常两阶段 ─────────────────────────────────────────
        print('\n[2] 正常两阶段：事件序列与上下文传递')
        calls.clear()
        ev = _events(query='EGFR', stage_ids=['safety', 'target'], api_key='sk-test')
        names = [e for e, _ in ev]

        check('事件以 stage_start 开头、以 done 结尾',
              names[0] == 'stage_start' and names[-1] == 'done', f'{names}')
        check('每阶段恰好一对 stage_start/stage_done',
              names.count('stage_start') == 2 and names.count('stage_done') == 2
              and names.count('stage_start') == names.count('stage_done'), f'{names}')
        check('内层的 done 不外发，整条流水线只有末尾一个 done',
              names.count('done') == 1, f'{names}')

        # 顺序：前端按 stage_start 推进进度条，错序会显示成乱跳
        starts = [d for e, d in ev if e == 'stage_start']
        check('stage_start 按 order 排序（target 在 safety 前）',
              [s['stage_id'] for s in starts] == ['target', 'safety'],
              f'{[s["stage_id"] for s in starts]}')
        check('stage_start 带 index/total 供前端画进度',
              [(s['index'], s['total']) for s in starts] == [(1, 2), (2, 2)],
              f'{[(s["index"], s["total"]) for s in starts]}')

        check('每个事件都带 stage_id（后端已补）',
              all('stage_id' in d for _, d in ev if _ != 'done'),
              f'{[(e, d.get("stage_id")) for e, d in ev if e != "done"]}')
        check('message 事件的 stage_id 标注正确',
              [d['stage_id'] for e, d in ev if e == 'message'] == ['target', 'safety'],
              f'{[d["stage_id"] for e, d in ev if e == "message"]}')

        check('按 order 执行 —— 第一次内层调用用的是 target 的 filter',
              calls and calls[0]['skills_filter'] == ds.skills_filter_for(ds.get_stage('target')),
              f'实际：{calls[0]["skills_filter"] if calls else None}')
        check('阶段锁定生效 —— 两次调用的 filter 不同',
              len(calls) == 2 and calls[0]['skills_filter'] != calls[1]['skills_filter'],
              f'{len(calls)} 次调用')
        check('每阶段只调一次内层（不是每阶段跑两遍）', len(calls) == 2, f'{len(calls)} 次')

        # ── 3. 上一阶段结论带进下一阶段 ────────────────────────────
        print('\n[3] 前序结论传递')
        second = calls[1]['messages'][0]['content']
        check('第 2 阶段的消息里带上了第 1 阶段的结论',
              '前序阶段结论' in second and '假回复' in second,
              f'第 2 阶段消息开头：{second[:60]!r}')
        check('第 1 阶段的消息里没有「前序阶段结论」小节（它是第一段）',
              '前序阶段结论' not in calls[0]['messages'][0]['content'])
        check('第 2 阶段仍是单条 user message（不是把前序塞成额外轮次）',
              len(calls[1]['messages']) == 1
              and calls[1]['messages'][0]['role'] == 'user',
              f'{len(calls[1]["messages"])} 条')

        done_payload = ev[-1][1]
        check('done 报告跑了 2 个阶段、未中止',
              done_payload['stages_run'] == 2 and done_payload['aborted'] is False,
              f'{done_payload}')
        check('stage_done 带耗时与摘要长度',
              all({'elapsed_ms', 'summary_chars'} <= set(d)
                  for e, d in ev if e == 'stage_done'),
              f'{[d for e, d in ev if e == "stage_done"]}')

        # ── 4. 内层报错：中止而非带病续跑 ──────────────────────────
        print('\n[4] 内层报错：立刻中止，不把垃圾摘要传给下一阶段')
        calls.clear()
        agent.process_chat_streaming = _boom_stream
        ev = _events(query='EGFR', stage_ids=['target', 'design', 'safety'], api_key='sk-test')
        names = [e for e, _ in ev]
        sd = [d for e, d in ev if e == 'stage_done']

        check('出错的阶段 stage_done 标 error 并带上原因',
              len(sd) == 1 and sd[0]['status'] == 'error' and '502' in sd[0]['error'], f'{sd}')
        check('出错的阶段仍有 stage_start（前端进度条不会卡在上一段）',
              names.count('stage_start') == 1, f'{names}')
        check('内层出错 → 后续阶段不再执行', len(calls) == 1, f'{len(calls)} 次')
        check('内层出错 → error 事件如实外发（不吞掉）', 'error' in names, f'{names}')
        check('内层出错 → 末尾 done 标 aborted',
              ev[-1][1]['aborted'] is True and ev[-1][1]['stages_run'] == 0, f'{ev[-1][1]}')
        check('内层出错 → 仍然以 done 收尾（前端有确定的结束信号）',
              names[-1] == 'done', f'{names}')

        # ── 5. 内层没发 done 就结束：同样按失败处理 ────────────────
        # agent 的错误路径是 `return` 而非 yield error，所以「没有 done」是唯一的信号。
        # 不当失败处理的话，这一阶段会带着空摘要进入下一阶段。
        print('\n[5] 内层静默结束（没有 done）：按失败处理')
        calls.clear()
        agent.process_chat_streaming = _silent_stream
        ev = _events(query='EGFR', stage_ids=['target', 'safety'], api_key='sk-test')
        sd = [d for e, d in ev if e == 'stage_done']

        check('没有 done → stage_done 标 error',
              len(sd) == 1 and sd[0]['status'] == 'error', f'{sd}')
        check('没有 done → 错误信息说明是内层没结束',
              bool(sd) and 'done' in sd[0].get('error', ''), f'{sd[0].get("error") if sd else None}')
        check('没有 done → 后续阶段不再执行', len(calls) == 1, f'{len(calls)} 次')
        check('没有 done → 末尾 done 标 aborted', ev[-1][1]['aborted'] is True, f'{ev[-1][1]}')

        # ── 6. 单阶段也要有完整的一对事件 ─────────────────────────
        print('\n[6] 单阶段')
        calls.clear()
        agent.process_chat_streaming = _ok_stream
        ev = _events(query='EGFR', stage_ids=['mechanism'], api_key='sk-test')
        names = [e for e, _ in ev]
        check('单阶段也是 start → … → done 的完整结构',
              names[0] == 'stage_start' and names.count('stage_done') == 1
              and names[-1] == 'done', f'{names}')
        check('单阶段的 index/total = 1/1',
              [d for e, d in ev if e == 'stage_start'][0]['index'] == 1
              and [d for e, d in ev if e == 'stage_start'][0]['total'] == 1)
    finally:
        agent.process_chat_streaming = _real

    print(f'\nPASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('FAILED: ' + ', '.join(FAIL))
        sys.exit(1)
    print('ALL drug pipeline event CHECK PASSED')


if __name__ == '__main__':
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
