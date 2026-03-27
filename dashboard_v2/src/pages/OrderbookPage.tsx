import { useState, useCallback } from 'react'
import { useOrderbook } from '../hooks'
import { useUIStore } from '../stores'
import { api } from '../lib/api'
import { formatINR, cn } from '../lib/utils'
import { BookOpen, XCircle, RefreshCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

export default function OrderbookPage() {
  const { data, isLoading, refetch } = useOrderbook()
  const { addToast } = useUIStore()
  const client = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'open' | 'executed' | 'failed'>('all')
  const openStatuses = ['OPEN', 'PENDING', 'TRIGGER_PENDING', 'SL-PENDING', 'CREATED', 'SENT_TO_BROKER']

  const orders = data?.orders || []

  const filtered = orders.filter(o => {
    const st = (o.status || '').toUpperCase()
    if (filter === 'open') return openStatuses.includes(st)
    if (filter === 'executed') return st.includes('EXEC') || st.includes('COMPLETE')
    if (filter === 'failed') return st.includes('FAIL') || st.includes('REJECT') || st.includes('CANCEL')
    return true
  })

  const handleCancel = useCallback(async (orderId: string) => {
    try {
      await api.cancelOrder(orderId)
      addToast('success', `Order ${orderId} cancelled`)
      client.invalidateQueries({ queryKey: ['orderbook'] })
    } catch (e: unknown) {
      addToast('error', `Cancel failed: ${e instanceof Error ? e.message : 'Unknown'}`)
    }
  }, [addToast, client])

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <BookOpen className="w-5 h-5 text-primary" />
        <h1 className="text-sm font-semibold text-text-bright">Orderbook</h1>
        <span className="text-[11px] text-text-muted">{orders.length} orders</span>

        <div className="flex-1" />

        <div className="flex gap-1">
          {(['all', 'open', 'executed', 'failed'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-2.5 py-1 rounded-md text-[11px] font-medium border transition-colors capitalize',
                filter === f
                  ? 'bg-primary/10 text-primary border-primary/30'
                  : 'text-text-muted border-border hover:border-border-hover'
              )}
            >
              {f}
            </button>
          ))}
        </div>

        <button onClick={() => refetch()} className="text-text-muted hover:text-text-primary p-1">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Table */}
      <div className="glass rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="text-center py-12 text-text-muted text-[13px]">Loading orderbook...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-text-muted text-[13px]">No orders</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border bg-bg-surface/50">
                  <th className="text-left px-3 py-2 font-semibold text-text-muted">Source</th>
                  <th className="text-left px-3 py-2 font-semibold text-text-muted">Symbol</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted">Side</th>
                  <th className="text-right px-3 py-2 font-semibold text-text-muted">Qty</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted hide-mobile">Type</th>
                  <th className="text-right px-3 py-2 font-semibold text-text-muted">Price</th>
                  <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Trigger</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted hide-mobile">Product</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted">Status</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted hide-mobile">Order ID</th>
                  <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Updated</th>
                  <th className="text-center px-3 py-2 font-semibold text-text-muted">Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o, i) => {
                  const side = o.side || (o.trantype === 'B' ? 'BUY' : o.trantype === 'S' ? 'SELL' : '—')
                  const status = (o.status || '—').toUpperCase()
                  const statusClass = status.includes('EXEC') || status.includes('COMPLETE') ? 'badge-safe'
                    : status.includes('FAIL') || status.includes('REJECT') ? 'badge-danger'
                    : status.includes('CANCEL') ? 'badge-warning'
                    : openStatuses.includes(status) ? 'badge-mock'
                    : 'badge-neutral'
                  const canCancel = o.source === 'SYSTEM' && openStatuses.includes(status)
                  const orderId = o.order_id || o.norenordno || ''

                  return (
                    <tr key={orderId || i} className="border-b border-border/30 hover:bg-bg-hover/30 transition-colors">
                      <td className="px-3 py-2">
                        <span className={cn('badge', o.source === 'SYSTEM' ? 'badge-mock' : 'badge-warning')}>
                          {o.source || 'BROKER'}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-[11px] text-text-bright font-semibold">
                        {o.tsym || o.symbol || '—'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={cn('badge', side === 'BUY' ? 'badge-buy' : 'badge-sell')}>{side}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{o.qty || o.quantity || '—'}</td>
                      <td className="px-3 py-2 text-center text-text-muted hide-mobile">{o.prctyp || o.order_type || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{formatINR(o.prc || o.price || 0)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-text-muted hide-mobile">
                        {o.trgprc || o.trigger_price ? formatINR(o.trgprc || o.trigger_price || 0) : '—'}
                      </td>
                      <td className="px-3 py-2 text-center hide-mobile">
                        <span className="badge badge-neutral">{o.prd || o.product || '—'}</span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={cn('badge', statusClass)}>{status}</span>
                      </td>
                      <td className="px-3 py-2 text-center text-[10px] text-text-muted font-mono hide-mobile">
                        {orderId ? orderId.slice(-8) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right text-[11px] text-text-muted hide-mobile">
                        {o.updated_at || o.norentm || '—'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {canCancel && (
                          <button
                            onClick={() => handleCancel(orderId)}
                            className="text-loss/70 hover:text-loss transition-colors p-1"
                            title="Cancel order"
                          >
                            <XCircle className="w-3.5 h-3.5" />
                          </button>
                        )}
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
