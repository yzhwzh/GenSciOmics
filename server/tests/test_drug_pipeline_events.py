#!/usr/bin/env python3
"""药物流水线编排的 SSE 事件序列 —— 用假 LLM 跑，不碰网络。

`process_drug_pipeline_streaming` 是唯一把「6 个独立 ReAct 循环」缝成一条流水线
的地方，缝错了不会报错，只会静默地错：

  - 内层的 `done` 若不拦，前端会以为整条流水线在第一个阶段就结束了；
  - 上一阶段的结论若没带进下一阶段，第 2 阶段等于从零开始 —— 用户看到的是
    6 段各说各话，而这恰恰是「流水线」相对「6 次独立对话」的全部价值；
  - 内层**明确报错**后若继续跑，却不告诉下一阶段「上一环缺了」，后者会当作上游
    已产出，交出一份读起来很完整的报告 —— 缺的是数据，不是措辞；
  - 内层**静默**结束（没发 done）则必须中止：那说明这一段是半途断的，
    `final_text` 可能只是半截叙事，下游会把它当结论用。

两条失败路径形态不同、处置也不同（见 [4] 与 [5]）：前者跳过该阶段继续跑，
但把「未完成」显式写进下游 prompt；后者直接停下。

这些都是「看起来在跑、实际白跑」，只能用事件序列断言锁住。

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

    def _boom_on_target(**kw):
        """只让第 1 阶段（靶点）炸，后面照常成功。

        必须只炸一段：三段全炸的话就没有「成功阶段的结论」可验证，
        「失败标记往下传」和「正常结论往下传」这两条会分不开。
        """
        calls.append(kw)
        if 'drug-target-intelligence' in (kw.get('skills_filter') or []):
            # 报错前先吐半截内容 —— 真实世界里 error 常发生在跑了几轮工具之后，
            # 此时 final_text 非空。若实现把它当结论传下去，这个 '半截话' 就会
            # 出现在下一阶段的 prompt 里。
            yield {'event': 'message', 'data': {'content': '半截话'}}
            yield {'event': 'turn_complete', 'data': {'content': '半截话'}}
            yield {'event': 'error', 'data': {'error': 'API error: 502'}}
            return
        yield {'event': 'message', 'data': {'content': '假回复'}}
        yield {'event': 'turn_complete', 'data': {'content': '假回复'}}
        yield {'event': 'done', 'data': {'final': True}}

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

        # ── 4. 内层明确报错：跳过失败阶段，继续跑剩下的 ─────────────
        # 与 [5] 的关键区别：报错时该阶段**不进** prior_summaries 的结论位，下游拿到
        # 的是「这一环缺了」而不是半截摘要 —— 所以继续跑是安全的，且能保住后面几段。
        print('\n[4] 内层报错：跳过失败阶段，继续跑后续阶段')
        calls.clear()
        agent.process_chat_streaming = _boom_on_target
        ev = _events(query='EGFR', stage_ids=['target', 'design', 'safety'], api_key='sk-test')
        names = [e for e, _ in ev]
        sd = [d for e, d in ev if e == 'stage_done']

        check('出错的阶段 stage_done 标 error 并带上原因',
              bool(sd) and sd[0]['status'] == 'error' and '502' in sd[0]['error'], f'{sd}')
        # 前三段都开了头 —— 前端进度条不会缺格（applyStageEvent 按 stage_id 定位）
        check('三个阶段都发了 stage_start',
              names.count('stage_start') == 3, f'{names}')
        check('内层出错 → 后续阶段继续执行', len(calls) == 3, f'{len(calls)} 次')
        check('内层出错 → error 事件如实外发（不吞掉）', 'error' in names, f'{names}')

        # 关键：下一阶段的 prompt 里必须**显式**说明上一环没产出。
        # 否则它与「用户压根没勾这一段」无法区分，模型会交出一份读起来很完整的报告。
        second_msg = calls[1]['messages'][0]['content']
        check('下一阶段的消息里显式标注上一阶段未完成',
              '未完成' in second_msg and '靶点与机制发现' in second_msg,
              f'含「未完成」={"未完成" in second_msg}，'
              f'含失败阶段名={"靶点与机制发现" in second_msg}')
        # 半截叙事绝不能被当作结论 —— 这是「继续跑」这个决定成立的前提
        check('失败阶段的半截内容没有被当成结论混进去',
              '半截话' not in second_msg,
              f'含半截内容={"半截话" in second_msg}')
        check('失败阶段在前序结论里只占那一格（没有额外塞内容）',
              second_msg.count('### ') == 1,
              f'「### 小节」出现 {second_msg.count("### ")} 次，应为 1（只有失败标记）')

        # 再下一段要同时看到两样：上上段的失败标记（跨阶段继续传）+ 上一段的真结论
        third_msg = calls[2]['messages'][0]['content']
        check('失败标记跨阶段继续往下传', '未完成' in third_msg,
              f'含「未完成」={"未完成" in third_msg}')
        check('成功阶段的结论照常往下传', '假回复' in third_msg,
              f'含上一段结论={"假回复" in third_msg}')

        check('done 记下失败阶段、不标 aborted（流水线跑到了头）',
              ev[-1][1]['aborted'] is False and ev[-1][1]['failed'] == ['target']
              and ev[-1][1]['stages_run'] == 2, f'{ev[-1][1]}')
        check('内层出错 → 仍然以 done 收尾（前端有确定的结束信号）',
              names[-1] == 'done', f'{names}')

        # ── 5. 内层没发 done 就结束：必须中止 ──────────────────────
        # 与 [4] 相反：这里不知道内层为什么停的，final_text 可能只是半截叙事，
        # 当成结论往下传会把垃圾一路带下去。所以这一段维持中止。
        print('\n[5] 内层静默结束（没有 done）：中止')
        calls.clear()
        agent.process_chat_streaming = _silent_stream
        ev = _events(query='EGFR', stage_ids=['target', 'safety'], api_key='sk-test')
        sd = [d for e, d in ev if e == 'stage_done']

        check('没有 done → stage_done 标 error',
              len(sd) == 1 and sd[0]['status'] == 'error', f'{sd}')
        check('没有 done → 错误信息说明是内层没结束',
              bool(sd) and 'done' in sd[0].get('error', ''), f'{sd[0].get("error") if sd else None}')
        check('没有 done → 后续阶段不再执行', len(calls) == 1, f'{len(calls)} 次')
        check('没有 done → 末尾 done 标 aborted 并记下失败阶段',
              ev[-1][1]['aborted'] is True and ev[-1][1]['failed'] == ['target'], f'{ev[-1][1]}')

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
