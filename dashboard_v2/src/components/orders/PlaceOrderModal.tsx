import { useMemo, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Loader2,
  Plus,
  Search,
  ShoppingBasket,
  Trash2,
  X,
} from 'lucide-react'
import { api } from '../../lib/api'
import { cn } from '../../lib/utils'
import { useUIStore } from '../../stores'
import type { SymbolInfo } from '../../types'

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
}

type TabKey = 'manual' | 'basket' | 'advanced'
type Side = 'BUY' | 'SELL'
type Product = 'MIS' | 'NRML' | 'CNC'
type OrderType = 'MARKET' | 'LIMIT'
type Triggered = 'NO' | 'YES'
type ExecutionMode =
  | 'ENTRY'
  | 'EXIT'
  | 'TEST_ENTRY_SUCCESS'
  | 'TEST_ENTRY_FAILURE'
  | 'TEST_EXIT_SUCCESS'
  | 'TEST_EXIT_FAILURE'

type AdvancedTargetType = 'DELTA' | 'THETA' | 'GAMMA' | 'VEGA' | 'PRICE' | 'PREMIUM'

interface ManualFormState {
  exchange: string
  symbol: string
  side: Side
  execution_mode: ExecutionMode
  qty: string
  product: Product
  order_type: OrderType
  price: string
  triggered_order: Triggered
  trigger_value: string
  target: string
  stoploss: string
  trail_sl: string
  trail_when: string
}

interface AdvancedLegState {
  id: number
  exchange: string
  symbol: string
  side: Side
  execution_mode: ExecutionMode
  qty: string
  target_type: AdvancedTargetType
  target_value: string
  product: Product
  order_type: OrderType
  price: string
}

const EXCHANGES = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS'] as const
const EXECUTION_MODES: ExecutionMode[] = [
  'ENTRY',
  'EXIT',
  'TEST_ENTRY_SUCCESS',
  'TEST_ENTRY_FAILURE',
  'TEST_EXIT_SUCCESS',
  'TEST_EXIT_FAILURE',
]

const defaultManualState = (): ManualFormState => ({
  exchange: 'NSE',
  symbol: '',
  side: 'BUY',
  execution_mode: 'ENTRY',
  qty: '1',
  product: 'MIS',
  order_type: 'MARKET',
  price: '',
  triggered_order: 'NO',
  trigger_value: '',
  target: '',
  stoploss: '',
  trail_sl: '',
  trail_when: '',
})

const defaultLeg = (id: number): AdvancedLegState => ({
  id,
  exchange: 'NSE',
  symbol: '',
  side: 'BUY',
  execution_mode: 'ENTRY',
  qty: '1',
  target_type: 'DELTA',
  target_value: '',
  product: 'MIS',
  order_type: 'MARKET',
  price: '',
})

const parseNum = (v: string) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function normalizeExecutionMode(mode: ExecutionMode): { execution_type: 'ENTRY' | 'EXIT'; test_mode: 'SUCCESS' | 'FAILURE' | null } {
  if (mode.startsWith('TEST_')) {
    const execution_type = mode.includes('ENTRY') ? 'ENTRY' : 'EXIT'
    const test_mode = mode.includes('SUCCESS') ? 'SUCCESS' : 'FAILURE'
    return { execution_type, test_mode }
  }
  return { execution_type: mode as 'ENTRY' | 'EXIT', test_mode: null }
}

function toManualPayload(state: ManualFormState) {
  const normalized = normalizeExecutionMode(state.execution_mode)
  return {
    exchange: state.exchange,
    symbol: state.symbol.trim(),
    execution_type: normalized.execution_type,
    test_mode: normalized.test_mode,
    side: state.side,
    qty: Number(state.qty || 0),
    product: state.product,
    order_type: state.order_type,
    price: state.order_type === 'LIMIT' ? parseNum(state.price) : null,
    triggered_order: state.triggered_order,
    trigger_value: state.trigger_value.trim() ? parseNum(state.trigger_value) : null,
    target: state.target.trim() ? parseNum(state.target) : null,
    stoploss: state.stoploss.trim() ? parseNum(state.stoploss) : null,
    trail_sl: state.trail_sl.trim() ? parseNum(state.trail_sl) : null,
    trail_when: state.trail_when.trim() ? parseNum(state.trail_when) : null,
    reason: 'WEB_MANUAL_V2',
  }
}

function toAdvancedLegPayload(leg: AdvancedLegState) {
  const normalized = normalizeExecutionMode(leg.execution_mode)
  return {
    exchange: leg.exchange,
    symbol: leg.symbol.trim(),
    side: leg.side,
    execution_type: normalized.execution_type,
    test_mode: normalized.test_mode,
    qty: Number(leg.qty || 0),
    target_type: leg.target_type,
    target_value: leg.target_value.trim() ? parseNum(leg.target_value) : null,
    product: leg.product,
    order_type: leg.order_type,
    price: leg.order_type === 'LIMIT' ? parseNum(leg.price) : null,
  }
}

function executionBadge(mode: ExecutionMode): string {
  if (mode === 'ENTRY' || mode === 'EXIT') return mode
  return mode.replace(/_/g, ' ')
}

export default function PlaceOrderModal({ open, onOpenChange }: Props) {
  const addToast = useUIStore((s) => s.addToast)

  const [tab, setTab] = useState<TabKey>('manual')
  const [manual, setManual] = useState<ManualFormState>(defaultManualState)

  const [searchText, setSearchText] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<SymbolInfo[]>([])

  const [basketOrders, setBasketOrders] = useState<Array<ReturnType<typeof toManualPayload>>>([])
  const [advancedLegs, setAdvancedLegs] = useState<AdvancedLegState[]>([defaultLeg(0)])
  const [nextLegId, setNextLegId] = useState(1)

  const [busy, setBusy] = useState<'none' | 'manual' | 'basket' | 'advanced'>('none')

  const canSubmitManual = useMemo(() => {
    if (!manual.symbol.trim()) return false
    const qty = Number(manual.qty)
    if (!Number.isFinite(qty) || qty <= 0) return false
    if (manual.order_type === 'LIMIT' && !manual.price.trim()) return false
    if (manual.triggered_order === 'YES' && !manual.trigger_value.trim()) return false
    return true
  }, [manual])

  const sortedBasket = useMemo(() => {
    return [...basketOrders].sort((a, b) => {
      if (a.execution_type === 'EXIT' && b.execution_type !== 'EXIT') return -1
      if (a.execution_type !== 'EXIT' && b.execution_type === 'EXIT') return 1
      return 0
    })
  }, [basketOrders])

  const updateManual = (patch: Partial<ManualFormState>) => {
    setManual((prev) => ({ ...prev, ...patch }))
  }

  const runSearch = async () => {
    const q = searchText.trim()
    if (q.length < 2) {
      setSearchResults([])
      return
    }
    setSearching(true)
    try {
      const results = await api.searchSymbols(q)
      setSearchResults(results.slice(0, 25))
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const applySymbol = (s: SymbolInfo) => {
    const symbol = s.trading_symbol || s.tradingsymbol || s.symbol
    updateManual({
      symbol,
      exchange: s.exchange || manual.exchange,
      qty: s.lot_size && s.lot_size > 0 ? String(s.lot_size) : manual.qty,
    })
    setSearchText(symbol)
    setSearchResults([])
  }

  const submitManual = async () => {
    const payload = toManualPayload(manual)
    if (!payload.symbol || !payload.qty) return

    setBusy('manual')
    try {
      await api.placeOrder(payload)
      addToast('success', `Intent queued for ${payload.symbol}`)
      setManual(defaultManualState())
      setSearchText('')
      setSearchResults([])
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Order submit failed')
    } finally {
      setBusy('none')
    }
  }

  const addCurrentToBasket = () => {
    const payload = toManualPayload(manual)
    if (!payload.symbol || !payload.qty) {
      addToast('warning', 'Fill symbol and quantity first')
      return
    }
    setBasketOrders((prev) => [...prev, payload])
    addToast('success', `Added ${payload.symbol} to basket`)
  }

  const removeBasketOrder = (idx: number) => {
    setBasketOrders((prev) => prev.filter((_, i) => i !== idx))
  }

  const submitBasket = async () => {
    if (!sortedBasket.length) return
    setBusy('basket')
    try {
      await api.submitBasketIntent({ orders: sortedBasket, reason: 'WEB_BASKET_V2' })
      addToast('success', `Basket submitted (${sortedBasket.length} legs)`)
      setBasketOrders([])
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Basket submit failed')
    } finally {
      setBusy('none')
    }
  }

  const addLeg = () => {
    setAdvancedLegs((prev) => [...prev, defaultLeg(nextLegId)])
    setNextLegId((n) => n + 1)
  }

  const updateLeg = (id: number, patch: Partial<AdvancedLegState>) => {
    setAdvancedLegs((prev) => prev.map((leg) => (leg.id === id ? { ...leg, ...patch } : leg)))
  }

  const removeLeg = (id: number) => {
    setAdvancedLegs((prev) => prev.filter((leg) => leg.id !== id))
  }

  const submitAdvanced = async () => {
    const legs = advancedLegs.map(toAdvancedLegPayload)
    const invalid = legs.some((leg) => !leg.symbol || !Number.isFinite(leg.qty) || leg.qty <= 0)
    if (invalid) {
      addToast('warning', 'Each leg needs valid symbol and quantity')
      return
    }

    setBusy('advanced')
    try {
      await api.submitAdvancedIntent({ legs, reason: 'WEB_ADVANCED_V2' })
      addToast('success', `Advanced order submitted (${legs.length} legs)`)
      setAdvancedLegs([defaultLeg(0)])
      setNextLegId(1)
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Advanced submit failed')
    } finally {
      setBusy('none')
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 animate-fade-in" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[96vw] max-w-6xl h-[88vh] glass rounded-2xl p-4 animate-slide-up focus:outline-none flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-sm font-semibold text-text-bright">Place Orders</Dialog.Title>
            <Dialog.Close className="p-1 rounded-lg hover:bg-white/5"><X className="w-4 h-4" /></Dialog.Close>
          </div>

          <div className="flex items-center gap-2 mb-3">
            {([
              { key: 'manual', label: 'Manual' },
              { key: 'basket', label: 'Basket' },
              { key: 'advanced', label: 'Advanced' },
            ] as const).map((item) => (
              <button
                key={item.key}
                onClick={() => setTab(item.key)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-[11px] font-semibold border transition-colors',
                  tab === item.key
                    ? 'bg-primary/15 text-primary border-primary/30'
                    : 'text-text-muted border-border-subtle hover:border-border-hover'
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-auto pr-1">
            {tab === 'manual' && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Exchange</label>
                    <select value={manual.exchange} onChange={(e) => updateManual({ exchange: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                      {EXCHANGES.map((e) => <option key={e} value={e}>{e}</option>)}
                    </select>
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-[10px] text-text-muted mb-1 block">Symbol Search</label>
                    <div className="flex gap-2">
                      <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
                        <input
                          value={searchText}
                          onChange={(e) => {
                            setSearchText(e.target.value)
                            updateManual({ symbol: e.target.value.toUpperCase() })
                          }}
                          onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                          placeholder="Type symbol..."
                          className="w-full pl-8 pr-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none"
                        />
                      </div>
                      <button onClick={runSearch} className="px-3 py-2 bg-primary/10 text-primary border border-primary/30 rounded-lg text-[11px] font-semibold hover:bg-primary/20 transition-colors">
                        {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Search'}
                      </button>
                    </div>
                    {searchResults.length > 0 && (
                      <div className="mt-1.5 max-h-44 overflow-y-auto rounded-lg border border-border-subtle bg-bg-base p-1">
                        {searchResults.map((s, i) => {
                          const symbol = s.trading_symbol || s.tradingsymbol || s.symbol
                          return (
                            <button key={`${symbol}-${i}`} onClick={() => applySymbol(s)} className="w-full text-left px-2.5 py-1.5 rounded-md text-[11px] hover:bg-white/5 transition-colors flex justify-between">
                              <span className="text-text-bright font-medium">{symbol}</span>
                              <span className="text-text-muted">{s.exchange}</span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Side</label>
                    <div className="grid grid-cols-2 gap-1.5">
                      <button onClick={() => updateManual({ side: 'BUY' })} className={cn('py-2 rounded-lg text-[11px] font-semibold flex items-center justify-center gap-1 border', manual.side === 'BUY' ? 'bg-profit/15 border-profit text-profit' : 'bg-bg-base border-border-subtle text-text-muted')}><ArrowUpCircle className="w-3.5 h-3.5" />BUY</button>
                      <button onClick={() => updateManual({ side: 'SELL' })} className={cn('py-2 rounded-lg text-[11px] font-semibold flex items-center justify-center gap-1 border', manual.side === 'SELL' ? 'bg-loss/15 border-loss text-loss' : 'bg-bg-base border-border-subtle text-text-muted')}><ArrowDownCircle className="w-3.5 h-3.5" />SELL</button>
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Execution</label>
                    <select value={manual.execution_mode} onChange={(e) => updateManual({ execution_mode: e.target.value as ExecutionMode })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                      {EXECUTION_MODES.map((m) => <option key={m} value={m}>{executionBadge(m)}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Qty</label>
                    <input type="number" min="1" value={manual.qty} onChange={(e) => updateManual({ qty: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Product</label>
                    <select value={manual.product} onChange={(e) => updateManual({ product: e.target.value as Product })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                      <option value="MIS">MIS</option>
                      <option value="NRML">NRML</option>
                      <option value="CNC">CNC</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Order Type</label>
                    <select value={manual.order_type} onChange={(e) => updateManual({ order_type: e.target.value as OrderType })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                      <option value="MARKET">MARKET</option>
                      <option value="LIMIT">LIMIT</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Price</label>
                    <input type="number" step="0.05" value={manual.price} onChange={(e) => updateManual({ price: e.target.value })} disabled={manual.order_type !== 'LIMIT'} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none disabled:opacity-50" />
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Triggered</label>
                    <select value={manual.triggered_order} onChange={(e) => updateManual({ triggered_order: e.target.value as Triggered })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                      <option value="NO">NO</option>
                      <option value="YES">YES</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Trigger Value</label>
                    <input type="number" step="0.05" value={manual.trigger_value} onChange={(e) => updateManual({ trigger_value: e.target.value })} disabled={manual.triggered_order !== 'YES'} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none disabled:opacity-50" />
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Target</label>
                    <input type="number" step="0.05" value={manual.target} onChange={(e) => updateManual({ target: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Stop Loss</label>
                    <input type="number" step="0.05" value={manual.stoploss} onChange={(e) => updateManual({ stoploss: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Trail SL</label>
                    <input type="number" step="0.05" value={manual.trail_sl} onChange={(e) => updateManual({ trail_sl: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                  </div>
                  <div>
                    <label className="text-[10px] text-text-muted mb-1 block">Trail When</label>
                    <input type="number" step="0.05" value={manual.trail_when} onChange={(e) => updateManual({ trail_when: e.target.value })} className="w-full px-2.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                  <button onClick={addCurrentToBasket} className="w-full py-2.5 rounded-xl text-[12px] font-bold bg-bg-base border border-border-subtle text-text-secondary hover:border-border-hover inline-flex items-center justify-center gap-2">
                    <ShoppingBasket className="w-4 h-4" /> Add To Basket
                  </button>
                  <button onClick={submitManual} disabled={busy !== 'none' || !canSubmitManual} className={cn('w-full py-2.5 rounded-xl text-[12px] font-bold transition-all flex items-center justify-center gap-2', manual.side === 'BUY' ? 'bg-profit text-white' : 'bg-loss text-white', (busy !== 'none' || !canSubmitManual) && 'opacity-50 cursor-not-allowed')}>
                    {busy === 'manual' ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    Submit Manual
                  </button>
                </div>
              </div>
            )}

            {tab === 'basket' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-border-subtle bg-bg-base px-3 py-2">
                  <div className="text-[12px] text-text-secondary">Total orders</div>
                  <div className="text-[14px] font-semibold text-text-bright">{sortedBasket.length}</div>
                </div>

                <div className="rounded-lg border border-border-subtle bg-bg-base overflow-hidden">
                  {sortedBasket.length === 0 ? (
                    <div className="text-center py-8 text-[12px] text-text-muted">No basket orders yet. Add orders from Manual tab.</div>
                  ) : (
                    <div className="max-h-[420px] overflow-auto divide-y divide-border-subtle">
                      {sortedBasket.map((o, i) => (
                        <div key={`${o.symbol}-${i}`} className="px-3 py-2.5 flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-[12px] font-semibold text-text-bright truncate">{o.exchange} {o.symbol} {o.side}</div>
                            <div className="text-[11px] text-text-muted truncate">{o.execution_type} · Qty {o.qty} · {o.order_type}{o.price ? ` @ ${o.price}` : ''}</div>
                          </div>
                          <button onClick={() => removeBasketOrder(i)} className="p-1.5 rounded text-loss/80 hover:text-loss hover:bg-loss/10" title="Remove">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <button onClick={() => setBasketOrders([])} disabled={!sortedBasket.length} className="w-full py-2.5 rounded-xl text-[12px] font-bold bg-bg-base border border-border-subtle text-text-secondary disabled:opacity-40">
                    Clear Basket
                  </button>
                  <button onClick={submitBasket} disabled={busy !== 'none' || !sortedBasket.length} className="w-full py-2.5 rounded-xl text-[12px] font-bold bg-warning text-white disabled:opacity-50 inline-flex items-center justify-center gap-2">
                    {busy === 'basket' ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    Execute Basket
                  </button>
                </div>
              </div>
            )}

            {tab === 'advanced' && (
              <div className="space-y-3">
                <div className="space-y-2">
                  {advancedLegs.map((leg, idx) => (
                    <div key={leg.id} className="rounded-xl border border-border-subtle bg-bg-base p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-[12px] font-semibold text-text-bright">Leg {idx + 1}</div>
                        <button onClick={() => removeLeg(leg.id)} className="p-1 rounded text-loss/80 hover:text-loss hover:bg-loss/10" title="Remove leg">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
                        <select value={leg.exchange} onChange={(e) => updateLeg(leg.id, { exchange: e.target.value })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          {EXCHANGES.map((e) => <option key={e} value={e}>{e}</option>)}
                        </select>
                        <input value={leg.symbol} onChange={(e) => updateLeg(leg.id, { symbol: e.target.value.toUpperCase() })} placeholder="Symbol" className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                        <select value={leg.side} onChange={(e) => updateLeg(leg.id, { side: e.target.value as Side })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          <option value="BUY">BUY</option>
                          <option value="SELL">SELL</option>
                        </select>
                        <input type="number" min="1" value={leg.qty} onChange={(e) => updateLeg(leg.id, { qty: e.target.value })} placeholder="Qty" className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
                        <select value={leg.execution_mode} onChange={(e) => updateLeg(leg.id, { execution_mode: e.target.value as ExecutionMode })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          {EXECUTION_MODES.map((m) => <option key={m} value={m}>{executionBadge(m)}</option>)}
                        </select>
                        <select value={leg.target_type} onChange={(e) => updateLeg(leg.id, { target_type: e.target.value as AdvancedTargetType })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          <option value="DELTA">DELTA</option>
                          <option value="THETA">THETA</option>
                          <option value="GAMMA">GAMMA</option>
                          <option value="VEGA">VEGA</option>
                          <option value="PRICE">PRICE</option>
                          <option value="PREMIUM">PREMIUM</option>
                        </select>
                        <input type="number" step="0.01" value={leg.target_value} onChange={(e) => updateLeg(leg.id, { target_value: e.target.value })} placeholder="Target Value" className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none" />
                        <select value={leg.product} onChange={(e) => updateLeg(leg.id, { product: e.target.value as Product })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          <option value="MIS">MIS</option>
                          <option value="NRML">NRML</option>
                          <option value="CNC">CNC</option>
                        </select>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        <select value={leg.order_type} onChange={(e) => updateLeg(leg.id, { order_type: e.target.value as OrderType })} className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none">
                          <option value="MARKET">MARKET</option>
                          <option value="LIMIT">LIMIT</option>
                        </select>
                        <input type="number" step="0.05" value={leg.price} onChange={(e) => updateLeg(leg.id, { price: e.target.value })} disabled={leg.order_type !== 'LIMIT'} placeholder="Price" className="px-2.5 py-2 bg-bg-elevated border border-border-subtle rounded-lg text-[11px] text-text-primary focus:border-primary focus:outline-none disabled:opacity-50" />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <button onClick={addLeg} className="w-full py-2.5 rounded-xl text-[12px] font-bold bg-bg-base border border-border-subtle text-text-secondary inline-flex items-center justify-center gap-2">
                    <Plus className="w-4 h-4" /> Add Leg
                  </button>
                  <button onClick={submitAdvanced} disabled={busy !== 'none' || !advancedLegs.length} className="w-full py-2.5 rounded-xl text-[12px] font-bold bg-primary text-white disabled:opacity-50 inline-flex items-center justify-center gap-2">
                    {busy === 'advanced' ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    Execute Advanced
                  </button>
                </div>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
