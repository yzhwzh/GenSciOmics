import { useEffect, useState } from 'react'
import { ArrowUpRight, Loader2 } from 'lucide-react'
import { fetchLog } from '../api/search'
import type { LogEntry } from '../api/types'

const TYPE_ICONS: Record<string, string> = {
  dataset_added: '',
  dataset_removed: '',
  analysis_start: '',
  analysis_ready: '',
  analysis_stop: '',
  milestone: '',
}

export default function UpdateLog() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadLog = () => {
      fetchLog(50)
        .then((data: unknown) => {
          if (Array.isArray(data)) {
            setLogs(data as LogEntry[])
            setLoading(false)
          }
        })
        .catch(() => setLoading(false))
    }
    loadLog()
    const interval = setInterval(loadLog, 5000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <section>
        <h2 className="text-base font-semibold text-brand-dark mb-3">Update Log</h2>
        <div className="bg-white rounded-xl border border-brand-border shadow-sm p-6 text-center">
          <Loader2 className="w-5 h-5 text-gray-300 mx-auto animate-spin" />
        </div>
      </section>
    )
  }

  return (
    <section>
      <h2 className="text-base font-semibold text-brand-dark mb-3">Update Log</h2>
      <div className="bg-white rounded-xl border border-brand-border shadow-sm divide-y divide-gray-100 max-h-[320px] overflow-y-auto">
        {logs.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-400">
            No events yet
          </div>
        ) : (
          logs.map((entry, i) => (
            <div
              key={`${entry.time}-${entry.type}-${i}`}
              className="flex items-start gap-2.5 px-4 py-2.5 hover:bg-gray-50 transition-colors"
            >
              <span className="text-sm mt-0.5 shrink-0">
                {TYPE_ICONS[entry.type] || ''}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-brand font-medium whitespace-nowrap">
                    {entry.time}
                  </span>
                  <span className="text-sm text-gray-700 truncate">
                    {entry.message}
                  </span>
                </div>
                {entry.detail && (
                  <p className="text-[11px] text-gray-400 truncate mt-0.5">
                    {entry.detail}
                  </p>
                )}
              </div>
              <ArrowUpRight className="w-3 h-3 text-gray-200 mt-1 shrink-0" />
            </div>
          ))
        )}
      </div>
    </section>
  )
}
