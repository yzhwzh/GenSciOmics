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
    <div className="space-y-2.5 p-3 bg-gray-50 rounded-lg border border-gray-200">
      <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2">LLM Configuration</div>

      {/* Model */}
      <div>
        <label className="text-[10px] font-medium text-gray-400 block mb-0.5">Model</label>
        {fetchedModels ? (
          <div className="relative">
            <select value={config.model}
              onChange={(e) => onChange({ ...config, model: e.target.value })}
              className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 bg-white text-gray-700 outline-none focus:border-blue-400 font-mono appearance-none cursor-pointer">
              {fetchedModels.map(m => (
                <option key={m.name} value={m.name}>
                  {m.name}{m.size_gb ? ` (${m.size_gb}GB)` : ''}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2 text-gray-400">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
        ) : (
          <input type="text" value={config.model}
            onChange={(e) => onChange({ ...config, model: e.target.value })}
            placeholder={fetching ? 'Loading...' : 'deepseek-r1:32b'}
            className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 bg-white text-gray-700 outline-none focus:border-blue-400 placeholder:text-gray-300 font-mono" />
        )}
      </div>

      {/* API Key */}
      <div>
        <label className="text-[10px] font-medium text-gray-400 block mb-0.5">API Key</label>
        <input type="password" value={config.apiKey} onChange={(e) => onChange({ ...config, apiKey: e.target.value })}
          placeholder={config.baseUrl.includes('localhost') ? 'Not needed for Ollama' : 'sk-...'}
          className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 bg-white text-gray-700 outline-none focus:border-blue-400 placeholder:text-gray-300" />
      </div>

      {/* Base URL */}
      <div>
        <label className="text-[10px] font-medium text-gray-400 block mb-0.5">Base URL</label>
        <input type="text" value={config.baseUrl} onChange={(e) => onChange({ ...config, baseUrl: e.target.value })}
          placeholder="http://localhost:11434/v1"
          className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 bg-white text-gray-700 outline-none focus:border-blue-400 placeholder:text-gray-300 font-mono" />
      </div>

      {/* Temperature */}
      <div>
        <label className="text-[10px] font-medium text-gray-400 block mb-0.5">Temperature: {config.temperature.toFixed(1)}</label>
        <input type="range" min="0" max="1.5" step="0.1" value={config.temperature}
          onChange={(e) => onChange({ ...config, temperature: parseFloat(e.target.value) })}
          className="w-full accent-blue-500" />
      </div>
    </div>
  )
}
