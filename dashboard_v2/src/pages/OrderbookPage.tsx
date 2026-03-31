import { useState, useCallback } from 'react'
import { useOrderbook } from '../hooks'
import { useUIStore } from '../stores'
import { api } from '../lib/api'
import { formatINR, cn } from '../lib/utils'
import { BookOpen, Download, Edit3, RefreshCw, XCircle } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

type ModifyState = {
  open: boolean
  orderId: string
  source: 'SYSTEM' | 'BROKER'
  orderType: 'MARKET' | 'LIMIT'
  price: string
  quantity: string
}

export default function OrderbookPage() {
  const { data, isLoading, refetch } = useOrderbook()
  const { addToast } = useUIStore()
  const client = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'open' | 'executed' | 'failed'>('all')
  const [modifying, setModifying] = useState<ModifyState>({
    open: false,
    orderId: '',
    source: 'SYSTEM',
    orderType: 'MARKET',
    price: '',
    quantity: '',
  })
  const [bulkBusy, setBulkBusy] = useState('')
  const [modifyBusy, setModifyBusy] = useState(false)
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

  const handleBrokerCancel = useCallback(async (orderId: string) => {
    try {
      await api.cancelBrokerOrder(orderId)
      addToast('success', `Broker order ${orderId} cancel requested`)
      client.invalidateQueries({ queryKey: ['orderbook'] })
    } catch (e: unknown) {
      addToast('error', `Broker cancel failed: ${e instanceof Error ? e.message : 'Unknown'}`)
    }
  }, [addToast, client])

  const runBulk = useCallback(async (action: 'cancel-system-all' | 'cancel-broker-all') => {
    setBulkBusy(action)
    try {
      if (action === 'cancel-system-all') await api.cancelAllSystemOrders()
      else await api.cancelAllBrokerOrders()
      addToast('success', action === 'cancel-system-all' ? 'System cancel-all submitted' : 'Broker cancel-all submitted')
      client.invalidateQueries({ queryKey: ['orderbook'] })
    } catch (e: unknown) {
      addToast('error', `${action} failed: ${e instanceof Error ? e.message : 'Unknown'}`)
    } finally {
      setBulkBusy('')
    }
  }, [addToast, client])

  const openModifyModal = (order: import('../types').Order) => {
    const source = (order.source || 'BROKER').toUpperCase() === 'SYSTEM' ? 'SYSTEM' : 'BROKER'
    setModifying({
      open: true,
      orderId: String(order.order_id || order.norenordno || ''),
      source,
      orderType: String(order.prctyp || order.order_type || 'MARKET').toUpperCase() === 'LIMIT' ? 'LIMIT' : 'MARKET',
      price: String(order.prc || order.price || ''),
      quantity: String(order.qty || order.quantity || ''),
    })
  }

  const submitModify = useCallback(async () => {
    if (!modifying.orderId) return

    setModifyBusy(true)
    try {
      const payload = {
        order_id: modifying.orderId,
        order_type: modifying.orderType,
        price: modifying.orderType === 'LIMIT' ? Number(modifying.price || 0) : null,
        quantity: modifying.quantity ? Number(modifying.quantity) : null,
      }

      if (modifying.source === 'SYSTEM') await api.modifySystemOrder(payload)
      else await api.modifyBrokerOrder(payload)

      addToast('success', `Modify request sent for ${modifying.orderId}`)
      setModifying((state) => ({ ...state, open: false }))
      client.invalidateQueries({ queryKey: ['orderbook'] })
    } catch (e: unknown) {
      addToast('error', `Modify failed: ${e instanceof Error ? e.message : 'Unknown'}`)
    } finally {
      setModifyBusy(false)
    }
  }, [addToast, client, modifying])

  const exportCsv = useCallback((source: 'all' | 'system' | 'broker') => {
    const selectedOrders = orders.filter((order) => {
      const orderSource = String(order.source || 'BROKER').toUpperCase()
      if (source === 'system') return orderSource === 'SYSTEM'
      if (source === 'broker') return orderSource !== 'SYSTEM'
      return true
    })

    if (!selectedOrders.length) {
      addToast('warning', 'No orders available for export')
      return
    }

    const headers = [
      'source', 'order_id', 'symbol', 'side', 'qty', 'order_type', 'price', 'trigger_price', 'product', 'status', 'updated_at',
    ]
    const csvRows = [headers.join(',')]

    for (const order of selectedOrders) {
      const row = [
        order.source || 'BROKER',
        order.order_id || order.norenordno || '',
        order.tsym || order.symbol || '',
        order.side || order.trantype || '',
        order.qty || order.quantity || '',
        order.prctyp || order.order_type || '',
        order.prc || order.price || '',
        order.trgprc || order.trigger_price || '',
        order.prd || order.product || '',
        order.status || '',
        order.updated_at || order.norentm || '',
      ]
      csvRows.push(row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(','))
    }

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `orderbook-${source}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }, [addToast, orders])

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

        <button
          onClick={() => runBulk('cancel-system-all')}
          disabled={bulkBusy === 'cancel-system-all'}
          className="px-2.5 py-1 rounded-md text-[11px] font-medium border border-loss/40 text-loss disabled:opacity-50"
        >
          {bulkBusy === 'cancel-system-all' ? 'Cancelling...' : 'Cancel All System'}
        </button>

        <button
          onClick={() => runBulk('cancel-broker-all')}
          disabled={bulkBusy === 'cancel-broker-all'}
          className="px-2.5 py-1 rounded-md text-[11px] font-medium border border-loss/40 text-loss disabled:opacity-50"
        >
          {bulkBusy === 'cancel-broker-all' ? 'Cancelling...' : 'Cancel All Broker'}
        </button>

        <button
          onClick={() => exportCsv('all')}
          className="px-2.5 py-1 rounded-md text-[11px] font-medium border border-border text-text-secondary inline-flex items-center gap-1"
        >
          <Download className="w-3.5 h-3.5" /> CSV
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
                  const orderSource = (o.source || 'BROKER').toUpperCase()
                  const canCancelSystem = orderSource === 'SYSTEM' && openStatuses.includes(status)
                  const canCancelBroker = orderSource !== 'SYSTEM' && openStatuses.includes(status)
                  const canModify = openStatuses.includes(status)
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
                        <div className="flex items-center justify-center gap-1.5">
                          {canModify ? (
                            <button
                              onClick={() => openModifyModal(o)}
                              className="text-primary/80 hover:text-primary transition-colors p-1"
                              title="Modify order"
                            >
                              <Edit3 className="w-3.5 h-3.5" />
                            </button>
                          ) : null}

                          {canCancelSystem ? (
                            <button
                              onClick={() => handleCancel(orderId)}
                              className="text-loss/70 hover:text-loss transition-colors p-1"
                              title="Cancel system order"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                            </button>
                          ) : null}

                          {canCancelBroker ? (
                            <button
                              onClick={() => handleBrokerCancel(orderId)}
                              className="text-loss/70 hover:text-loss transition-colors p-1"
                              title="Cancel broker order"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modifying.open ? (
        <div className="fixed inset-0 z-[90] bg-black/60 flex items-center justify-center p-4">
          <div className="w-full max-w-md glass rounded-xl border border-border p-4 space-y-3">
            <div className="text-sm font-semibold text-text-bright">Modify Order</div>
            <div className="text-[11px] text-text-muted font-mono">{modifying.orderId} • {modifying.source}</div>

            <div className="space-y-1">
              <label className="text-[11px] text-text-muted">Order Type</label>
              <select
                value={modifying.orderType}
                onChange={(e) => setModifying((state) => ({ ...state, orderType: e.target.value as 'MARKET' | 'LIMIT' }))}
                className="w-full h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px]"
              >
                <option value="MARKET">MARKET</option>
                <option value="LIMIT">LIMIT</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-[11px] text-text-muted">Price</label>
                <input
                  value={modifying.price}
                  onChange={(e) => setModifying((state) => ({ ...state, price: e.target.value }))}
                  disabled={modifying.orderType !== 'LIMIT'}
                  className="w-full h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] disabled:opacity-50"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-text-muted">Quantity</label>
                <input
                  value={modifying.quantity}
                  onChange={(e) => setModifying((state) => ({ ...state, quantity: e.target.value }))}
                  className="w-full h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px]"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setModifying((state) => ({ ...state, open: false }))}
                className="px-3 py-1.5 rounded-md border border-border text-[12px] text-text-secondary"
              >
                Cancel
              </button>
              <button
                onClick={submitModify}
                disabled={modifyBusy}
                className="px-3 py-1.5 rounded-md bg-primary text-bg-base text-[12px] font-semibold disabled:opacity-50"
              >
                {modifyBusy ? 'Submitting...' : 'Submit'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
