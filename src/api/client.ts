const apiCache = new Map<string, { data: unknown; timestamp: number }>()
const CACHE_TTL = 5 * 60 * 1000

export async function apiFetch<T>(url: string, options?: RequestInit, timeoutMs = 60_000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const res = await fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer))
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// An empty list from these endpoints means "nothing available right now", not
// "nothing exists": the backend answers [] for every list request until its
// initial filesystem scan finishes, and a tissue page opened in that window
// would otherwise pin that [] for the full TTL — outliving the scan and making
// a healthy dataset list look permanently empty. Empty arrays are cheap to
// refetch, so they are never cached.
const isEmptyList = (data: unknown): boolean => Array.isArray(data) && data.length === 0

export async function cachedFetch<T>(url: string, ttl = CACHE_TTL): Promise<T> {
  const cached = apiCache.get(url)
  if (cached && Date.now() - cached.timestamp < ttl) {
    return cached.data as T
  }
  const data = await apiFetch<T>(url)
  if (!isEmptyList(data)) {
    apiCache.set(url, { data, timestamp: Date.now() })
  }
  return data
}

export function clearCache() {
  apiCache.clear()
}

export function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toLocaleString()
}
