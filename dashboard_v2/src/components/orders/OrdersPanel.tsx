import { useDashboardStore } from '../../stores'
import { formatINR, cn } from '../../lib/utils'

export function OrdersPanel() {
  const snapshot = useDashboardStore(s => s.snapshot)
  const openStatuses = ['OPEN', 'PENDING', 'TRIGGER_PENDING', 'SL-PENDING', 'CREATED', 'SENT_TO_BROKER']
  const pendingOrders = (snapshot?.system?.open_orders || []).concat(
    (snapshot?.broker?.orders || []).filter(o => {
      const st = (o.status || '').toUpperCase()
      return openStatuses.includes(st)
    })
  )
  const recentOrders = (snapshot?.system?.orders || []).slice(0, 15)

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <h2 className="text-sm font-semibold text-text-bright">Orders</h2>
        {pendingOrders.length > 0 && (
          <span className="badge badge-warning">{pendingOrders.length} pending</span>
        )}
      </div>

      {/* Pending Orders */}
      {pendingOrders.length > 0 && (
        <div className="border-b border-border">
          <div className="px-4 py-1.5 bg-warning/5 text-[11px] font-semibold text-warning uppercase tracking-wider">
            Pending / Open
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border/50 bg-bg-surface/30">
                  <th className="text-left px-3 py-1.5 font-semibold text-text-muted">Source</th>
                  <th className="text-left px-3 py-1.5 font-semibold text-text-muted">Symbol</th>
                  <th className="text-center px-3 py-1.5 font-semibold text-text-muted">Side</th>
                  <th className="text-right px-3 py-1.5 font-semibold text-text-muted">Qty</th>
                  <th className="text-right px-3 py-1.5 font-semibold text-text-muted hide-mobile">Price</th>
                  <th className="text-center px-3 py-1.5 font-semibold text-text-muted">Status</th>
                </tr>
              </thead>
              <tbody>
                {pendingOrders.map((o, i) => {
                  const side = o.side || (o.trantype === 'B' ? 'BUY' : o.trantype === 'S' ? 'SELL' : '—')
                  return (
                    <tr key={o.order_id || o.norenordno || i} className="border-b border-border/30 hover:bg-bg-hover/30">
                      <td className="px-3 py-2">
                        <span className={cn('badge', o.source === 'SYSTEM' ? 'badge-mock' : 'badge-warning')}>
                          {o.source || 'BROKER'}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-[11px] text-text-bright">{o.tsym || o.symbol || '—'}</td>
                      <td className="px-3 py-2 text-center">
                        <span className={cn('badge', side === 'BUY' ? 'badge-buy' : 'badge-sell')}>{side}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{o.qty || o.quantity || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums hide-mobile">{formatINR(o.prc || o.price || 0)}</td>
                      <td className="px-3 py-2 text-center">
                        <span className="badge badge-warning">{o.status || '—'}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent Orders */}
      <div>
        <div className="px-4 py-1.5 bg-bg-surface/30 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
          Recent ({recentOrders.length})
        </div>
        {recentOrders.length === 0 ? (
          <div className="text-center py-6 text-[13px] text-text-muted">No recent orders</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border/50">
                  <th className="text-left px-3 py-1.5 font-semibold text-text-muted">Symbol</th>
                  <th className="text-center px-3 py-1.5 font-semibold text-text-muted">Side</th>
                  <th className="text-right px-3 py-1.5 font-semibold text-text-muted">Qty</th>
                  <th className="text-right px-3 py-1.5 font-semibold text-text-muted hide-mobile">Price</th>
                  <th className="text-center px-3 py-1.5 font-semibold text-text-muted">Status</th>
                  <th className="text-right px-3 py-1.5 font-semibold text-text-muted hide-mobile">Updated</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((o, i) => {
                  const side = o.side || (o.trantype === 'B' ? 'BUY' : o.trantype === 'S' ? 'SELL' : '—')
                  const status = (o.status || '—').toUpperCase()
                  const statusClass = status.includes('EXEC') ? 'badge-safe'
                    : status.includes('FAIL') || status.includes('REJECT') ? 'badge-danger'
                    : status.includes('CANCEL') ? 'badge-warning'
                    : openStatuses.includes(status) ? 'badge-mock'
                    : 'badge-neutral'
                  return (
                    <tr key={o.order_id || o.norenordno || i} className="border-b border-border/30 hover:bg-bg-hover/30">
                      <td className="px-3 py-2 font-mono text-[11px] text-text-bright">{o.tsym || o.symbol || '—'}</td>
                      <td className="px-3 py-2 text-center">
                        <span className={cn('badge', side === 'BUY' ? 'badge-buy' : 'badge-sell')}>{side}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{o.qty || o.quantity || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums hide-mobile">{formatINR(o.prc || o.price || 0)}</td>
                      <td className="px-3 py-2 text-center">
                        <span className={cn('badge', statusClass)}>{status}</span>
                      </td>
                      <td className="px-3 py-2 text-right text-[11px] text-text-muted hide-mobile">
                        {o.updated_at || o.norentm || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
