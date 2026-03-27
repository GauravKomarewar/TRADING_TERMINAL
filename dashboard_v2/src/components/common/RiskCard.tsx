import { useDashboardStore } from '../../stores'
import { formatINR, pnlClass, cn } from '../../lib/utils'
import { Shield } from 'lucide-react'

export function RiskCard() {
  const risk = useDashboardStore(s => s.snapshot?.system?.risk)

  const pnl = risk?.daily_pnl ?? 0
  const maxLoss = risk?.max_loss_limit ?? -2500
  const peak = risk?.peak_profit ?? 0
  const distance = Math.abs(maxLoss) - Math.abs(pnl < 0 ? pnl : 0)
  const distPct = maxLoss !== 0 ? (distance / Math.abs(maxLoss)) * 100 : 100
  const status = risk?.status || 'SAFE'

  const statusColor = status === 'SAFE' ? 'text-profit' : status === 'WARNING' ? 'text-warning' : 'text-loss'
  const barColor = status === 'SAFE' ? 'bg-profit' : status === 'WARNING' ? 'bg-warning' : 'bg-loss'

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Shield className={cn('w-4 h-4', statusColor)} />
          <h3 className="text-sm font-semibold text-text-bright">Risk Manager</h3>
        </div>
        <span className={cn('badge', status === 'SAFE' ? 'badge-safe' : status === 'WARNING' ? 'badge-warning' : 'badge-danger')}>
          {status}
        </span>
      </div>

      <div className="p-4 space-y-3">
        {/* Daily P&L */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text-muted">Daily P&L</span>
          <span className={cn('text-sm font-bold tabular-nums', pnlClass(pnl))}>{formatINR(pnl)}</span>
        </div>

        {/* Progress bar: Distance to exit */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-text-muted">Distance to Exit</span>
            <span className="text-[10px] text-text-muted">{formatINR(distance)}</span>
          </div>
          <div className="h-1.5 rounded-full bg-bg-elevated overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all duration-500', barColor)}
              style={{ width: `${Math.max(0, Math.min(100, distPct))}%` }}
            />
          </div>
        </div>

        {/* Max Loss */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text-muted">Max Loss Limit</span>
          <span className="text-[12px] text-text-secondary tabular-nums">{formatINR(maxLoss)}</span>
        </div>

        {/* Peak Profit */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text-muted">Peak Profit</span>
          <span className={cn('text-[12px] tabular-nums', pnlClass(peak))}>{formatINR(peak)}</span>
        </div>

        {/* Flags */}
        <div className="flex gap-3 pt-1">
          <div className={cn(
            'flex-1 text-center py-1.5 rounded-md text-[10px] font-semibold border',
            risk?.loss_hit ? 'bg-loss/10 text-loss border-loss/30' : 'bg-bg-elevated text-text-muted border-border'
          )}>
            {risk?.loss_hit ? '⚠ LOSS HIT' : '✓ No Loss Hit'}
          </div>
          <div className={cn(
            'flex-1 text-center py-1.5 rounded-md text-[10px] font-semibold border',
            risk?.human_violation ? 'bg-loss/10 text-loss border-loss/30' : 'bg-bg-elevated text-text-muted border-border'
          )}>
            {risk?.human_violation ? '⚠ VIOLATION' : '✓ No Violation'}
          </div>
        </div>
      </div>
    </div>
  )
}
