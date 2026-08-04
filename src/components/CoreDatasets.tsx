import { useNavigate } from 'react-router-dom'
import { DATASETS } from '../data/mockData'
import { ORGAN_SVG } from '../data/organIcons'

const CARD_COLORS = [
  'from-blue-50 to-blue-100', 'from-cyan-50 to-cyan-100',
  'from-indigo-50 to-indigo-100', 'from-sky-50 to-sky-100',
  'from-violet-50 to-violet-100', 'from-teal-50 to-teal-100',
  'from-amber-50 to-amber-100', 'from-rose-50 to-rose-100',
  'from-emerald-50 to-emerald-100', 'from-pink-50 to-pink-100',
  'from-purple-50 to-purple-100', 'from-orange-50 to-orange-100',
  'from-lime-50 to-lime-100', 'from-fuchsia-50 to-fuchsia-100',
]

function OrganIcon({ slug }: { slug: string }) {
  const icon = ORGAN_SVG[slug]
  if (!icon) {
    // Fallback: first letter of organ name
    return <span className="text-[11px] font-bold">{slug.charAt(0).toUpperCase()}</span>
  }
  return (
    <svg viewBox={icon.viewBox} className="w-5 h-5" fill="none">
      {icon.children}
    </svg>
  )
}

export default function CoreDatasets() {
  const navigate = useNavigate()

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <div className="w-[3px] h-4 bg-brand-gold rounded-sm" />
        <h2 className="text-[15px] font-semibold text-text-primary">Core Datasets</h2>
      </div>
      <div className="grid grid-cols-4 gap-2.5">
        {DATASETS.map((ds, i) => (
          <button
            key={ds.id}
            onClick={() => navigate(`/tissue/${ds.slug}`)}
            className="flex flex-col items-center gap-1.5 p-3 bg-surface rounded-xl shadow-card hover:shadow-raised hover:border-brand-gold/30 hover:-translate-y-0.5 transition-all cursor-pointer group border border-transparent"
          >
            <div
              className={`w-10 h-10 rounded-lg bg-gradient-to-br ${CARD_COLORS[i % CARD_COLORS.length]} flex items-center justify-center text-brand group-hover:scale-105 transition-transform`}
            >
              <OrganIcon slug={ds.slug} />
            </div>
            <span className="text-xs text-text-primary text-center leading-tight group-hover:text-brand transition-colors">
              {ds.label}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
