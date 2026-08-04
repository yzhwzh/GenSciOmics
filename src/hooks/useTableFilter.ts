import { useMemo, useCallback, useState, useDeferredValue } from 'react'

export type FilterState = Record<string, Set<string>>

export function useTableFilter<T>(rows: T[]) {
  const [filters, setFilters] = useState<FilterState>({})

  // Defer filter application so checkbox toggling stays instant
  const deferredFilters = useDeferredValue(filters)

  // Pre-compute unique values ONCE when rows change (not per-column per-render)
  const uniqueValues = useMemo(() => {
    const map: Record<string, string[]> = {}
    if (rows.length === 0) return map

    // Collect unique values for all columns in a single pass
    const cols = new Set<string>()
    for (const row of rows) {
      for (const key of Object.keys(row as Record<string, unknown>)) {
        cols.add(key)
      }
    }

    const raw: Record<string, Set<string>> = {}
    for (const col of cols) {
      raw[col] = new Set<string>()
    }

    for (const row of rows) {
      for (const col of cols) {
        raw[col].add(String((row as Record<string, unknown>)[col] ?? ''))
      }
    }

    for (const col of cols) {
      map[col] = [...raw[col]].sort((a, b) => a.localeCompare(b))
    }
    return map
  }, [rows])

  // Use deferred filters for the expensive filteredRows computation
  const filteredRows = useMemo(() => {
    const activeCols = Object.entries(deferredFilters).filter(([, vals]) => vals.size > 0)
    if (activeCols.length === 0) return rows

    return rows.filter((row) =>
      activeCols.every(([col, selectedValues]) => {
        const cellValue = String((row as Record<string, unknown>)[col] ?? '')
        return selectedValues.has(cellValue)
      }),
    )
  }, [rows, deferredFilters])

  const getUniqueValues = useCallback(
    (colKey: string): string[] => {
      return uniqueValues[colKey] ?? []
    },
    [uniqueValues],
  )

  const toggleFilter = useCallback((colKey: string, value: string) => {
    setFilters((prev) => {
      const next = new Map(Object.entries(prev))
      const current = next.get(colKey)
      if (!current) {
        next.set(colKey, new Set([value]))
      } else {
        const updated = new Set(current)
        if (updated.has(value)) {
          updated.delete(value)
        } else {
          updated.add(value)
        }
        if (updated.size === 0) {
          next.delete(colKey)
        } else {
          next.set(colKey, updated)
        }
      }
      return Object.fromEntries(next)
    })
  }, [])

  // Batch-set a column's filter values (e.g., Select All / Deselect All)
  const setColumnFilter = useCallback((colKey: string, values: Set<string>) => {
    setFilters((prev) => {
      if (values.size === 0) {
        const next = { ...prev }
        delete next[colKey]
        return next
      }
      return { ...prev, [colKey]: values }
    })
  }, [])

  const clearFilter = useCallback((colKey: string) => {
    setFilters((prev) => {
      const next = { ...prev }
      delete next[colKey]
      return next
    })
  }, [])

  const clearAllFilters = useCallback(() => {
    setFilters({})
  }, [])

  const isFilterActive = useCallback(
    (colKey: string): boolean => {
      return !!filters[colKey] && filters[colKey].size > 0
    },
    [filters],
  )

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((s) => s.size > 0).length,
    [filters],
  )

  return {
    filteredRows,
    filters,
    activeFilterCount,
    uniqueValues,
    getUniqueValues,
    toggleFilter,
    setColumnFilter,
    clearFilter,
    clearAllFilters,
    isFilterActive,
  }
}
