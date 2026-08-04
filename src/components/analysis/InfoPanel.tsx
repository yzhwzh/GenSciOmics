import { Loader2 } from 'lucide-react'
import { formatNumber } from '../../api/client'
import type { AnalysisInfo } from '../../api/types'

export default function InfoPanel({
  info,
  loading,
}: {
  info: AnalysisInfo | null
  loading: boolean
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
  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">Abstract</h3>
        {abstract.title && (
          <h4 className="text-sm font-semibold text-text-primary mb-1 leading-snug">{abstract.title}</h4>
        )}
        {abstract.abstract ? (
          <p className="text-xs text-text-secondary leading-relaxed">{abstract.abstract}</p>
        ) : (
          <p className="text-xs text-text-muted italic">Abstract not available</p>
        )}
        {(abstract.journal || abstract.authors) && (
          <p className="text-[11px] text-text-muted mt-1">
            {abstract.authors && <span>{abstract.authors}. </span>}
            {abstract.journal && <span className="italic">{abstract.journal}. </span>}
            {abstract.year && <span>{abstract.year}.</span>}
            {abstract.doi && <span> DOI: {abstract.doi}</span>}
            {info.pmid && <span> PMID: {info.pmid}</span>}
          </p>
        )}
      </div>

      {abstract.methods && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">Methods</h3>
          <div className="text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">{abstract.methods}</div>
        </div>
      )}

      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">Dataset Summary</h3>
        <div className="grid grid-cols-5 gap-2">
          {[
            { label: 'Donors', value: stats.patient_count },
            { label: 'Samples', value: stats.sample_count },
            { label: 'Cells', value: formatNumber(stats.cells) },
            { label: 'Cell Types', value: stats.celltype_count },
            { label: 'Genes', value: formatNumber(stats.genes) },
          ].map((item) => (
            <div key={item.label} className="bg-surface-raised rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-text-primary">{item.value ?? '-'}</div>
              <div className="text-[10px] text-text-muted">{item.label}</div>
            </div>
          ))}
        </div>
        {stats.cell_type_names.length > 0 && (
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
