import { useState, useEffect } from 'react'
import type { LLMConfig } from '../../api/types'

type FetchedModel = { name: string; size_gb?: number }

export default function LLMConfigPanel({
  config,
  onChange,
}: {
  config: LLMConfig
  onChange: (c: LLMConfig) => void
}) {
  const [fetchedModels, setFetchedModels] = useState<FetchedModel[] | null>(null)
  const [fetching, setFetching] = useState(false)

  useEffect(() => {
    if (!config.baseUrl) {
      setFetchedModels(null)
      return
    }
    let cancelled = false
    setFetching(true)
    fetch('/api/llm/fetch-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: config.baseUrl, api_key: config.apiKey }),
    })
      .then(r => r.json())
      .then(data => {
        if (!cancelled) {
          const models = data.models || []
          setFetchedModels(models.length > 0 ? models : null)
          setFetching(false)
        }
      })
      .catch(() => {
        if (!cancelled) { setFetchedModels(null); setFetching(false) }
      })
    return () => { cancelled = true }
  }, [config.baseUrl, config.apiKey])

  return (
    <div className="space-y-2.5 p-3 bg-surface-raised rounded-lg border border-border-light">
      <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">LLM Configuration</div>

      {/* Model — always show company default + fetched models */}
      <div>
        <label className="text-[10px] font-medium text-text-muted block mb-0.5">Model</label>
        <div className="relative">
          <select value={config.model}
            onChange={(e) => onChange({ ...config, model: e.target.value })}
            className="w-full text-xs border border-border-light rounded px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-blue-400 font-mono appearance-none cursor-pointer">
            {!fetchedModels?.find(m => m.name === config.model) && (
              <option value={config.model}>{config.model}</option>
            )}
            {fetchedModels?.map(m => (
              <option key={m.name} value={m.name}>
                {m.name}{m.size_gb ? ` (${m.size_gb}GB)` : ''}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2 text-text-muted">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      </div>

      {/* API Key */}
      <div>
        <label className="text-[10px] font-medium text-text-muted block mb-0.5">API Key</label>
        <input type="password" value={config.apiKey} onChange={(e) => onChange({ ...config, apiKey: e.target.value })}
          placeholder="sk-..."
          className="w-full text-xs border border-border-light rounded px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-blue-400 placeholder:text-text-muted" />
      </div>

      {/* Base URL */}
      <div>
        <label className="text-[10px] font-medium text-text-muted block mb-0.5">Base URL</label>
        <input type="text" value={config.baseUrl} onChange={(e) => onChange({ ...config, baseUrl: e.target.value })}
          placeholder="https://api.openai.com/v1"
          className="w-full text-xs border border-border-light rounded px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-blue-400 placeholder:text-text-muted font-mono" />
      </div>

      {/* Temperature */}
      <div>
        <label className="text-[10px] font-medium text-text-muted block mb-0.5">Temperature: {config.temperature.toFixed(1)}</label>
        <input type="range" min="0" max="1.5" step="0.1" value={config.temperature}
          onChange={(e) => onChange({ ...config, temperature: parseFloat(e.target.value) })}
          className="w-full accent-blue-500" />
      </div>
    </div>
  )
}
