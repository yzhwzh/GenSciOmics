import { useRef, useEffect } from 'react'
import { Loader2, Bot, User, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../../api/types'

export default function ChatPanel({
  messages,
  loading,
  error,
}: {
  messages: ChatMessage[]
  loading: boolean
  error: string | null
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
            {msg.role !== 'user' && <Bot className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />}
            <div className={`rounded-lg px-3 py-2 ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-700 prose prose-sm max-w-none'}`}>
              {msg.role === 'user' ? (
                <p className="text-[11px] leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                  table: ({ children }) => <div className="overflow-x-auto"><table className="w-full text-[10px] border-collapse">{children}</table></div>,
                  th: ({ children }) => <th className="border border-gray-300 px-1.5 py-0.5 font-medium text-left">{children}</th>,
                  td: ({ children }) => <td className="border border-gray-300 px-1.5 py-0.5">{children}</td>,
                  h3: ({ children }) => <h3 className="text-xs font-semibold mt-1.5 mb-1">{children}</h3>,
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                }}>
                  {msg.content}
                </ReactMarkdown>
              )}
            </div>
            {msg.role === 'user' && <User className="w-4 h-4 text-gray-400 mt-0.5 shrink-0" />}
          </div>

        </div>
      ))}

      {loading && (
        <div className="flex items-center gap-2 text-gray-400 px-1">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span className="text-[10px]">Analyzing...</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 text-red-500 bg-red-50 rounded-lg px-3 py-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <p className="text-[11px]">{error}</p>
        </div>
      )}

      <div ref={endRef} />
    </div>
  )
}
