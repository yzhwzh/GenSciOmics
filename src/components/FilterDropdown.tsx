import { useState, useRef, useEffect, useMemo, memo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Filter, X } from 'lucide-react'

interface FilterDropdownProps {
  label: string
  values: string[]
  selectedValues: Set<string> | undefined
  onToggle: (value: string) => void
  onSetAll?: (values: Set<string>) => void
  onClear: () => void
  isActive: boolean
  /** Render popup via portal to avoid overflow clipping (use inside scrollable containers) */
  portal?: boolean
}

function FilterDropdown({
  label,
  values,
  selectedValues,
  onToggle,
  onSetAll,
  onClear,
  isActive,
  portal: usePortal = false,
}: FilterDropdownProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open])

  // Recompute portal position
  const updatePos = useCallback(() => {
    if (!usePortal || !buttonRef.current) return
    const rect = buttonRef.current.getBoundingClientRect()
    setPos({ top: rect.bottom + 4, left: rect.left })
  }, [usePortal])

  useEffect(() => {
    if (!open || !usePortal) return
    updatePos()
    window.addEventListener('scroll', updatePos, true)
    window.addEventListener('resize', updatePos)
    return () => {
      window.removeEventListener('scroll', updatePos, true)
      window.removeEventListener('resize', updatePos)
    }
  }, [open, usePortal, updatePos])

  const filteredValues = useMemo(() => {
    if (!search.trim()) return values
    const q = search.toLowerCase()
    return values.filter((v) => v.toLowerCase().includes(q))
  }, [values, search])

  const allSelected = selectedValues && selectedValues.size === values.length
  const noneSelected = !selectedValues || selectedValues.size === 0

  const handleSelectAll = () => {
    if (onSetAll) {
      onSetAll(new Set(values))
    } else {
      for (const v of values) {
        if (!selectedValues?.has(v)) onToggle(v)
      }
    }
  }

  const handleDeselectAll = () => {
    if (onSetAll) {
      onSetAll(new Set())
    } else {
      if (selectedValues) {
        for (const v of [...selectedValues]) {
          onToggle(v)
        }
      }
      onClear()
    }
  }

  const openDropdown = () => {
    setOpen(true)
    if (usePortal) updatePos()
  }

  const popupContent = (
    <div className="w-56 bg-white border border-gray-200 rounded-lg shadow-lg max-h-72 flex flex-col">
      {/* Header with select/deselect */}
      <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-gray-100">
        <button
          onClick={handleSelectAll}
          disabled={allSelected}
          className="text-[11px] text-blue-600 hover:text-blue-800 disabled:text-gray-300 disabled:cursor-not-allowed"
        >
          Select All
        </button>
        <button
          onClick={handleDeselectAll}
          disabled={noneSelected}
          className="text-[11px] text-gray-500 hover:text-gray-700 disabled:text-gray-300 disabled:cursor-not-allowed"
        >
          Deselect All
        </button>
        <button
          onClick={() => { setOpen(false); setSearch('') }}
          className="text-gray-400 hover:text-gray-600"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {/* Search input */}
      <div className="px-2.5 py-1.5 border-b border-gray-100">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search values..."
          className="w-full text-[11px] px-2 py-1 border border-gray-200 rounded outline-none focus:border-blue-400"
          autoFocus
        />
      </div>

      {/* Value list — lazy render if many values */}
      <div className="flex-1 overflow-y-auto">
        {filteredValues.length === 0 ? (
          <div className="px-2.5 py-3 text-[11px] text-gray-400 text-center">No values</div>
        ) : filteredValues.length > 200 && !search.trim() ? (
          <div className="px-2.5 py-6 text-[11px] text-gray-400 text-center">
            {filteredValues.length} values — type to search
          </div>
        ) : (
          filteredValues.map((v) => {
            const checked = selectedValues?.has(v) ?? false
            return (
              <label
                key={v}
                className="flex items-center gap-2 px-2.5 py-1 hover:bg-gray-50 cursor-pointer text-[11px] text-gray-700"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(v)}
                  className="w-3 h-3 accent-blue-600"
                />
                <span className="truncate flex-1">{v || '(empty)'}</span>
              </label>
            )
          })
        )}
      </div>

      {/* Footer with count */}
      <div className="px-2.5 py-1 border-t border-gray-100 text-[10px] text-gray-400">
        {selectedValues?.size ?? 0} / {values.length} selected
      </div>
    </div>
  )

  return (
    <div ref={containerRef} className="relative inline-flex items-center">
      <button
        ref={buttonRef}
        onClick={openDropdown}
        className={`inline-flex items-center gap-1 transition-colors ${
          isActive ? 'text-blue-600' : ''
        }`}
        title={`Filter by ${label}`}
      >
        <span>{label}</span>
        <Filter className={`w-3 h-3 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
        {isActive && selectedValues && (
          <span className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold text-white bg-blue-500 rounded-full">
            {selectedValues.size}
          </span>
        )}
      </button>

      {open && !usePortal && (
        <div className="absolute top-full left-0 mt-1 z-50">
          {popupContent}
        </div>
      )}

      {open && usePortal && pos && createPortal(
        <div
          style={{
            position: 'fixed',
            top: pos.top,
            left: Math.min(pos.left, window.innerWidth - 240),
            zIndex: 9999,
          }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          {popupContent}
        </div>,
        document.body
      )}
    </div>
  )
}

export default memo(FilterDropdown)
