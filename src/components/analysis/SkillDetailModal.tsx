import { useState, useEffect } from 'react'
import { X, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props {
  skillName: string | null
  onClose: () => void
}

export default function SkillDetailModal({ skillName, onClose }: Props) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!skillName) { setContent(''); return }
    setLoading(true)
    setError('')
    fetch(`/api/skills/content?name=${encodeURIComponent(skillName)}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) { setError(data.error); setContent('') }
        else { setContent(data.content || ''); setError('') }
      })
      .catch(e => { setError(e.message); setContent('') })
      .finally(() => setLoading(false))
  }, [skillName])

  if (!skillName) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-2xl max-h-[80vh] flex flex-col m-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 shrink-0">
          <h2 className="text-sm font-semibold text-gray-800">{skillName}</h2>
          <button onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 text-xs text-gray-700 prose prose-sm max-w-none">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
            </div>
          ) : error ? (
            <p className="text-red-500">{error}</p>
          ) : content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
              table: ({ children }) => (
                <div className="overflow-x-auto"><table className="w-full text-[10px] border-collapse">{children}</table></div>
              ),
              th: ({ children }) => <th className="border border-gray-300 px-1.5 py-0.5 font-medium text-left">{children}</th>,
              td: ({ children }) => <td className="border border-gray-300 px-1.5 py-0.5">{children}</td>,
              code: ({ className, children, ...rest }) => {
                const isInline = !className
                if (isInline) return <code className="bg-gray-100 px-1 rounded text-[10px]" {...rest}>{children}</code>
                return <pre className="bg-gray-900 text-green-400 rounded p-2 text-[9px] overflow-x-auto font-mono">{children}</pre>
              },
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:text-blue-700 hover:underline">{children}</a>
              ),
            }}>
              {content}
            </ReactMarkdown>
          ) : (
            <p className="text-gray-400 text-center py-8">No content available for this skill.</p>
          )}
        </div>
      </div>
    </div>
  )
}
