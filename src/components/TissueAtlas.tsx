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

export default function TissueAtlas() {
  const navigate = useNavigate()
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [tissueDiseases, setTissueDiseases] = useState<TissueDiseaseMap>({})
  const [species, setSpecies] = useState('Human')

  const SPECIES_LIST = ['Human', 'Mouse', 'Monkey']
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
        <h2 className="text-base font-semibold text-brand-dark">Browse by Tissue atlas</h2>
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
          {['Human', 'Mouse', 'Monkey'].map(sp => (
            <button key={sp} onClick={() => setSpecies(sp)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                species === sp ? 'bg-white text-brand shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}>{sp}</button>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-xl border border-brand-border shadow-sm p-4">
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
              <image href={BASE_BG} x="0" y="0" width="100%" height="100%" opacity="0.4" preserveAspectRatio="xMinYMin meet" />
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
                        fill={isHovered ? 'rgba(59, 68, 172, 0.25)' : 'rgba(59, 68, 172, 0.04)'}
                        stroke={isHovered ? 'rgba(59, 68, 172, 0.6)' : 'rgba(59, 68, 172, 0.12)'}
                        strokeWidth={isHovered ? 2.5 : 1}
                        strokeDasharray={isHovered ? '5 3' : 'none'}
                      />
                    ))}
                  </g>
                )
              })}
            </svg>
            {hovered && (
              <div className="absolute bg-white rounded-lg shadow-lg border border-gray-200 p-2.5 z-10 pointer-events-none"
                style={{ left: Math.min(mousePos.x + 14, 260), top: Math.max(mousePos.y - 10, 0) }}>
                <div className="text-[11px] font-semibold text-brand-dark whitespace-nowrap">{hovered.label}</div>
                {liveDiseases.length > 0 ? (
                  <div className="mt-1 space-y-0.5">
                    {liveDiseases.slice(0, 5).map(d => (
                      <div key={d.name} className="text-[10px] text-gray-500 flex justify-between gap-3">
                        <span>{d.name}</span><span className="font-mono text-gray-400">{d.count}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[9px] text-gray-400 mt-0.5 italic">No datasets yet</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
