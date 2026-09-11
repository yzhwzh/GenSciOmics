import { useRef, useEffect } from 'react'
import { Loader2, Bot, User, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../../api/types'

export default function ChatPanel({
  messages,
  loading,
  error,
  status,
}: {
  messages: ChatMessage[]
  loading: boolean
  error: string | null
  /**
   * What the backend says it is doing right now, from the SSE `status` event
   * (`server/agent/__init__.py:288` sends "思考中…" while a tool runs).
   * LiteratureTab has populated this on every send since it was written —
   * "Searching..." before the request, the server's message during it — but
   * nothing ever rendered it, so it fell through to the placeholder below.
   * Optional: FreeAnalysisTab has no status channel and the tests omit it.
   */
  status?: string | null
}) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="h-full overflow-y-auto px-3 py-2 space-y-3">
      {messages.filter(m => m.role !== 'system').map((msg, i) => (
        <div key={i} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
          {/* Message bubble */}
          <div className={`flex items-start gap-2 max-w-[85%] ${msg.role === 'user' ? '' : ''}`}>
            {msg.role !== 'user' && <Bot className="w-4 h-4 text-brand-light mt-0.5 shrink-0" />}
            <div className={`rounded-lg px-3 py-2 ${msg.role === 'user' ? 'bg-brand text-white' : 'bg-surface-muted text-text-secondary prose prose-sm max-w-none'}`}>
              {msg.role === 'user' ? (
                <p className="text-[11px] leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                  table: ({ children }) => <div className="overflow-x-auto"><table className="w-full text-[10px] border-collapse">{children}</table></div>,
                  th: ({ children }) => <th className="border border-border-medium px-1.5 py-0.5 font-medium text-left">{children}</th>,
                  td: ({ children }) => <td className="border border-border-medium px-1.5 py-0.5">{children}</td>,
                  h3: ({ children }) => <h3 className="text-xs font-semibold mt-1.5 mb-1">{children}</h3>,
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                }}>
                  {msg.content}
                </ReactMarkdown>
              )}
            </div>
            {msg.role === 'user' && <User className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />}
          </div>

        </div>
      ))}

      {loading && (
        <div className="flex items-center gap-2 text-text-muted px-1">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span className="text-[10px]">{status || 'Analyzing...'}</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 text-error bg-error-bg rounded-lg px-3 py-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <p className="text-[11px]">{error}</p>
        </div>
      )}

      <div ref={endRef} />
    </div>
  )
}
