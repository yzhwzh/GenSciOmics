import { useNavigate } from 'react-router-dom'
import { DATASETS } from '../data/mockData'
import { ORGAN_SVG } from '../data/organIcons'

const CARD_COLORS = [
  'from-blue-50 to-blue-100', 'from-cyan-50 to-cyan-100',
  'from-indigo-50 to-indigo-100', 'from-sky-50 to-sky-100',
  'from-blue-50 to-indigo-100', 'from-cyan-50 to-sky-100',
  'from-blue-50 to-cyan-100', 'from-indigo-50 to-blue-100',
  'from-sky-50 to-blue-100', 'from-cyan-50 to-indigo-100',
  'from-blue-50 to-sky-100', 'from-indigo-50 to-cyan-100',
  'from-sky-50 to-indigo-100', 'from-cyan-50 to-blue-100',
]

function OrganIcon({ slug }: { slug: string }) {
  const icon = ORGAN_SVG[slug]
  if (!icon) return null
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
      <h2 className="text-base font-semibold text-brand-dark mb-3">
        Core datasets
      </h2>
      <div className="grid grid-cols-4 gap-2.5">
        {DATASETS.map((ds, i) => (
          <button
            key={ds.id}
            onClick={() => navigate(`/tissue/${ds.slug}`)}
            className="flex flex-col items-center gap-1.5 p-3 bg-white rounded-xl border border-brand-border shadow-sm hover:shadow-md hover:border-brand-light transition-all cursor-pointer group"
          >
            <div
              className={`w-10 h-10 rounded-lg bg-gradient-to-br ${CARD_COLORS[i % CARD_COLORS.length]} flex items-center justify-center text-brand group-hover:scale-105 transition-transform`}
            >
              <OrganIcon slug={ds.slug} />
            </div>
            <span className="text-xs text-gray-700 text-center leading-tight group-hover:text-brand transition-colors">
              {ds.label}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
