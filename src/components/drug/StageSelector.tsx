import { AlertTriangle, Check, Loader2, CircleAlert, Circle } from 'lucide-react'
import type { DrugStage, DrugStageProgress } from '../../api/types'

/**
 * 阶段卡片列表 —— 用户在这里勾选要跑哪几段。
 *
 * 每张卡片同时承担两件事：勾选，以及**在跑的时候显示这一段的状态**。
 * 合成一个组件是因为进度格子必须和勾选框一一对齐 —— 拆成两个列表会需要
 * 两套顺序，而顺序一旦不一致，进度就会显示在错误的阶段上。
 */

interface StageSelectorProps {
  stages: DrugStage[]
  selected: string[]
  onToggle: (id: string) => void
  onSelectAll: () => void
  onClear: () => void
  /** 运行中才有值；为 null 表示尚未运行过。 */
  progress: DrugStageProgress[] | null
  running: boolean
  onShowSkill: (name: string) => void
}

const STATUS_ICON = {
  pending: Circle,
  running: Loader2,
  ok: Check,
  error: CircleAlert,
} as const

const STATUS_CLASS = {
  pending: 'text-text-muted',
  running: 'text-brand animate-spin',
  ok: 'text-green-600',
  error: 'text-error',
} as const

export default function StageSelector({
  stages,
  selected,
  onToggle,
  onSelectAll,
  onClear,
  progress,
  running,
  onShowSkill,
}: StageSelectorProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">
          选择要运行的阶段
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onSelectAll}
            disabled={running}
            className="text-[10px] text-brand hover:underline disabled:opacity-40 disabled:no-underline"
          >
            全选
          </button>
          <span className="text-border-light">|</span>
          <button
            onClick={onClear}
            disabled={running}
            className="text-[10px] text-text-muted hover:text-brand hover:underline disabled:opacity-40 disabled:no-underline"
          >
            清空
          </button>
          <span className="text-[10px] text-text-muted">已选 {selected.length}/{stages.length}</span>
        </div>
      </div>

      {stages.map(stage => {
        const isSelected = selected.includes(stage.id)
        // 进度按 stageId 查，而不是按下标 —— 选的阶段是注册表的子集，
        // 下标在两个列表里含义不同。
        const prog = progress?.find(p => p.stageId === stage.id)
        const Icon = prog ? STATUS_ICON[prog.status] : null

        return (
          <div
            key={stage.id}
            className={`rounded-lg border transition-colors ${
              isSelected
                ? 'border-brand/40 bg-brand-bg/40'
                : 'border-border-light bg-surface hover:bg-surface-muted'
            }`}
          >
            <label
              className={`flex items-start gap-2 p-2.5 ${
                running ? 'cursor-not-allowed' : 'cursor-pointer'
              }`}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={running}
                onChange={() => onToggle(stage.id)}
                className="mt-0.5 w-3.5 h-3.5 accent-[var(--color-brand,#2563eb)] shrink-0"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  {Icon && prog && (
                    <Icon
                      className={`w-3 h-3 shrink-0 ${STATUS_CLASS[prog.status]}`}
                      aria-label={prog.status}
                    />
                  )}
                  <span className="text-[11px] font-semibold text-text-primary">
                    {stage.order}. {stage.label}
                  </span>
                  {prog?.status === 'ok' && prog.elapsedMs !== undefined && (
                    <span className="text-[9px] text-text-muted font-mono">
                      {(prog.elapsedMs / 1000).toFixed(0)}s
                    </span>
                  )}
                </div>

                <p className="text-[10px] text-text-secondary leading-relaxed mt-1">
                  {stage.summary}
                </p>

                <div className="flex flex-wrap gap-1 mt-1.5">
                  {stage.skills.map(name => (
                    <button
                      key={name}
                      type="button"
                      onClick={(e) => { e.preventDefault(); onShowSkill(name) }}
                      className="text-[9px] font-mono text-text-muted bg-surface-raised hover:text-brand hover:bg-brand-bg px-1.5 py-0.5 rounded transition-colors"
                      title="查看该 skill 的说明"
                    >
                      {name}
                    </button>
                  ))}
                </div>

                {/* 能力边界。只在选中且确实有边界时显示 —— 未勾选的卡片上挂一段
                    「做不到什么」会让人以为整页都受限。 */}
                {isSelected && stage.gap && (
                  <p className="flex items-start gap-1 text-[9px] text-amber-700 leading-relaxed mt-1.5">
                    <AlertTriangle className="w-3 h-3 shrink-0 mt-px" />
                    <span>{stage.gap}</span>
                  </p>
                )}

                {prog?.status === 'error' && prog.error && (
                  <p className="text-[9px] text-error leading-relaxed mt-1.5">{prog.error}</p>
                )}
              </div>
            </label>
          </div>
        )
      })}
    </div>
  )
}
