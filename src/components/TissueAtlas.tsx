import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchDatasets } from '../api/datasets'
import { ORGAN_SHAPES } from '../data/mockData'
import { SPECIES_ORGANS } from '../data/organShapes'
import type { DatasetInfo } from '../api/types'

interface TissueDiseaseMap {
  [tissue: string]: { name: string; count: number }[]
}

const SPECIES_BG: Record<string, string> = {
  Human: '/shape-body.png',
  Mouse: '/assets/mouse_female.svg',
  Monkey: '/assets/monkey.svg',
}

function getOrganShapes(species: string) {
  if (species === 'Human') return ORGAN_SHAPES
  return SPECIES_ORGANS[species] || []
}

const SPECIES_LIST = ['Human', 'Mouse', 'Monkey']

export default function TissueAtlas() {
  const navigate = useNavigate()
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [tissueDiseases, setTissueDiseases] = useState<TissueDiseaseMap>({})
  const [species, setSpecies] = useState('Human')

  const organShapes = getOrganShapes(species)
  const BASE_BG = SPECIES_BG[species]

  useEffect(() => {
    const loadData = () => {
      fetchDatasets().then((data: DatasetInfo[]) => {
        if (!Array.isArray(data)) return
        const map: TissueDiseaseMap = {}
        for (const d of data) {
          const t = d.tissue?.toLowerCase() || ''
          if (!map[t]) map[t] = []
          const e = map[t].find(x => x.name === d.disease)
          if (e) e.count++; else map[t].push({ name: d.disease, count: 1 })
        }
        setTissueDiseases(map)
      }).catch(() => {})
    }
    loadData()
    const i = setInterval(loadData, 10000)
    return () => clearInterval(i)
  }, [])

  const hovered = hoveredSlug ? organShapes.find(o => o.slug === hoveredSlug) : null
  const liveDiseases = hoveredSlug ? (tissueDiseases[hoveredSlug] ?? []) : []

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-[3px] h-4 bg-brand-gold rounded-sm" />
          <h2 className="text-[15px] font-semibold text-text-primary">Tissue Atlas</h2>
        </div>
        <div className="flex items-center gap-1 bg-surface-muted rounded-lg p-0.5">
          {SPECIES_LIST.map(sp => (
            <button key={sp} onClick={() => setSpecies(sp)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                species === sp ? 'bg-surface text-brand shadow-card' : 'text-text-secondary hover:text-text-primary'
              }`}>{sp}</button>
          ))}
        </div>
      </div>
      <div className="bg-surface rounded-xl shadow-card p-4">
        <div className="relative flex justify-center" onMouseMove={e => {
          const r = e.currentTarget.getBoundingClientRect()
          setMousePos({ x: e.clientX - r.left, y: e.clientY - r.top })
        }}>
          <div className="relative w-[280px] shrink-0">
            <svg viewBox={
              species === 'Mouse' ? '0 0 85 160' :
              species === 'Monkey' ? '0 0 145 125' :
              '0 0 1000 1500'
            } className="w-full h-auto block">
              <image href={BASE_BG} x="0" y="0" width="100%" height="100%" opacity="0.12" preserveAspectRatio="xMinYMin meet" />
              {organShapes.map(organ => {
                const isHovered = hoveredSlug === organ.slug
                return (
                  <g key={organ.slug} className="pointer-events-auto cursor-pointer"
                    onClick={() => navigate(`/tissue/${organ.slug}`)}
                    onMouseEnter={() => setHoveredSlug(organ.slug)}
                    onMouseLeave={() => setHoveredSlug(null)}
                    role="button" aria-label={`${organ.label}`}>
                    {organ.paths.map((d: string, i: number) => (
                      <path key={`${organ.slug}-${i}`} d={d}
                        fill={isHovered ? 'rgba(255, 181, 72, 0.25)' : 'rgba(59, 68, 172, 0.12)'}
                        stroke={isHovered ? 'rgba(255, 181, 72, 0.6)' : 'rgba(59, 68, 172, 0.25)'}
                        strokeWidth={isHovered ? 2.5 : 1.5}
                        strokeDasharray={isHovered ? '5 3' : 'none'}
                      />
                    ))}
                  </g>
                )
              })}
            </svg>
            {hovered && (
              <div className="absolute bg-surface rounded-lg shadow-overlay border border-border-light p-2.5 z-10 pointer-events-none"
                style={{ left: Math.min(mousePos.x + 14, 260), top: Math.max(mousePos.y - 10, 0) }}>
                <div className="text-xs font-semibold text-text-primary whitespace-nowrap">{hovered.label}</div>
                {liveDiseases.length > 0 ? (
                  <div className="mt-1 space-y-0.5">
                    {liveDiseases.slice(0, 5).map(d => (
                      <div key={d.name} className="text-[11px] text-text-secondary flex justify-between gap-3">
                        <span>{d.name}</span><span className="font-mono text-text-muted">{d.count}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11px] text-text-muted mt-0.5 italic">No datasets yet</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
