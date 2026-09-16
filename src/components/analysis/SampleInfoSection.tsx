import { useState, useMemo } from 'react'
import { ChevronRight, ChevronDown, Star, FileSpreadsheet, FileText, Image as ImageIcon } from 'lucide-react'
import SupplementaryTable, { SupplementaryTableLoading } from './SupplementaryTable'
import { fetchSupplementaryTable } from '../../api/analysis'
import type {
  SupplementaryItem,
  SupplementaryNote,
  SupplementaryTable as SupplementaryTableData,
} from '../../api/types'

/**
 * Study Info 页的「补充材料 / 样本信息」区块。
 *
 * 设计上只做两件事，且刻意不对称：
 *
 *  · **清单是免费的** —— 后端为了提取 Methods 本来就下了整份全文 XML，
 *    `<supplementary-material>` 就在同一份里，所以列表零额外网络、秒出。
 *  · **内容是昂贵的** —— PMC 没有单文件接口，点开一个附件要下整包
 *    （实测 6.7–37 MB，经代理 24–37 秒）。所以只在用户真的点「查看」时才下，
 *    下完落盘缓存，之后再点是毫秒级。
 *
 * 列表**不做任何过滤**。文件名和 caption 都不可靠（`Table_S9.xlsx` 打开是
 * motif 表，`mmc2.xlsx` 才是患者信息；不少论文的 caption 干脆是空的），
 * 所以 `is_sample_hint` 只用来排序和打星 —— 猜错最多少一颗星，
 * 不会让任何一条附件从用户眼前消失。
 */

const KIND_ICON = {
  table: FileSpreadsheet,
  figure: ImageIcon,
  file: FileText,
} as const

const KIND_LABEL = {
  table: '表格',
  figure: '图片',
  file: '附件',
} as const

/**
 * 三种「没有」的说法必须不同。
 *
 * 混成一句「无补充材料」就是把「查过确实没有」和「我们根本没能力查」
 * 说成一回事 —— 前者是结论，后者不是。
 */
const NOTE_TEXT: Record<Exclude<SupplementaryNote, ''>, string> = {
  'no-pmcid': '该文献未开放全文（拿不到 PMC 编号），因此无法检查是否有补充材料。这不代表它没有。',
  none: '已获取文献全文，其中没有补充材料附件。',
  error: '补充材料清单抓取失败（可能是网络限流）。刷新页面可重试。',
}

export default function SampleInfoSection({
  items,
  note,
  pmcid,
}: {
  items: SupplementaryItem[]
  note: SupplementaryNote
  pmcid?: string
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [tables, setTables] = useState<Record<string, SupplementaryTableData>>({})
  const [loading, setLoading] = useState<string | null>(null)

  // 疑似样本表的排前面；其余保持后端给的原始顺序。
  // 用 index 兜底保证稳定 —— 同分项不能因为排序在两次渲染间跳来跳去。
  const sorted = useMemo(() => {
    return items
      .map((item, index) => ({ item, index }))
      .sort((a, b) =>
        Number(b.item.is_sample_hint) - Number(a.item.is_sample_hint) || a.index - b.index)
      .map(({ item }) => item)
  }, [items])

  const toggle = async (item: SupplementaryItem) => {
    if (expanded === item.name) {
      setExpanded(null)
      return
    }
    setExpanded(item.name)
    if (tables[item.name] || !pmcid) return

    setLoading(item.name)
    try {
      const result = await fetchSupplementaryTable(pmcid, item.name)
      setTables(prev => ({ ...prev, [item.name]: result }))
    } catch (err: unknown) {
      // 失败要落到这个附件自己的格子里，不能让整个 Study Info 页塌掉
      setTables(prev => ({
        ...prev,
        [item.name]: { error: err instanceof Error ? err.message : '获取失败' },
      }))
    } finally {
      setLoading(null)
    }
  }

  return (
    <div>
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
        Sample Information
        {sorted.length > 0 && (
          <span className="ml-1.5 font-normal normal-case tracking-normal text-text-muted">
            （{sorted.length} 个补充材料附件）
          </span>
        )}
      </h3>

      {sorted.length === 0 ? (
        <p className={`text-[11px] leading-relaxed ${note === 'error' ? 'text-amber-700' : 'text-text-muted'}`}>
          {note ? NOTE_TEXT[note] : '没有补充材料。'}
        </p>
      ) : (
        <div className="space-y-1">
          {sorted.map((item) => {
            const Icon = KIND_ICON[item.kind] ?? FileText
            const isOpen = expanded === item.name
            const canView = item.kind === 'table'
            const loaded = tables[item.name]
            const isLoading = loading === item.name

            return (
              <div key={item.name} className="border border-border-light rounded-lg overflow-hidden">
                <div
                  onClick={() => canView && toggle(item)}
                  className={`flex items-center gap-1.5 px-2 py-1.5 ${
                    canView ? 'cursor-pointer hover:bg-surface-raised' : ''
                  } ${isOpen ? 'bg-surface-raised' : ''}`}
                >
                  {canView
                    ? (isOpen
                        ? <ChevronDown className="w-3 h-3 text-text-muted shrink-0" />
                        : <ChevronRight className="w-3 h-3 text-text-muted shrink-0" />)
                    : <span className="w-3 shrink-0" />}

                  <Icon className="w-3.5 h-3.5 text-text-muted shrink-0" />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      {item.is_sample_hint && (
                        <Star
                          className="w-3 h-3 text-amber-500 fill-amber-500 shrink-0"
                          aria-label="疑似样本信息表"
                        />
                      )}
                      <span className="text-[11px] text-text-primary truncate" title={item.name}>
                        {item.caption || item.name}
                      </span>
                    </div>
                    {item.caption && (
                      <div className="text-[10px] text-text-muted truncate" title={item.name}>
                        {item.name}
                      </div>
                    )}
                  </div>

                  <span className="text-[9px] text-text-muted bg-surface-raised px-1.5 py-0.5 rounded shrink-0">
                    {KIND_LABEL[item.kind] ?? '附件'}
                  </span>
                </div>

                {isOpen && (
                  <div className="px-2 pb-2">
                    {isLoading && !loaded && (
                      <SupplementaryTableLoading
                        hint="正在下载该文献的补充材料压缩包（首次打开需数十秒，之后会被缓存，秒开）…"
                      />
                    )}
                    {!isLoading && loaded && <SupplementaryTable table={loaded} />}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
