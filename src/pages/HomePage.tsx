import { useEffect, useState } from 'react'
import Header from '../components/Header'
import CoreDatasets from '../components/CoreDatasets'
import TissueAtlas from '../components/TissueAtlas'
import UpdateLog from '../components/UpdateLog'
import OnlineUsers from '../components/OnlineUsers'
import StatsTable from '../components/StatsTable'
import { apiFetch } from '../api/client'

export default function HomePage() {
  const [stats, setStats] = useState({ organs: 0, diseases: 0, datasets: 0 })

  useEffect(() => {
    apiFetch<any[]>('/api/datasets').then((data) => {
      if (!Array.isArray(data)) return
      const tissues = new Set(data.map((d: any) => d.tissue?.toLowerCase()))
      const diseases = new Set(data.map((d: any) => d.disease))
      setStats({
        organs: tissues.size,
        diseases: diseases.size,
        datasets: data.length,
      })
    }).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-brand-bg">
      <Header />

      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-b from-[#eef0f7] via-brand-bg to-surface">
        <div className="absolute inset-0 pointer-events-none bg-cell-field" />
        <div className="relative z-10 max-w-4xl mx-auto text-center py-14 px-6">
          <h1 className="text-[30px] font-bold tracking-[-0.03em] text-text-primary leading-tight">
            Explore Biology Across <span className="text-brand-gold">Every Layer</span>
          </h1>
          <p className="mt-3 text-sm text-text-secondary max-w-lg mx-auto leading-relaxed">
            Single-cell · Bulk RNA · Proteomics · Metabolomics — one platform for multi-omics data exploration.
          </p>
          <div className="flex justify-center gap-10 mt-8">
            <div className="text-center">
              <div className="text-[26px] font-bold text-brand">{stats.organs || '—'}</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider mt-1">Organs</div>
            </div>
            <div className="text-center">
              <div className="text-[26px] font-bold text-brand">{stats.diseases || '—'}</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider mt-1">Diseases</div>
            </div>
            <div className="text-center">
              <div className="text-[26px] font-bold text-brand">{stats.datasets || '—'}</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider mt-1">Datasets</div>
            </div>
            <div className="text-center">
              <div className="text-[26px] font-bold text-brand">4</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider mt-1">Omics Types</div>
            </div>
          </div>
        </div>
      </section>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 pb-8">
        <div className="flex gap-5">
          <div className="w-[55%] flex flex-col gap-5">
            <CoreDatasets />
            <StatsTable />
          </div>
          <div className="w-[45%] flex flex-col gap-5">
            <TissueAtlas />
            <UpdateLog />
            <OnlineUsers />
          </div>
        </div>
      </main>
    </div>
  )
}
