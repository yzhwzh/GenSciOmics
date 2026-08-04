import { useMemo, useRef, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import type { ChatMessage } from '../../api/types'

interface Props {
  messages: ChatMessage[]
  loading: boolean
}

/** Extract image markdown tags from stdout text */
function extractImages(stdout: string): { alt: string; url: string }[] {
  const results: { alt: string; url: string }[] = []
  const re = /!\[([^\]]*)\]\((\/api\/results\?file=[^)]+)\)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(stdout)) !== null) {
    results.push({ alt: m[1], url: m[2] })
  }
  return results
}

/** Extract download links from stdout (excludes image markdown ![alt](url)) */
function extractDownloadLinks(stdout: string): { label: string; url: string }[] {
  const results: { label: string; url: string }[] = []
  const re = /(?<!!)\[([^\]]+)\]\((\/api\/results\?file=[^)]+)\)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(stdout)) !== null) {
    results.push({ label: m[1], url: m[2] })
  }
  return results
}

/** Extract script name from shell command */
function extractScriptName(command: string): string {
  const m = command.match(/([^/\s]+\.py)/)
  return m ? m[1] : ''
}

/** Truncate user message for group label */
function truncate(text: string, max = 40): string {
  return text.length > max ? text.slice(0, max) + '…' : text
}

export default function ToolResultsPanel({ messages, loading }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Group tool results by assistant message
  const groups = useMemo(() => {
    const results: {
      msgIndex: number
      userPreview: string
      items: { name: string; command?: string; stdout?: string; result?: unknown }[]
    }[] = []
    for (const msg of messages) {
      if (msg.role === 'assistant' && msg.tool_results?.length) {
        // Find the preceding user message for context
        let userPreview = ''
        for (let i = messages.indexOf(msg) - 1; i >= 0; i--) {
          if (messages[i].role === 'user') {
            userPreview = truncate(messages[i].content)
            break
          }
        }
        const items = msg.tool_results.map((tr) => {
          const r = tr.result as Record<string, unknown> | undefined
          const command = r?._command as string | undefined
          const stdout = r?.stdout as string | undefined
          return { name: tr.name, command, stdout, result: r }
        })
        results.push({ msgIndex: results.length, userPreview, items })
      }
    }
    return results
  }, [messages])

  const totalCount = groups.reduce((s, g) => s + g.items.length, 0)

  // Auto-scroll to bottom when new results arrive
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [totalCount])

  if (totalCount === 0 && !loading) {
    return (
      <div className="h-full flex flex-col bg-gray-50/50 border-l border-gray-200">
        <div className="shrink-0 px-3 py-1.5 border-b border-gray-100 bg-white">
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Tool Results</span>
        </div>
        <div className="flex-1 flex items-center justify-center px-4">
          <p className="text-[11px] text-gray-400 text-center leading-relaxed">
            Send a message to see skill usage,<br />executed code, and results here.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gray-50/50 border-l border-gray-200">
      {/* Header */}
      <div className="shrink-0 px-3 py-1.5 border-b border-gray-100 bg-white">
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
          Tool Results
          {totalCount > 0 && <span className="ml-1 font-normal">({totalCount})</span>}
        </span>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4 text-[11px] text-gray-700">
        {groups.map((group) => (
          <div key={group.msgIndex}>
            {/* Group header */}
            <div className="flex items-center gap-1.5 mb-2">
              <span className="text-[9px] font-medium text-gray-400 uppercase">Msg {group.msgIndex + 1}</span>
              {group.userPreview && (
                <span className="text-[9px] text-gray-300 truncate">— {group.userPreview}</span>
              )}
            </div>

            {/* Items */}
            {group.items.map((item, idx) => (
              <div key={idx} className="mb-3 pb-3 border-b border-gray-200 last:border-b-0 last:pb-0">
                {/* Skill name */}
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-[10px] font-semibold text-blue-600">
                    {item.command ? extractScriptName(item.command) || item.name : item.name}
                  </span>
                  {item.name === 'shell' && (
                    <span className="text-[8px] bg-gray-200 text-gray-500 px-1 rounded">shell</span>
                  )}
                </div>

                {/* Executed code */}
                {item.command && (
                  <pre className="text-[9px] bg-gray-900 text-green-400 rounded p-2 mb-1.5 overflow-x-auto whitespace-pre-wrap max-h-24 overflow-y-auto font-mono leading-relaxed">
                    {item.command}
                  </pre>
                )}

                {/* Images extracted from stdout */}
                {item.stdout && extractImages(item.stdout).map((img, i) => (
                  <div key={i} className="mb-1">
                    <img
                      src={img.url}
                      alt={img.alt}
                      className="max-w-full h-auto rounded border border-gray-200"
                      style={{ maxHeight: 120 }}
                    />
                  </div>
                ))}

                {/* Download links from stdout */}
                {item.stdout && extractDownloadLinks(item.stdout).filter(l => !l.label.startsWith('⬇')).map((link, i) => (
                  <div key={i}>
                    <a href={link.url} download className="text-[9px] text-blue-500 hover:text-blue-700 hover:underline">
                      ⬇ {link.label}
                    </a>
                  </div>
                ))}

                {/* Result summary for non-shell results */}
                {item.name !== 'shell' && (item.result as any) ? (
                  <div className="text-[10px] text-gray-500 mt-0.5">
                    {typeof item.result === 'object'
                      ? Object.entries(item.result as Record<string, unknown>)
                          .filter(([k]) => !k.startsWith('_'))
                          .slice(0, 3)
                          .map(([k, v]) => (
                            <span key={k} className="mr-2">
                              {k}: {Array.isArray(v) ? `[${v.length}]` : String(v).slice(0, 60)}
                            </span>
                          ))
                      : String(item.result).slice(0, 100)}
                  </div>
                ) : null}

                {/* Key numbers from stdout */}
                {item.stdout && !item.command && (
                  <div className="text-[10px] text-gray-500 mt-0.5 whitespace-pre-wrap line-clamp-3">
                    {item.stdout.slice(0, 200)}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}

        {loading && (
          <div className="flex items-center justify-center py-3">
            <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />
          </div>
        )}

        <div ref={scrollRef} />
      </div>
    </div>
  )
}
