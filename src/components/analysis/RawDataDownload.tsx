import { useState, useRef, useEffect, useCallback } from 'react'
import { Download, Loader2, X } from 'lucide-react'
import AsyncCreatableSelect from 'react-select/async-creatable'
import CreatableSelect from 'react-select/creatable'
import { fetchRawExpression, fetchCellTypes, searchGenes } from '../../api/analysis'
import type { StylesConfig } from 'react-select'

interface Props {
  realPath: string
}

interface Option {
  value: string
  label: string
}

// ── Tailwind-styled react-select theme ─────────────────────
const selectStyles: StylesConfig<Option, true> = {
  control: (base, { isFocused }) => ({
    ...base,
    borderColor: isFocused ? '#93c5fd' : '#e5e7eb',
    boxShadow: isFocused ? '0 0 0 1px #93c5fd' : 'none',
    '&:hover': { borderColor: '#93c5fd' },
    fontSize: '12px',
    minHeight: '30px',
    borderRadius: '6px',
    cursor: 'text',
  }),
  multiValue: (base) => ({
    ...base,
    backgroundColor: '#eff6ff',
    borderRadius: '4px',
    fontSize: '11px',
  }),
  multiValueLabel: (base) => ({
    ...base,
    color: '#1d4ed8',
    fontWeight: 500,
    padding: '1px 4px',
  }),
  multiValueRemove: (base) => ({
    ...base,
    color: '#93c5fd',
    '&:hover': { backgroundColor: '#dbeafe', color: '#2563eb' },
    borderRadius: '0 4px 4px 0',
  }),
  menu: (base) => ({
    ...base,
    fontSize: '12px',
    zIndex: 60,
  }),
  option: (base, { isFocused, isSelected }) => ({
    ...base,
    backgroundColor: isSelected ? '#2563eb' : isFocused ? '#eff6ff' : '#fff',
    color: isSelected ? '#fff' : '#374151',
    padding: '6px 10px',
    cursor: 'pointer',
  }),
  input: (base) => ({ ...base, fontSize: '12px' }),
  placeholder: (base) => ({ ...base, color: '#9ca3af', fontSize: '12px' }),
  noOptionsMessage: (base) => ({ ...base, fontSize: '12px', color: '#9ca3af' }),
}

export default function RawDataDownload({ realPath }: Props) {
  const [open, setOpen] = useState(false)
  const [genes, setGenes] = useState<Option[]>([])
  const [cellTypes, setCellTypes] = useState<Option[]>([])
  const [cellTypeOptions, setCellTypeOptions] = useState<Option[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const modalRef = useRef<HTMLDivElement>(null)

  // Load cell type options when dialog opens
  useEffect(() => {
    if (!open || !realPath) return
    fetchCellTypes(realPath)
      .then(types => setCellTypeOptions(types.map(t => ({ value: t, label: t }))))
      .catch(() => {})
  }, [open, realPath])

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) setOpen(false)
    }
    setTimeout(() => document.addEventListener('mousedown', handler), 0)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Async gene search
  const loadGeneOptions = useCallback(async (input: string): Promise<Option[]> => {
    if (!input || input.length < 1) return []
    try {
      const results = await searchGenes(realPath, input)
      return results.slice(0, 30).map(g => ({ value: g, label: g }))
    } catch {
      return []
    }
  }, [realPath])

  const handleDownload = async () => {
    if (genes.length === 0) { setError('Please select at least one gene'); return }
    setError(''); setLoading(true)
    try {
      const genesStr = genes.map(g => g.value).join(',')
      const ctStr = cellTypes.map(c => c.value).join(',')
      const blob = await fetchRawExpression(realPath, genesStr, ctStr)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'raw_expression.csv'; a.click()
      URL.revokeObjectURL(url)
      setOpen(false)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button onClick={() => setOpen(true)}
        className="ml-auto flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 font-medium">
        <Download className="w-3.5 h-3.5" />
        Download Raw Data
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div ref={modalRef} className="bg-white rounded-xl border border-gray-200 shadow-xl p-4 w-[380px]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold text-gray-700">Download Raw Data</span>
              <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <label className="block text-[11px] font-medium text-gray-500 mb-1">Gene(s)</label>
            <AsyncCreatableSelect
              isMulti
              cacheOptions
              defaultOptions={false}
              loadOptions={loadGeneOptions}
              onChange={(v) => setGenes(v as Option[])}
              value={genes}
              placeholder="Search and select genes..."
              noOptionsMessage={({ inputValue }) => inputValue ? 'No genes found' : 'Type to search'}
              styles={selectStyles}
              className="mb-3"
            />

            <label className="block text-[11px] font-medium text-gray-500 mb-1">Cell Type(s)</label>
            <CreatableSelect
              isMulti
              options={cellTypeOptions}
              onChange={(v) => setCellTypes(v as Option[])}
              value={cellTypes}
              placeholder="Select cell types..."
              noOptionsMessage={() => 'No cell types loaded'}
              styles={selectStyles}
              className="mb-3"
            />

            {error && <div className="text-[11px] text-red-500 mb-2">{error}</div>}

            <div className="flex justify-end gap-2">
              <button onClick={() => setOpen(false)}
                className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border border-gray-200">Cancel</button>
              <button onClick={handleDownload} disabled={loading}
                className="text-xs text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 px-3 py-1.5 rounded flex items-center gap-1">
                {loading && <Loader2 className="w-3 h-3 animate-spin" />}
                {loading ? 'Downloading...' : 'Download'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
