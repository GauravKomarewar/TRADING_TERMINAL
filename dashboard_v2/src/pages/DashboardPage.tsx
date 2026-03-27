import { useDashboardPolling } from '../hooks'
import { useDashboardStore } from '../stores'
import { KPIStrip } from '../components/positions/KPIStrip'
import { PositionsTable } from '../components/positions/PositionsTable'
import { OrdersPanel } from '../components/orders/OrdersPanel'
import { RiskCard } from '../components/common/RiskCard'
import { AccountCard } from '../components/common/AccountCard'
import { TelegramCard } from '../components/common/TelegramCard'

export default function DashboardPage() {
  useDashboardPolling()
  useDashboardStore(s => s.snapshot)

  return (
    <div className="space-y-4 animate-fade-in">
      {/* KPI Strip */}
      <KPIStrip />

      {/* Main Grid: 2-column on desktop */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
        {/* Left — Tables */}
        <div className="space-y-4 min-w-0">
          <PositionsTable />
          <OrdersPanel />
        </div>

        {/* Right — Sidebar Cards */}
        <div className="space-y-4">
          <RiskCard />
          <AccountCard />
          <TelegramCard />
        </div>
      </div>
    </div>
  )
}
