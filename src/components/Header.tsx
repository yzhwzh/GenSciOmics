import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Loader2 } from 'lucide-react'
import { searchDatasets } from '../api/search'

interface PreviewResult {
  tissue: string
  disease: string
  pmid: string
  search_matches: [string, string][]
}

const MATCH_ICONS: Record<string, string> = {
  gene: '',
  disease: '',
  pmid: '',
  tissue: '',
  sample_type: '',
  celltype: '',
}

export default function Header() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [preview, setPreview] = useState<PreviewResult[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const q = query.trim()
    if (!q) {
      setPreview([])
      setShowDropdown(false)
      return
    }
    timerRef.current = setTimeout(() => {
      // Cancel any previous in-flight request
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setLoading(true)
      searchDatasets(q, controller.signal)
        .then((data) => {
          const res = Array.isArray(data.results) ? data.results : []
          setPreview(res.slice(0, 6))
          setShowDropdown(true)
        })
        .catch((err) => {
          if (err?.name === 'AbortError') return
          setPreview([])
        })
        .finally(() => setLoading(false))
    }, 250)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      abortRef.current?.abort()
    }
  }, [query])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const doSearch = (q?: string) => {
    const term = (q ?? query).trim()
    if (!term) return
    setShowDropdown(false)
    navigate(`/search?q=${encodeURIComponent(term)}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') doSearch()
    if (e.key === 'Escape') setShowDropdown(false)
  }

  const previewCounts = () => {
    const counts: Record<string, number> = {}
    for (const r of preview) {
      const seen = new Set<string>()
      for (const [type] of (r.search_matches ?? [])) {
        if (!seen.has(type)) {
          seen.add(type)
          counts[type] = (counts[type] || 0) + 1
        }
      }
    }
    return counts
  }

  return (
    <header className="bg-white border-b border-brand-border sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex items-center justify-between h-16">
          <a href="/" className="flex items-center gap-2.5 shrink-0">
            <img
              src="/gensci-logo.svg"
              alt="GenSci"
              className="h-8 w-auto"
            />
          </a>

          <div className="flex-1 max-w-xl mx-8 relative" ref={dropdownRef}>
            <div className="flex items-center gap-2 bg-brand-bg border border-brand-border rounded-xl px-4 py-2 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand-accent transition-all">
              <Search className="w-4 h-4 text-brand-text-secondary shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => { if (preview.length) setShowDropdown(true) }}
                placeholder="Search cells, disease, PMID..."
                className="flex-1 bg-transparent outline-none text-sm text-brand-text placeholder:text-gray-400"
              />
              <button
                onClick={() => doSearch()}
                className="bg-brand hover:bg-brand-dark text-white text-xs font-semibold px-4 py-1.5 rounded-lg transition-colors shrink-0"
              >
                Search
              </button>
            </div>

            {showDropdown && query.trim() && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-50 overflow-hidden">
                {loading ? (
                  <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Searching...
                  </div>
                ) : preview.length === 0 ? (
                  <div className="py-6 text-center text-sm text-gray-400">
                    No results for &ldquo;{query}&rdquo;
                  </div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2 border-b border-gray-100">
                      {Object.entries(previewCounts()).map(([type, count]) => (
                        <span key={type} className="inline-flex items-center gap-1 text-[11px] text-gray-600 bg-gray-50 px-2 py-0.5 rounded-full">
                          {MATCH_ICONS[type] || ''} {type} {count}
                        </span>
                      ))}
                      <span className="text-[11px] text-gray-400 ml-auto">{preview.length} datasets</span>
                    </div>

                    <div className="max-h-[300px] overflow-y-auto">
                      {preview.map((r, i) => (
                        <button
                          key={i}
                          onClick={() => doSearch(query)}
                          className="w-full text-left px-4 py-2.5 hover:bg-blue-50 transition-colors border-b border-gray-50 last:border-0"
                        >
                          <div className="flex items-center gap-2 text-sm">
                            <span className="font-medium text-gray-800">{r.disease}</span>
                            <span className="text-gray-400 text-xs">· {r.tissue}</span>
                            <span className="text-gray-300 font-mono text-[11px]">{r.pmid}</span>
                          </div>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {(r.search_matches ?? []).slice(0, 3).map(([type, val]) => (
                              <span key={`${type}-${val}`} className="inline-flex items-center gap-0.5 text-[10px] text-gray-500 bg-gray-50 px-1.5 py-0.5 rounded">
                                {MATCH_ICONS[type] || '·'} {val.length > 18 ? val.slice(0, 18) + '…' : val}
                              </span>
                            ))}
                          </div>
                        </button>
                      ))}
                    </div>

                    <button
                      onClick={() => doSearch()}
                      className="w-full text-center py-2.5 text-xs font-medium text-brand bg-brand-bg hover:bg-brand-light/10 transition-colors border-t border-gray-100"
                    >
                      View all {preview.length}+ results →
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-brand-text-secondary hidden sm:block">
              Single-cell Atlas
            </span>
          </div>
        </div>
      </div>
    </header>
  )
}
