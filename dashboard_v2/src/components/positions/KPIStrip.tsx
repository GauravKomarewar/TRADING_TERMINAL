import { useDashboardStore } from '../../stores'
import { formatINR, pnlClass } from '../../lib/utils'
import { TrendingUp, BarChart3, AlertTriangle, Wifi, Shield } from 'lucide-react'

export function KPIStrip() {
  const snapshot = useDashboardStore(s => s.snapshot)
  const summary = snapshot?.broker?.positions_summary
  const risk = snapshot?.system?.risk
  const broker = snapshot?.system?.heartbeat?.status || 'UNKNOWN'
  const telegStats = snapshot?.system?.telegram_stats
  const managedCount = snapshot?.managed_exits?.length || 0

  const netPnl = summary?.net_pnl ?? 0
  const openCount = summary?.open_count ?? 0
  const alertCount = (telegStats?.total ?? 0)

  const items = [
    {
      label: 'Net P&L',
      value: formatINR(netPnl),
      icon: TrendingUp,
      color: pnlClass(netPnl),
    },
    {
      label: 'Open Positions',
      value: String(openCount),
      sub: managedCount > 0 ? `${managedCount} managed` : undefined,
      icon: BarChart3,
      color: 'text-primary',
    },
    {
      label: 'Alerts',
      value: String(alertCount),
      sub: telegStats ? `${telegStats.success || 0} sent` : undefined,
      icon: AlertTriangle,
      color: 'text-warning',
    },
    {
      label: 'Risk',
      value: risk?.status || 'SAFE',
      icon: Shield,
      color: risk?.status === 'SAFE' ? 'text-profit' : risk?.status === 'WARNING' ? 'text-warning' : 'text-loss',
      isBadge: true,
    },
    {
      label: 'Broker',
      value: broker,
      icon: Wifi,
      color: broker === 'CONNECTED' ? 'text-profit' : 'text-text-muted',
      isBadge: true,
    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
      {items.map(item => (
        <div key={item.label} className="glass rounded-xl px-4 py-3 flex items-start gap-3 hover:border-border-hover transition-colors">
          <div className={`mt-0.5 ${item.color}`}>
            <item.icon className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="text-[11px] font-medium text-text-muted uppercase tracking-wider">{item.label}</div>
            {item.isBadge ? (
              <div className={`text-sm font-bold ${item.color}`}>{item.value}</div>
            ) : (
              <div className={`text-lg font-bold tabular-nums ${item.color}`}>{item.value}</div>
            )}
            {item.sub && <div className="text-[11px] text-text-muted">{item.sub}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
