import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, FolderOpen } from 'lucide-react'
import { DATASETS } from '../data/mockData'

export default function DatasetPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const dataset = DATASETS.find((d) => d.slug === slug)

  return (
    <div className="min-h-screen bg-surface-raised/50">
      <div className="bg-surface border-b border-border-light">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-text-muted hover:text-brand transition-colors mb-3"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Home
          </button>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-100 to-purple-200 flex items-center justify-center">
              <FolderOpen className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-text-primary">{dataset?.label ?? slug ?? 'Unknown Dataset'}</h1>
              <p className="text-sm text-text-muted">Dataset overview page</p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="bg-surface rounded-xl border border-border-light shadow-card p-8 text-center">
          <FolderOpen className="w-12 h-12 text-text-muted mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-text-primary mb-2">
            {dataset?.label ?? slug ?? 'Dataset'}
          </h2>
          <p className="text-sm text-text-muted max-w-md mx-auto mb-6">
            This page is under development. Dataset details and browsing capabilities will be available here.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => navigate('/')}
              className="text-sm text-brand hover:underline px-4 py-2"
            >
              Back to Home
            </button>
            <button
              onClick={() => navigate(`/tissue/${slug}`)}
              className="text-sm bg-brand text-white px-4 py-2 rounded-lg hover:bg-brand-dark transition-colors"
            >
              Browse {dataset?.label ?? ''} Datasets
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
