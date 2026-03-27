import { useState, useCallback } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X, Search, ArrowUpCircle, ArrowDownCircle, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'
import { api } from '../../lib/api'
import { useUIStore } from '../../stores'
import type { SymbolInfo } from '../../types'

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
}

export default function PlaceOrderModal({ open, onOpenChange }: Props) {
  const addToast = useUIStore((s) => s.addToast)
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<SymbolInfo[]>([])
  const [selected, setSelected] = useState<SymbolInfo | null>(null)
  const [searching, setSearching] = useState(false)

  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT' | 'SL' | 'SL-M'>('MARKET')
  const [qty, setQty] = useState('')
  const [price, setPrice] = useState('')
  const [triggerPrice, setTriggerPrice] = useState('')
  const [product, setProduct] = useState<'NRML' | 'MIS' | 'CNC'>('NRML')
  const [submitting, setSubmitting] = useState(false)

  const doSearch = useCallback(async () => {
    if (search.length < 2) return
    setSearching(true)
    try {
      const r = await api.searchSymbols(search)
      setResults(Array.isArray(r) ? r : [])
    } catch { setResults([]) }
    setSearching(false)
  }, [search])

  const handleSubmit = async () => {
    if (!selected || !qty || !selected.exchange) return
    setSubmitting(true)
    try {
      const normalizedOrderType = orderType === 'SL-M' ? 'SLM' : orderType
      const isTriggeredOrder = orderType === 'SL' || orderType === 'SL-M'
      const symbol = selected.trading_symbol || selected.tradingsymbol || selected.symbol

      await api.placeOrder({
        exchange: selected.exchange,
        symbol,
        execution_type: 'ENTRY',
        side,
        qty: Number(qty),
        order_type: normalizedOrderType,
        product,
        price: orderType === 'LIMIT' || orderType === 'SL' ? Number(price) : undefined,
        triggered_order: isTriggeredOrder ? 'YES' : 'NO',
        trigger_value: isTriggeredOrder ? Number(triggerPrice) : undefined,
        reason: 'DASHBOARD_V2_MANUAL_ORDER',
      })
      addToast('success', `${side} intent submitted for ${symbol}`)
      onOpenChange(false)
      resetForm()
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Order failed')
    }
    setSubmitting(false)
  }

  const resetForm = () => {
    setSearch(''); setResults([]); setSelected(null)
    setSide('BUY'); setOrderType('MARKET'); setQty(''); setPrice(''); setTriggerPrice('')
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 animate-fade-in" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[95vw] max-w-md glass rounded-2xl p-5 animate-slide-up focus:outline-none">
          <div className="flex items-center justify-between mb-4">
            <Dialog.Title className="text-sm font-semibold text-text-bright">Place Order</Dialog.Title>
            <Dialog.Close className="p-1 rounded-lg hover:bg-white/5"><X className="w-4 h-4" /></Dialog.Close>
          </div>

          {/* Symbol Search */}
          {!selected ? (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && doSearch()}
                    placeholder="Search symbol..."
                    className="w-full pl-8 pr-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-[12px] text-text-primary focus:border-primary focus:outline-none"
                  />
                </div>
                <button onClick={doSearch} disabled={searching} className="px-3 py-2 bg-primary/10 text-primary border border-primary/30 rounded-lg text-[11px] font-semibold hover:bg-primary/20 transition-colors">
                  {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Search'}
                </button>
              </div>
              {results.length > 0 && (
                <div className="max-h-48 overflow-y-auto space-y-0.5 rounded-lg border border-border-subtle bg-bg-base p-1">
                  {results.slice(0, 20).map((s, i) => (
                    <button
                      key={i}
                      onClick={() => { setSelected(s); setResults([]) }}
                      className="w-full text-left px-2.5 py-1.5 rounded-md text-[11px] hover:bg-white/5 transition-colors flex justify-between"
                    >
                      <span className="text-text-bright font-medium">{s.trading_symbol || s.tradingsymbol || s.symbol}</span>
                      <span className="text-text-muted">{s.exchange}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {/* Selected Symbol */}
              <div className="flex items-center justify-between px-3 py-2 bg-bg-base rounded-lg border border-border-subtle">
                <div>
                  <div className="text-[12px] font-semibold text-text-bright">
                    {selected.trading_symbol || selected.tradingsymbol || selected.symbol}
                  </div>
                  <div className="text-[10px] text-text-muted">{selected.exchange}</div>
                </div>
                <button onClick={() => setSelected(null)} className="text-[10px] text-text-muted hover:text-text-primary">Change</button>
              </div>

              {/* Side Toggle */}
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => setSide('BUY')}
                  className={cn(
                    'py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-1.5 transition-all border',
                    side === 'BUY'
                      ? 'bg-profit/15 border-profit text-profit'
                      : 'bg-bg-base border-border-subtle text-text-muted hover:border-profit/50'
                  )}
                >
                  <ArrowUpCircle className="w-3.5 h-3.5" /> BUY
                </button>
                <button
                  onClick={() => setSide('SELL')}
                  className={cn(
                    'py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-1.5 transition-all border',
                    side === 'SELL'
                      ? 'bg-loss/15 border-loss text-loss'
                      : 'bg-bg-base border-border-subtle text-text-muted hover:border-loss/50'
                  )}
                >
                  <ArrowDownCircle className="w-3.5 h-3.5" /> SELL
                </button>
              </div>

              {/* Order Type & Product */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-text-muted mb-1 block">Order Type</label>
                  <select
                    value={orderType}
                    onChange={(e) => setOrderType(e.target.value as typeof orderType)}
                    className="w-full px-2.5 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                  >
                    <option value="MARKET">MARKET</option>
                    <option value="LIMIT">LIMIT</option>
                    <option value="SL">SL</option>
                    <option value="SL-M">SL-M</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-text-muted mb-1 block">Product</label>
                  <select
                    value={product}
                    onChange={(e) => setProduct(e.target.value as typeof product)}
                    className="w-full px-2.5 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                  >
                    <option value="NRML">NRML</option>
                    <option value="MIS">MIS</option>
                    <option value="CNC">CNC</option>
                  </select>
                </div>
              </div>

              {/* Qty + Price Fields */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-text-muted mb-1 block">Quantity</label>
                  <input
                    type="number"
                    value={qty}
                    onChange={(e) => setQty(e.target.value)}
                    placeholder="Qty"
                    className="w-full px-2.5 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                  />
                </div>
                {(orderType === 'LIMIT' || orderType === 'SL') && (
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Price</label>
                    <input
                      type="number"
                      step="0.05"
                      value={price}
                      onChange={(e) => setPrice(e.target.value)}
                      placeholder="Price"
                      className="w-full px-2.5 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                    />
                  </div>
                )}
                {(orderType === 'SL' || orderType === 'SL-M') && (
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Trigger Price</label>
                    <input
                      type="number"
                      step="0.05"
                      value={triggerPrice}
                      onChange={(e) => setTriggerPrice(e.target.value)}
                      placeholder="Trigger"
                      className="w-full px-2.5 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                    />
                  </div>
                )}
              </div>

              {/* Submit */}
              <button
                onClick={handleSubmit}
                disabled={
                  submitting
                  || !qty
                  || ((orderType === 'LIMIT' || orderType === 'SL') && !price)
                  || ((orderType === 'SL' || orderType === 'SL-M') && !triggerPrice)
                }
                className={cn(
                  'w-full py-2.5 rounded-xl text-[12px] font-bold transition-all flex items-center justify-center gap-2',
                  side === 'BUY'
                    ? 'bg-profit text-white shadow-[0_0_20px_rgba(34,197,94,.3)] hover:shadow-[0_0_30px_rgba(34,197,94,.5)]'
                    : 'bg-loss text-white shadow-[0_0_20px_rgba(239,68,68,.3)] hover:shadow-[0_0_30px_rgba(239,68,68,.5)]',
                  (submitting || !qty) && 'opacity-50 cursor-not-allowed'
                )}
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {side} {selected.trading_symbol || selected.tradingsymbol || selected.symbol}
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
