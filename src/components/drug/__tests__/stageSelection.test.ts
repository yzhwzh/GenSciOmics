import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import type { DrugStage } from '../../../api/types'
import {
  DRUG_STAGE_KEY,
  toggleStage,
  selectAllStages,
  isAllSelected,
  orderSelected,
  loadSelection,
  saveSelection,
  initProgress,
  applyStageEvent,
  progressSummary,
} from '../stageSelection'

/**
 * 这里是药物页「哪些阶段会跑」的全部判断逻辑。它错了不会抛异常 ——
 * 只会安静地少跑一段，而一段流水线要跑十几分钟，用户不会立刻发现。
 * 所以勾选、排序、刷新后恢复这三条路径都直接钉在测试里。
 */

const stage = (id: string, order: number, label = id): DrugStage => ({
  id, order, label, summary: '', skills: [], gap: '',
})

// 故意不按 order 排列，用来验证 orderSelected 是真的在排序而不是照抄入参顺序
const STAGES: DrugStage[] = [
  stage('safety', 6, '安评与注册情报'),
  stage('target', 1, '靶点与机制发现'),
  stage('design', 2, '药物设计'),
]

describe('勾选', () => {
  it('未选中时加入，已选中时移除', () => {
    expect(toggleStage([], 'target')).toEqual(['target'])
    expect(toggleStage(['target'], 'target')).toEqual([])
    expect(toggleStage(['target'], 'design')).toEqual(['target', 'design'])
  })

  it('返回新数组，不改原数组', () => {
    const before = ['target']
    const after = toggleStage(before, 'design')
    expect(before).toEqual(['target'])
    expect(after).not.toBe(before)
  })

  it('全选选中所有阶段 id', () => {
    expect(selectAllStages(STAGES)).toEqual(['safety', 'target', 'design'])
  })

  it('全选判断在「少一个」时为假 —— 否则「全选」按钮会显示成已完成状态', () => {
    expect(isAllSelected(['target', 'design', 'safety'], STAGES)).toBe(true)
    expect(isAllSelected(['target', 'design'], STAGES)).toBe(false)
    expect(isAllSelected([], STAGES)).toBe(false)
  })

  it('注册表为空时不算「全选」（避免空列表显示成全选）', () => {
    expect(isAllSelected([], [])).toBe(false)
  })
})

describe('排序', () => {
  it('按注册表顺序输出，而非用户点击顺序', () => {
    expect(orderSelected(['safety', 'target'], STAGES)).toEqual(['target', 'safety'])
  })

  it('忽略选中集合里的未知 id', () => {
    expect(orderSelected(['target', 'ghost'], STAGES)).toEqual(['target'])
  })
})

describe('刷新后恢复', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => sessionStorage.clear())

  it('原样取回上次的勾选', () => {
    saveSelection(['target', 'safety'])
    expect(loadSelection(STAGES)).toEqual(['target', 'safety'])
  })

  it('丢弃注册表里已不存在的 id', () => {
    // 阶段被改名/删除后留下的旧值。原样回填会让用户看到一个勾不掉的幽灵阶段，
    // 而且点运行会被后端 resolve_stages() 判为 unknown 而整条拒绝。
    sessionStorage.setItem(DRUG_STAGE_KEY, JSON.stringify(['target', 'retired-stage']))
    expect(loadSelection(STAGES)).toEqual(['target'])
  })

  it('坏 JSON 不抛异常，退回空选择', () => {
    sessionStorage.setItem(DRUG_STAGE_KEY, '{not json')
    expect(loadSelection(STAGES)).toEqual([])
  })

  it('非数组的合法 JSON 也退回空选择', () => {
    sessionStorage.setItem(DRUG_STAGE_KEY, JSON.stringify({ stage: 'target' }))
    expect(loadSelection(STAGES)).toEqual([])
  })

  it('没有存过时返回空数组', () => {
    expect(loadSelection(STAGES)).toEqual([])
  })
})

describe('进度归约', () => {
  it('初始全为 pending，顺序按注册表', () => {
    const p = initProgress(STAGES, ['safety', 'target'])
    expect(p.map(x => x.stageId)).toEqual(['target', 'safety'])
    expect(p.every(x => x.status === 'pending')).toBe(true)
    expect(p[0]).toMatchObject({ label: '靶点与机制发现', index: 0, total: 2 })
    expect(p[1]).toMatchObject({ index: 1, total: 2 })
  })

  it('stage_start 把该阶段标为 running，不动其它阶段', () => {
    const p = initProgress(STAGES, ['target', 'safety'])
    const next = applyStageEvent(p, 'stage_start', { stage_id: 'safety' })
    expect(next[0].status).toBe('pending')
    expect(next[1].status).toBe('running')
  })

  it('stage_done(ok) 记下耗时', () => {
    let p = initProgress(STAGES, ['target'])
    p = applyStageEvent(p, 'stage_start', { stage_id: 'target' })
    p = applyStageEvent(p, 'stage_done', { stage_id: 'target', status: 'ok', elapsed_ms: 12345 })
    expect(p[0]).toMatchObject({ status: 'ok', elapsedMs: 12345 })
  })

  it('stage_done(error) 带上后端给的原因', () => {
    let p = initProgress(STAGES, ['target'])
    p = applyStageEvent(p, 'stage_done', {
      stage_id: 'target', status: 'error', error: 'API error: 502',
    })
    expect(p[0].status).toBe('error')
    expect(p[0].error).toBe('API error: 502')
  })

  it('error 没带原因时给个兜底文案，不显示空白', () => {
    let p = initProgress(STAGES, ['target'])
    p = applyStageEvent(p, 'stage_done', { stage_id: 'target', status: 'error' })
    expect(p[0].error).toBeTruthy()
  })

  it('未知 stage_id 被忽略，不凭空插入新格子', () => {
    const p = initProgress(STAGES, ['target'])
    expect(applyStageEvent(p, 'stage_start', { stage_id: 'ghost' })).toEqual(p)
  })

  it('缺 stage_id 的事件被忽略（done / 心跳等）', () => {
    const p = initProgress(STAGES, ['target'])
    expect(applyStageEvent(p, 'done', { final: true })).toEqual(p)
  })

  it('message / tool_call 等不改变进度', () => {
    const p = initProgress(STAGES, ['target'])
    expect(applyStageEvent(p, 'message', { stage_id: 'target', content: '...' })).toEqual(p)
  })

  it('归约返回新对象，不改原数组（React 才不会漏渲染）', () => {
    const p = initProgress(STAGES, ['target'])
    const next = applyStageEvent(p, 'stage_start', { stage_id: 'target' })
    expect(p[0].status).toBe('pending')
    expect(next).not.toBe(p)
    expect(next[0]).not.toBe(p[0])
  })
})

describe('进度文案', () => {
  it('只数 ok，error 与 running 不算完成', () => {
    let p = initProgress(STAGES, ['target', 'safety', 'design'])
    p = applyStageEvent(p, 'stage_done', { stage_id: 'target', status: 'ok' })
    p = applyStageEvent(p, 'stage_done', { stage_id: 'safety', status: 'error' })
    p = applyStageEvent(p, 'stage_start', { stage_id: 'design' })
    expect(progressSummary(p)).toBe('1 / 3 阶段完成')
  })
})
