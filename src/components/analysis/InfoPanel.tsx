import { Loader2 } from 'lucide-react'
import { formatNumber } from '../../api/client'
import SampleInfoSection from './SampleInfoSection'
import type { AnalysisInfo } from '../../api/types'

export default function InfoPanel({
  info,
  loading,
  abstractError = false,
  onRetryAbstract,
  isBulk = false,
}: {
  info: AnalysisInfo | null
  loading: boolean
  /** 摘要这次没取到（见 AnalysisPage / BUG_LOG B35）。 */
  abstractError?: boolean
  /** 重试取摘要。必须给 —— 不给的话失败就是死路，用户只能刷新整页。 */
  onRetryAbstract?: () => void
  isBulk?: boolean
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 text-brand animate-spin" />
      </div>
    )
  }
  if (!info) {
    return <div className="text-sm text-text-muted p-4">No info available</div>
  }

  const { abstract, stats } = info
  // 摘要可能与 stats 分两批到达（BUG_LOG B35）：stats 先渲染，摘要后补。
  // 三种状态必须分开，且**全部由数据推导**（不靠 effect 里 set 的 loading 标志 ——
  // 那个标志在 effect 跑起来之前是 false，于是每一轮冷加载都会先渲染一帧
  // 「Abstract not available」，正好是这段注释声称已消除的那句谎话）：
  //   还在取   → abstract_ready !== true 且没失败 → 转圈
  //   没取到   → 失败过 → 说明这是暂时的，给重试
  //   真没有   → abstract_ready === true 但内容为空 → 才是 not available
  const abstractMissing = abstract == null || (!abstract.title && !abstract.abstract)
  const abstractPending = info.abstract_ready !== true && abstractMissing && !abstractError
  const abstractUnavailable = info.abstract_ready !== true && abstractMissing && abstractError
  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">Abstract</h3>
        {abstractUnavailable ? (
          <p className="text-xs text-text-muted">
            摘要暂时取不到（外部文献库超时或限流）。
            <button
              type="button"
              onClick={onRetryAbstract}
              className="ml-1 text-brand underline underline-offset-2 hover:text-brand-dark"
            >
              重试
            </button>
          </p>
        ) : abstractPending ? (
          <p className="text-xs text-text-muted flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 text-brand animate-spin" /> Loading abstract…
          </p>
        ) : (
          <>
            {abstract?.title && (
              <h4 className="text-sm font-semibold text-text-primary mb-1 leading-snug">{abstract.title}</h4>
            )}
            {abstract?.abstract ? (
              <p className="text-xs text-text-secondary leading-relaxed">{abstract.abstract}</p>
            ) : (
              <p className="text-xs text-text-muted italic">Abstract not available</p>
            )}
            {(abstract?.journal || abstract?.authors) && (
              <p className="text-[11px] text-text-muted mt-1">
                {abstract.authors && <span>{abstract.authors}. </span>}
                {abstract.journal && <span className="italic">{abstract.journal}. </span>}
                {abstract.year && <span>{abstract.year}.</span>}
                {abstract.doi && <span> DOI: {abstract.doi}</span>}
                {info.pmid && <span> PMID: {info.pmid}</span>}
              </p>
            )}
          </>
        )}
      </div>

      {abstract?.methods && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">Methods</h3>
          <div className="text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">{abstract.methods}</div>
        </div>
      )}

      {/* 补充材料。
          注意判空的是 `undefined` 而不是空数组 —— 后端只在真的查过之后才写这个
          字段（非 PubMed 数据集整个不写）。「没查」和「查了没有」在这里必须分开，
          前者整块不显示，后者要显示一句「确实没有」。 */}
      {abstract?.supplementary !== undefined && (
        <SampleInfoSection
          items={abstract.supplementary}
          note={abstract.supplementary_note ?? ''}
          pmcid={abstract.pmcid}
        />
      )}

      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">Dataset Summary</h3>
        <div className="grid grid-cols-5 gap-2">
          {(isBulk
            ? [
                { label: 'Samples', value: stats.sample_count },
                { label: 'Patients', value: stats.patient_count },
                { label: 'Diseases', value: stats.disease_count },
                { label: 'Genes', value: formatNumber(stats.genes) },
                { label: 'Tumor / Normal', value: stats.group_dist },
              ]
            : [
                { label: 'Donors', value: stats.patient_count },
                { label: 'Samples', value: stats.sample_count },
                { label: 'Cells', value: formatNumber(stats.cells) },
                { label: 'Cell Types', value: stats.celltype_count },
                { label: 'Genes', value: formatNumber(stats.genes) },
              ]
          ).map((item) => (
            <div key={item.label} className="bg-surface-raised rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-text-primary">{item.value ?? '-'}</div>
              <div className="text-[10px] text-text-muted">{item.label}</div>
            </div>
          ))}
        </div>
        {!isBulk && stats.cell_type_names.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {stats.cell_type_names.map((ct) => (
              <span key={ct} className="text-[10px] bg-brand/10 text-brand-dark px-1.5 py-0.5 rounded">
                {ct}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
