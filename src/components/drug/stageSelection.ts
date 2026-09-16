import type { DrugStage, DrugStageProgress } from '../../api/types'

/**
 * 药物流水线的纯状态逻辑 —— 勾选、持久化、进度归约。
 *
 * 单独成模块（而不是塞进组件）是为了能直接测：这里的每条规则错了都不会报错，
 * 只会导致「点全选少勾一个」「刷新后选择错乱」「进度条永远停在第一段」这类
 * 只能靠手动发现的问题。
 */

/** sessionStorage key。与既有 gensci_* 命名一致。 */
export const DRUG_STAGE_KEY = 'gensci_drug_stages'

export function toggleStage(selected: string[], id: string): string[] {
  return selected.includes(id) ? selected.filter(s => s !== id) : [...selected, id]
}

export function selectAllStages(stages: DrugStage[]): string[] {
  return stages.map(s => s.id)
}

export function isAllSelected(selected: string[], stages: DrugStage[]): boolean {
  return stages.length > 0 && stages.every(s => selected.includes(s.id))
}

/**
 * 把选中项按注册表顺序排列后返回。
 *
 * 后端 `resolve_stages()` 会自己按 order 重排（`drug_stages.py:229`），所以这不是
 * 为了正确性，而是为了让「将运行的顺序」在按钮上显示得和实际执行一致 ——
 * 否则用户勾选的顺序与跑的顺序不同，看起来像随机决定跑哪一段。
 */
export function orderSelected(selected: string[], stages: DrugStage[]): string[] {
  // 显式按 order 排序，不依赖 stages 恰好已排好。
  // 后端 stages_payload() 目前是按注册表顺序发的，但把这个顺序当成契约、
  // 等哪天后端改了或前端从别处拿到阶段列表，这里会安静地按错顺序显示。
  return stages
    .filter(s => selected.includes(s.id))
    .sort((a, b) => a.order - b.order)
    .map(s => s.id)
}

/**
 * 读取上次的勾选。**只保留注册表里仍然存在的 id。**
 *
 * 阶段改名/删除后，旧 sessionStorage 里会留下认不出的 id。若原样回填，
 * 用户会看到一个勾不掉的幽灵阶段，点击运行还会因后端 `resolve_stages()`
 * 返回 unknown 而整条流水线被拒（`llm_proxy.py:274-276` 的行为）。
 */
export function loadSelection(stages: DrugStage[]): string[] {
  try {
    const raw = sessionStorage.getItem(DRUG_STAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const known = new Set(stages.map(s => s.id))
    return parsed.filter((x): x is string => typeof x === 'string' && known.has(x))
  } catch {
    return []
  }
}

export function saveSelection(selected: string[]): void {
  try {
    sessionStorage.setItem(DRUG_STAGE_KEY, JSON.stringify(selected))
  } catch { /* quota / 隐私模式 —— 选择丢失不影响本次运行 */ }
}

/** 运行开始前的初始进度：全 pending，顺序即实际执行顺序。 */
export function initProgress(stages: DrugStage[], selectedIds: string[]): DrugStageProgress[] {
  const run = orderSelected(selectedIds, stages)
  return run.map((id, i) => {
    const stage = stages.find(s => s.id === id) as DrugStage
    return { stageId: id, label: stage.label, status: 'pending', index: i, total: run.length }
  })
}

/**
 * 按 SSE 事件推进进度。不认识的 stage_id（例如后端加了新阶段而前端缓存了旧的
 * 注册表）直接忽略 —— 宁可少一格进度，也不要凭空插入一个没有 label 的格子。
 */
export function applyStageEvent(
  progress: DrugStageProgress[],
  event: string,
  data: unknown,
): DrugStageProgress[] {
  const d = data as Record<string, unknown> | null
  if (!d || typeof d.stage_id !== 'string') return progress
  const idx = progress.findIndex(p => p.stageId === d.stage_id)
  if (idx === -1) return progress

  const patch = (updates: Partial<DrugStageProgress>): DrugStageProgress[] =>
    progress.map((p, i) => (i === idx ? { ...p, ...updates } : p))

  if (event === 'stage_start') return patch({ status: 'running' })
  if (event === 'stage_done') {
    return patch(d.status === 'error'
      ? { status: 'error', error: typeof d.error === 'string' ? d.error : '阶段失败' }
      : { status: 'ok', elapsedMs: typeof d.elapsed_ms === 'number' ? d.elapsed_ms : undefined })
  }
  return progress
}

/** 进度条文案：跑完几个 / 共几个。中止时用实际完成数，不是选中数。 */
export function progressSummary(progress: DrugStageProgress[]): string {
  const done = progress.filter(p => p.status === 'ok').length
  return `${done} / ${progress.length} 阶段完成`
}
