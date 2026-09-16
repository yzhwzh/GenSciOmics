import { useState } from 'react'
import { Loader2, Download, AlertTriangle } from 'lucide-react'
import type { SupplementaryTable as SupplementaryTableData } from '../../api/types'

/**
 * 渲染一个补充材料附件的内容（后端已解析成 sheets）。
 *
 * 只负责「给我数据、我画出来」，取数据的事在 SampleInfoSection 里 ——
 * 那边知道用户点了哪一条，也知道要不要提示下载代价。
 */

/** CSV 单元格转义：逗号、引号、换行都得包起来，引号要翻倍。 */
function csvCell(v: string | number | null): string {
  if (v === null || v === undefined) return ''
  const s = String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export default function SupplementaryTable({ table }: { table: SupplementaryTableData }) {
  const [active, setActive] = useState(0)

  if (table.error) {
    return (
      <div className="flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5">
        <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
        <span className="leading-relaxed">{table.error}</span>
      </div>
    )
  }

  const sheets = table.sheets ?? []
  if (!sheets.length) {
    return <div className="text-[11px] text-text-muted py-2">文件里没有可显示的内容。</div>
  }

  // 后端只会返回合法下标能取到的 sheet，但防御一下越界，免得切 tab 时白屏
  const sheet = sheets[Math.min(active, sheets.length - 1)]
  const hasColumns = sheet.columns.some(c => c !== '')
  const headers = hasColumns
    ? sheet.columns
    : sheet.columns.map((_, i) => `列 ${i + 1}`)

  const downloadCSV = () => {
    const csvRows = [headers.map(csvCell).join(',')]
    for (const row of sheet.rows) csvRows.push(row.map(csvCell).join(','))
    // BOM 让 Excel 认出 UTF-8，否则中文列名会是乱码
    const blob = new Blob(['﻿' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${sheet.name || 'supplementary'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="border border-border-light rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-2 py-1 bg-surface-raised border-b border-border-light">
        <div className="flex items-center gap-1 overflow-x-auto">
          {sheets.map((s, i) => (
            <button
              key={`${s.name}-${i}`}
              onClick={() => setActive(i)}
              className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
                i === active
                  ? 'bg-brand text-white'
                  : 'text-text-muted hover:text-text-secondary hover:bg-surface'
              }`}
            >
              {s.name || `Sheet ${i + 1}`}
            </button>
          ))}
        </div>
        <button
          onClick={downloadCSV}
          className="flex items-center gap-1 text-[10px] text-text-muted hover:text-brand px-1.5 py-0.5 rounded hover:bg-surface transition-colors shrink-0"
        >
          <Download className="w-3 h-3" /> CSV
        </button>
      </div>

      <div className="overflow-auto max-h-[420px]">
        <table className="text-[11px] border-collapse w-full">
          <thead className="sticky top-0 bg-surface-raised z-10">
            <tr>
              {headers.map((c, i) => (
                <th
                  key={i}
                  className="text-left font-semibold text-text-secondary px-2 py-1 border-b border-border-light whitespace-nowrap"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((row, r) => (
              <tr key={r} className="hover:bg-surface-raised/60">
                {headers.map((_, c) => (
                  <td
                    key={c}
                    className="px-2 py-0.5 text-text-secondary border-b border-border-light/50 align-top"
                  >
                    {row[c] === null || row[c] === undefined ? '' : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {sheet.rows.length === 0 && (
          <div className="text-[11px] text-text-muted px-2 py-3 text-center">这个 sheet 是空的。</div>
        )}
      </div>

      {table.truncated && (
        // 截断必须说出来：只显示前 5000 行而不吭声，用户会以为这就是全部
        <div className="px-2 py-1 text-[10px] text-amber-700 bg-amber-50 border-t border-amber-200">
          表格过大，仅显示前 {sheet.rows.length} 行。完整内容请用右上角 CSV 下载。
        </div>
      )}
    </div>
  )
}

export function SupplementaryTableLoading({ hint }: { hint: string }) {
  return (
    <div className="flex items-start gap-2 px-2 py-2 bg-blue-50 border border-blue-200 rounded-lg">
      <Loader2 className="w-3.5 h-3.5 text-brand animate-spin shrink-0 mt-0.5" />
      <span className="text-[11px] text-text-secondary leading-relaxed">{hint}</span>
    </div>
  )
}
