import { Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import HomePage from './pages/HomePage'
import DatasetPage from './pages/DatasetPage'
import TissuePage from './pages/TissuePage'
import AnalysisPage from './pages/AnalysisPage'
import SearchPage from './pages/SearchPage'

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/dataset/:slug" element={<DatasetPage />} />
        <Route path="/tissue/:slug" element={<TissuePage />} />
        <Route path="/analysis/:tissue/:disease/:pmid" element={<AnalysisPage />} />
        <Route path="/search" element={<SearchPage />} />
      </Routes>
    </ErrorBoundary>
  )
}
