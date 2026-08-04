import Header from '../components/Header'
import CoreDatasets from '../components/CoreDatasets'
import TissueAtlas from '../components/TissueAtlas'
import UpdateLog from '../components/UpdateLog'
import OnlineUsers from '../components/OnlineUsers'
import StatsTable from '../components/StatsTable'

export default function HomePage() {
  return (
    <div className="min-h-screen bg-brand-bg">
      <Header />

      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex gap-6">
          {/* Left Column - 60% */}
          <div className="w-[60%] flex flex-col gap-6">
            <CoreDatasets />
            <StatsTable />
          </div>

          {/* Right Column - 40% */}
          <div className="w-[40%] flex flex-col gap-6">
            <TissueAtlas />
            <UpdateLog />
            <OnlineUsers />
          </div>
        </div>
      </main>
    </div>
  )
}
