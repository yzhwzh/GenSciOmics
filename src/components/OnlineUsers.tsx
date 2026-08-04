import { useEffect, useState } from 'react'
import { Users } from 'lucide-react'

const SESSION_ID = crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)
const INTERVAL = 15000  // 15 seconds

export default function OnlineUsers() {
  const [count, setCount] = useState<number | null>(null)

  useEffect(() => {
    // Send heartbeat + fetch count on interval
    const tick = () => {
      fetch('/api/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID }),
      }).catch(() => {})
      fetch('/api/online-count')
        .then(r => r.json())
        .then(d => { if (typeof d.count === 'number') setCount(d.count) })
        .catch(() => {})
    }
    tick()
    const id = setInterval(tick, INTERVAL)
    return () => clearInterval(id)
  }, [])

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm">
      <div className="px-4 py-3 flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-green-50 flex items-center justify-center">
          <Users className="w-3.5 h-3.5 text-green-500" />
        </div>
        <div>
          <div className="text-[11px] font-semibold text-gray-800">Online Users</div>
          <div className="text-[10px] text-gray-400">
            {count !== null ? (
              <><strong className="text-green-600 text-sm">{count}</strong> active now</>
            ) : (
              'Loading...'
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
