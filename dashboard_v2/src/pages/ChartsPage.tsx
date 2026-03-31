import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AreaSeries, CandlestickSeries, ColorType, createChart, LineSeries,
  type CandlestickData, type IChartApi, type LineData, type Time,
} from 'lightweight-charts'
import {
  ChartCandlestick, LineChart, Loader2, Plus,
  Search, Trash2, Activity, ShoppingCart, TrendingUp,
  RefreshCw, Settings, AlertCircle
} from 'lucide-react'
import { api } from '../lib/api'
import { cn, formatNum, formatINR } from '../lib/utils'
import { useUIStore } from '../stores'
import type { OhlcCandle, SymbolInfo, Strategy } from '../types'

// ─── Types ─────────────────────────────────────────────────────────────────
type ChartMode = 'candles' | 'line' | 'area'
type RangePreset = 'today' | '2d' | '7d' | '1m' | '3m'
type ThemePreset = 'trading-dark' | 'dawn' | 'matrix'
type PageTab = 'chart' | 'performance'

interface OverlaySymbol { symbol: string; color: string }

interface ChartWorkspaceState {
  symbol: string; interval: number; range: RangePreset; mode: ChartMode
  theme: ThemePreset; overlays: OverlaySymbol[]
  showSma: boolean; showEma: boolean; showVolume: boolean; showRsi: boolean
  showBb: boolean; showCci: boolean; showAtr: boolean; showMacd: boolean
  smaPeriod: number; emaPeriod: number; rsiPeriod: number; bbPeriod: number
  bbStdDev: number; cciPeriod: number; atrPeriod: number
  macdFast: number; macdSlow: number; macdSignal: number
  levels: number[]; autoRefresh: boolean; marketHoursOnly: boolean
}

const STORE_KEY = 'dashboard_v2.chart_workspace'
const OVERLAY_COLORS = ['#22d3ee', '#f59e0b', '#818cf8', '#fb7185', '#4ade80', '#38bdf8']

const THEMES: Record<ThemePreset, { panelClass: string; chartBg: string; grid: string; text: string; up: string; down: string }> = {
  'trading-dark': { panelClass: 'bg-bg-base', chartBg: '#0f131f', grid: '#242b3d', text: '#8a95ad', up: '#22c55e', down: '#f43f5e' },
  dawn: { panelClass: 'bg-[#f8fafc]', chartBg: '#f8fafc', grid: '#d7dee9', text: '#4b5563', up: '#059669', down: '#dc2626' },
  matrix: { panelClass: 'bg-[#08120b]', chartBg: '#08120b', grid: '#174724', text: '#4ade80', up: '#22c55e', down: '#facc15' },
}

const INTERVALS = [1, 3, 5, 15, 30, 60]
const RANGES: { key: RangePreset; label: string; limit: number }[] = [
  { key: 'today', label: 'Today', limit: 220 },
  { key: '2d', label: '2D', limit: 450 },
  { key: '7d', label: '7D', limit: 1200 },
  { key: '1m', label: '1M', limit: 3000 },
  { key: '3m', label: '3M', limit: 5000 },
]

const MARKET_OPEN_IST = 9 * 60 + 15  // 09:15 in minutes
const MARKET_CLOSE_IST = 15 * 60 + 30 // 15:30 in minutes

const defaultState: ChartWorkspaceState = {
  symbol: 'NIFTY', interval: 3, range: 'today', mode: 'candles', theme: 'trading-dark',
  overlays: [], showSma: true, showEma: false, showVolume: true,
  showRsi: false, showBb: false, showCci: false, showAtr: false, showMacd: false,
  smaPeriod: 20, emaPeriod: 50, rsiPeriod: 14, bbPeriod: 20, bbStdDev: 2,
  cciPeriod: 20, atrPeriod: 14, macdFast: 12, macdSlow: 26, macdSignal: 9,
  levels: [], autoRefresh: true, marketHoursOnly: true,
}

// ─── Indicator Math ──────────────────────────────────────────────────────────
function sma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = []
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    out.push(i < period - 1 ? null : sum / period)
  }
  return out
}

function ema(values: number[], period: number): Array<number | null> {
  if (!values.length) return []
  const mult = 2 / (period + 1)
  const out: Array<number | null> = []
  let prev = values[0]
  for (let i = 0; i < values.length; i++) {
    if (i === 0) { out.push(values[i]); continue }
    prev = (values[i] - prev) * mult + prev
    out.push(i < period - 1 ? null : prev)
  }
  return out
}

function rsi(data: CandlestickData<Time>[], period: number): LineData<Time>[] {
  if (data.length < period + 1) return []
  let gains = 0, losses = 0
  for (let i = 1; i <= period; i++) {
    const d = data[i].close - data[i - 1].close
    if (d > 0) gains += d; else losses -= d
  }
  let avgG = gains / period, avgL = losses / period
  const r: LineData<Time>[] = [{ time: data[period].time, value: avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL) }]
  for (let i = period + 1; i < data.length; i++) {
    const d = data[i].close - data[i - 1].close
    avgG = (avgG * (period - 1) + Math.max(d, 0)) / period
    avgL = (avgL * (period - 1) + Math.max(-d, 0)) / period
    r.push({ time: data[i].time, value: avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL) })
  }
  return r
}

function bollingerBands(data: CandlestickData<Time>[], period: number, stdDev: number) {
  const u: LineData<Time>[] = [], l: LineData<Time>[] = [], m: LineData<Time>[] = []
  for (let i = period - 1; i < data.length; i++) {
    let s = 0; for (let j = i - period + 1; j <= i; j++) s += data[j].close
    const avg = s / period
    let sq = 0; for (let j = i - period + 1; j <= i; j++) sq += (data[j].close - avg) ** 2
    const std = Math.sqrt(sq / period)
    m.push({ time: data[i].time, value: avg })
    u.push({ time: data[i].time, value: avg + stdDev * std })
    l.push({ time: data[i].time, value: avg - stdDev * std })
  }
  return { upper: u, mid: m, lower: l }
}

function buildLine(candles: CandlestickData<Time>[], values: Array<number | null>): LineData<Time>[] {
  return candles
    .map((c, i) => values[i] == null || !isFinite(values[i]!) ? null : { time: c.time, value: values[i]! })
    .filter((x): x is LineData<Time> => x != null)
}

// ─── Market Hours Filter ─────────────────────────────────────────────────────
function isMarketHours(tsSeconds: number): boolean {
  const d = new Date(tsSeconds * 1000)
  // Convert to IST (UTC+5:30)
  const istMinutes = ((d.getUTCHours() * 60 + d.getUTCMinutes()) + 5 * 60 + 30) % (24 * 60)
  return istMinutes >= MARKET_OPEN_IST && istMinutes <= MARKET_CLOSE_IST
}

function filterMarketHours(candles: CandlestickData<Time>[]): CandlestickData<Time>[] {
  return candles.filter((c) => isMarketHours(c.time as number))
}

// ─── Convert raw candles ─────────────────────────────────────────────────────
function toChartData(candles: OhlcCandle[]): CandlestickData<Time>[] {
  return candles.map((c) => {
    const ts = Math.floor(new Date(c.bucket).getTime() / 1000)
    if (!isFinite(ts)) return null
    return { time: ts as Time, open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) }
  }).filter((x): x is CandlestickData<Time> => x != null)
}

function toLineData(candles: CandlestickData<Time>[]): LineData<Time>[] {
  return candles.map((c) => ({ time: c.time, value: c.close }))
}

// ─── Trade from Chart Modal ───────────────────────────────────────────────────
function TradeFromChartModal({
  symbol, price, onClose
}: { symbol: string; price: number; onClose: () => void }) {
  const addToast = useUIStore((s) => s.addToast)
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [qty, setQty] = useState(50)
  const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT'>('LIMIT')
  const [limitPrice, setLimitPrice] = useState(price)
  const [product, setProduct] = useState('NRML')
  const [busy, setBusy] = useState(false)

  const handleTrade = async () => {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = { symbol, side, qty, order_type: orderType, product }
      if (orderType === 'LIMIT' && limitPrice > 0) payload.price = limitPrice
      await api.placeOrder(payload)
      addToast('success', `${side} ${qty} × ${symbol} @ ${orderType === 'MARKET' ? 'MKT' : formatINR(limitPrice)}`)
      onClose()
    } catch (err) { addToast('error', err instanceof Error ? err.message : 'Order failed') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="glass rounded-2xl p-5 w-full max-w-sm space-y-4 animate-slide-up">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[13px] font-bold text-text-bright flex items-center gap-2">
              <ShoppingCart className="w-4 h-4 text-primary" />Trade from Chart
            </div>
            <div className="text-[11px] text-text-muted">{symbol} · LTP ~{formatINR(price)}</div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary w-8 h-8 flex items-center justify-center text-xl">×</button>
        </div>

        <div className="flex gap-2">
          {(['BUY', 'SELL'] as const).map((s) => (
            <button key={s} onClick={() => setSide(s)}
              className={cn('flex-1 h-9 rounded-lg text-[12px] font-bold border transition-colors',
                s === side ? (s === 'BUY' ? 'bg-profit text-bg-base border-profit' : 'bg-loss text-bg-base border-loss') : 'border-border text-text-muted hover:border-border-hover')}>
              {s}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Quantity</label>
            <input type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))}
              className="w-full h-9 px-2.5 rounded-lg bg-bg-input border border-border text-[13px] font-mono text-text-bright focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Product</label>
            <select value={product} onChange={(e) => setProduct(e.target.value)}
              className="w-full h-9 px-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-bright focus:outline-none focus:border-primary">
              {['NRML', 'MIS', 'CNC'].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Order Type</label>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value as 'MARKET' | 'LIMIT')}
              className="w-full h-9 px-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-bright focus:outline-none focus:border-primary">
              <option value="LIMIT">LIMIT</option>
              <option value="MARKET">MARKET</option>
            </select>
          </div>
          {orderType === 'LIMIT' && (
            <div>
              <label className="text-[10px] text-text-muted uppercase mb-1 block">Limit Price</label>
              <input type="number" step="0.05" value={limitPrice} onChange={(e) => setLimitPrice(Number(e.target.value))}
                className="w-full h-9 px-2.5 rounded-lg bg-bg-input border border-border text-[13px] font-mono text-text-bright focus:outline-none focus:border-primary" />
            </div>
          )}
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 h-9 rounded-lg border border-border text-[12px] font-semibold text-text-secondary hover:border-border-hover">Cancel</button>
          <button onClick={handleTrade} disabled={busy}
            className={cn('flex-1 h-9 rounded-lg text-[12px] font-bold flex items-center justify-center gap-1.5 transition-all',
              side === 'BUY' ? 'bg-profit text-bg-base hover:bg-profit/90' : 'bg-loss text-bg-base hover:bg-loss/90',
              busy && 'opacity-60 cursor-not-allowed')}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShoppingCart className="w-3.5 h-3.5" />}
            {busy ? 'Placing…' : `${side} ${symbol}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Strategy Performance Chart ───────────────────────────────────────────────
interface PerfSample { ts: number; pnl: number; underlying?: number }

function StrategyPerfChart({ strategies }: { strategies: Strategy[] }) {
  const [selectedStrategy, setSelectedStrategy] = useState<string>(strategies[0]?.name || '')
  const [samples, setSamples] = useState<PerfSample[]>([])
  const [events, setEvents] = useState<Array<{ time: number; type: string; pnl: number }>>([])
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const pnlSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const underlyingSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const addToast = useUIStore((s) => s.addToast)

  const loadPerfData = useCallback(async () => {
    if (!selectedStrategy) return
    setLoading(true)
    try {
      const [samplesData, eventsData] = await Promise.all([
        api.strategySamples(new URLSearchParams({ strategy: selectedStrategy, limit: '2000' }).toString()),
        api.strategyEvents(new URLSearchParams({ strategy: selectedStrategy }).toString()),
      ])
      type SampleRow = { timestamp?: string; ts?: number; total_pnl?: number; combined_pnl?: number; underlying_ltp?: number }
      type EventRow = { timestamp?: string; ts?: number; event_type?: string; type?: string; pnl?: number; total_pnl?: number }
      const rawSamples = Array.isArray((samplesData as { samples?: SampleRow[] }).samples) ? (samplesData as { samples: SampleRow[] }).samples : []
      const rawEvents = Array.isArray((eventsData as { events?: EventRow[] }).events) ? (eventsData as { events: EventRow[] }).events : []

      setSamples(rawSamples.map((r: SampleRow) => ({
        ts: r.timestamp ? Math.floor(new Date(r.timestamp).getTime() / 1000) : Number(r.ts ?? 0),
        pnl: Number(r.total_pnl ?? r.combined_pnl ?? 0),
        underlying: r.underlying_ltp ? Number(r.underlying_ltp) : undefined,
      })).filter((s: PerfSample) => s.ts > 0))

      setEvents(rawEvents.map((e: EventRow) => ({
        time: e.timestamp ? Math.floor(new Date(e.timestamp).getTime() / 1000) : Number(e.ts ?? 0),
        type: String(e.event_type ?? e.type ?? ''),
        pnl: Number(e.pnl ?? e.total_pnl ?? 0),
      })).filter((e: { time: number }) => e.time > 0))
    } catch (err) {
      addToast('warning', err instanceof Error ? err.message : 'Failed to load performance data')
    } finally { setLoading(false) }
  }, [selectedStrategy, addToast])

  useEffect(() => { loadPerfData() }, [loadPerfData])
  useEffect(() => {
    if (!autoRefresh) return
    const t = window.setInterval(loadPerfData, 5000)
    return () => window.clearInterval(t)
  }, [autoRefresh, loadPerfData])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#0f131f' }, textColor: '#8a95ad' },
      grid: { vertLines: { color: '#242b3d' }, horzLines: { color: '#242b3d' } },
      rightPriceScale: { borderColor: '#242b3d' },
      leftPriceScale: { visible: true, borderColor: '#242b3d' },
      timeScale: { borderColor: '#242b3d', timeVisible: true, secondsVisible: false },
    })
    chartRef.current = chart
    return () => { chart.remove(); chartRef.current = null; pnlSeriesRef.current = null; underlyingSeriesRef.current = null }
  }, [])

  useEffect(() => {
    if (!chartRef.current || !samples.length) return
    const chart = chartRef.current
    if (pnlSeriesRef.current) chart.removeSeries(pnlSeriesRef.current)
    if (underlyingSeriesRef.current) chart.removeSeries(underlyingSeriesRef.current)

    const pnlSeries = chart.addSeries(AreaSeries, {
      lineColor: '#22d3ee',
      topColor: 'rgba(34,211,238,0.3)',
      bottomColor: 'rgba(34,211,238,0.02)',
      lineWidth: 2,
      priceScaleId: 'right',
      priceLineVisible: true,
    })
    pnlSeries.setData(samples.map((s) => ({ time: s.ts as Time, value: s.pnl })))
    pnlSeriesRef.current = pnlSeries

    const underlyingSamples = samples.filter((s) => s.underlying != null)
    if (underlyingSamples.length > 0) {
      const scale = samples.reduce((mx, s) => Math.max(mx, Math.abs(s.pnl)), 1) /
        (underlyingSamples.reduce((mx, s) => Math.max(mx, s.underlying!), 1) * 0.1)
      const uSeries = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 1,
        priceScaleId: 'left',
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      })
      uSeries.setData(underlyingSamples.map((s) => ({ time: s.ts as Time, value: s.underlying! })))
      underlyingSeriesRef.current = uSeries
      void scale
    }
  }, [samples])

  const latestPnl = samples.length ? samples[samples.length - 1].pnl : 0
  const maxPnl = samples.length ? Math.max(...samples.map((s) => s.pnl)) : 0
  const minPnl = samples.length ? Math.min(...samples.map((s) => s.pnl)) : 0

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <TrendingUp className="w-5 h-5 text-primary shrink-0" />
        <span className="text-sm font-semibold text-text-bright hidden sm:block">Strategy Performance</span>

        <select value={selectedStrategy} onChange={(e) => setSelectedStrategy(e.target.value)}
          className="h-8 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary focus:outline-none focus:border-primary">
          {strategies.map((s) => <option key={s.name} value={s.name}>{s.display_name || s.name}</option>)}
        </select>

        <div className="flex-1" />

        <div className="flex items-center gap-2 text-[11px]">
          <span className={cn('font-bold tabular-nums text-base', latestPnl >= 0 ? 'text-profit' : 'text-loss')}>{formatINR(latestPnl)}</span>
          <span className="text-text-muted">P&L</span>
        </div>

        <button onClick={() => setAutoRefresh(!autoRefresh)}
          className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors',
            autoRefresh ? 'bg-primary/15 text-primary border-primary/40' : 'border-border text-text-muted')}>
          {autoRefresh ? <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />LIVE</span> : 'Paused'}
        </button>

        <button onClick={loadPerfData} className="text-text-muted hover:text-text-primary p-1">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Perf stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Current P&L</div>
          <div className={cn('text-sm font-bold tabular-nums', latestPnl >= 0 ? 'text-profit' : 'text-loss')}>{formatINR(latestPnl)}</div>
        </div>
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Peak P&L</div>
          <div className="text-sm font-bold tabular-nums text-profit">{formatINR(maxPnl)}</div>
        </div>
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Max Drawdown</div>
          <div className="text-sm font-bold tabular-nums text-loss">{formatINR(minPnl)}</div>
        </div>
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Trade Events</div>
          <div className="text-sm font-bold text-text-bright">{events.length}</div>
        </div>
      </div>

      {/* Chart */}
      <div className="glass rounded-xl overflow-hidden">
        <div ref={containerRef} className="h-[380px] relative">
          {loading && !samples.length && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
            </div>
          )}
          {!loading && !samples.length && (
            <div className="absolute inset-0 flex items-center justify-center text-text-muted text-[12px] text-center px-8">
              <div>
                <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-40" />
                No performance data yet.<br />Analytics data is collected while the strategy is running.
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Events Table */}
      {events.length > 0 && (
        <div className="glass rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border text-[11px] font-semibold text-text-bright">Trade Events</div>
          <div className="overflow-x-auto max-h-[200px] overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-bg-surface/50 sticky top-0">
                <tr>
                  <th className="px-3 py-1.5 text-left text-text-muted font-semibold">Time</th>
                  <th className="px-3 py-1.5 text-left text-text-muted font-semibold">Type</th>
                  <th className="px-3 py-1.5 text-right text-text-muted font-semibold">P&L</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(-50).reverse().map((ev, i) => (
                  <tr key={i} className="border-t border-border/30 hover:bg-bg-hover/20">
                    <td className="px-3 py-1.5 text-text-secondary font-mono">{new Date(ev.time * 1000).toLocaleTimeString()}</td>
                    <td className="px-3 py-1.5">
                      <span className={cn('badge text-[10px]',
                        ev.type === 'ENTRY' ? 'badge-buy' : ev.type === 'EXIT' ? 'badge-sell' : 'badge-neutral')}>
                        {ev.type}
                      </span>
                    </td>
                    <td className={cn('px-3 py-1.5 text-right tabular-nums font-semibold', ev.pnl >= 0 ? 'text-profit' : 'text-loss')}>
                      {formatINR(ev.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main Chart Page ─────────────────────────────────────────────────────────
export default function ChartsPage() {
  const addToast = useUIStore((s) => s.addToast)

  const [state, setState] = useState<ChartWorkspaceState>(() => {
    try { const raw = localStorage.getItem(STORE_KEY); return raw ? { ...defaultState, ...JSON.parse(raw) } : defaultState }
    catch { return defaultState }
  })

  const [activeTab, setActiveTab] = useState<PageTab>('chart')
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<SymbolInfo[]>([])
  const [symbolUniverse, setSymbolUniverse] = useState<string[]>([])
  const [levelInput, setLevelInput] = useState('')
  const [lastRefreshTime, setLastRefreshTime] = useState<Date | null>(null)
  const [tradeOpen, setTradeOpen] = useState(false)
  const [currentPrice, setCurrentPrice] = useState(0)
  const [showSettings, setShowSettings] = useState(false)

  const chartRef = useRef<IChartApi | null>(null)
  const mainSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const smaSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const emaSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const rsiSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  const bbSeriesRef = useRef<ReturnType<IChartApi['addSeries']>[] | null>(null)
  const overlaySeriesRef = useRef<Map<string, ReturnType<IChartApi['addSeries']>>>(new Map())
  const containerRef = useRef<HTMLDivElement | null>(null)
  const candleDataRef = useRef<CandlestickData<Time>[]>([])
  const themeTokens = THEMES[state.theme]
  const rangeLimit = useMemo(() => RANGES.find((r) => r.key === state.range)?.limit ?? 220, [state.range])

  useEffect(() => { localStorage.setItem(STORE_KEY, JSON.stringify(state)) }, [state])
  const upd = useCallback((patch: Partial<ChartWorkspaceState>) => setState((prev) => ({ ...prev, ...patch })), [])

  // Load strategies for perf tab
  useEffect(() => {
    api.listStrategies().then((res) => setStrategies(res.strategies || [])).catch(() => {})
  }, [])

  // Load symbol universe
  useEffect(() => {
    api.historicalSymbols().then((catalog) => {
      const syms = Array.from(new Set(catalog.index_symbols.map((s: string) => s.toUpperCase())))
      setSymbolUniverse(syms)
    }).catch(() => {})
  }, [])

  // Search suggestions
  useEffect(() => {
    if (query.length < 1) { setSuggestions([]); return }
    const t = setTimeout(async () => {
      try {
        const fromUniverse = symbolUniverse.filter((s) => s.startsWith(query.toUpperCase())).slice(0, 8).map((s) => ({ symbol: s, exchange: 'NSE', trading_symbol: s }))
        setSuggestions(fromUniverse)
        if (query.length >= 2) {
          const apiResults = await api.searchSymbols(query)
          setSuggestions([...fromUniverse, ...apiResults.filter((r) => !fromUniverse.some((f) => f.symbol === r.symbol))].slice(0, 10))
        }
      } catch { /* ignore */ }
    }, 200)
    return () => clearTimeout(t)
  }, [query, symbolUniverse])

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: themeTokens.chartBg }, textColor: themeTokens.text },
      grid: { vertLines: { color: themeTokens.grid }, horzLines: { color: themeTokens.grid } },
      rightPriceScale: { borderColor: themeTokens.grid },
      timeScale: { borderColor: themeTokens.grid, timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: themeTokens.grid }, horzLine: { color: themeTokens.grid } },
    })
    chartRef.current = chart

    // Update current price on crosshair move
    chart.subscribeCrosshairMove((param) => {
      if (param.time && mainSeriesRef.current) {
        const data = param.seriesData.get(mainSeriesRef.current)
        if (data && 'close' in (data as object)) setCurrentPrice(Number((data as CandlestickData<Time>).close))
        else if (data && 'value' in (data as object)) setCurrentPrice(Number((data as LineData<Time>).value))
      }
    })

    return () => {
      chart.remove(); chartRef.current = null
      mainSeriesRef.current = null; smaSeriesRef.current = null
      emaSeriesRef.current = null; rsiSeriesRef.current = null
      bbSeriesRef.current = null; overlaySeriesRef.current.clear()
    }
  }, [themeTokens.chartBg, themeTokens.grid, themeTokens.text])

  const clearSeries = useCallback(() => {
    if (!chartRef.current) return
    const c = chartRef.current
    ;[mainSeriesRef, smaSeriesRef, emaSeriesRef, rsiSeriesRef].forEach((r) => {
      if (r.current) { c.removeSeries(r.current); r.current = null }
    })
    if (bbSeriesRef.current) { bbSeriesRef.current.forEach((s) => c.removeSeries(s)); bbSeriesRef.current = null }
    overlaySeriesRef.current.forEach((s) => c.removeSeries(s)); overlaySeriesRef.current.clear()
  }, [])

  const loadChart = useCallback(async () => {
    if (!chartRef.current) return
    setLoading(true)
    try {
      let rawCandles = toChartData(await api.indexOhlc(state.symbol, state.interval, rangeLimit))
      if (state.marketHoursOnly && state.interval <= 15) rawCandles = filterMarketHours(rawCandles)
      candleDataRef.current = rawCandles
      if (!rawCandles.length) { clearSeries(); addToast('warning', `No data for ${state.symbol}`); return }

      clearSeries()
      const chart = chartRef.current
      const closes = rawCandles.map((c) => c.close)

      if (state.mode === 'candles') {
        const s = chart.addSeries(CandlestickSeries, { upColor: themeTokens.up, downColor: themeTokens.down, borderVisible: false, wickUpColor: themeTokens.up, wickDownColor: themeTokens.down, priceLineVisible: false })
        s.setData(rawCandles); mainSeriesRef.current = s
      } else if (state.mode === 'line') {
        const s = chart.addSeries(LineSeries, { color: '#22d3ee', lineWidth: 2, priceLineVisible: false })
        s.setData(toLineData(rawCandles)); mainSeriesRef.current = s
      } else {
        const s = chart.addSeries(AreaSeries, { lineColor: '#818cf8', topColor: 'rgba(129,140,248,0.35)', bottomColor: 'rgba(129,140,248,0.04)', lineWidth: 2, priceLineVisible: false })
        s.setData(toLineData(rawCandles)); mainSeriesRef.current = s
      }

      if (state.showSma) {
        const s = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        s.setData(buildLine(rawCandles, sma(closes, state.smaPeriod)))
        smaSeriesRef.current = s
      }
      if (state.showEma) {
        const s = chart.addSeries(LineSeries, { color: '#34d399', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        s.setData(buildLine(rawCandles, ema(closes, state.emaPeriod)))
        emaSeriesRef.current = s
      }
      if (state.showBb) {
        const bb = bollingerBands(rawCandles, state.bbPeriod, state.bbStdDev)
        const colors = ['#8b5cf6', '#8b5cf6', '#8b5cf6']
        bbSeriesRef.current = [bb.upper, bb.mid, bb.lower].map((d, i) => {
          const s = chart.addSeries(LineSeries, { color: colors[i], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, lineStyle: i === 1 ? 1 : 0 })
          s.setData(d); return s
        })
      }
      if (state.showRsi) {
        const s = chart.addSeries(LineSeries, { color: '#ec4899', lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
        s.setData(rsi(rawCandles, state.rsiPeriod))
        rsiSeriesRef.current = s
      }

      setLastRefreshTime(new Date())
      if (rawCandles.length) setCurrentPrice(rawCandles[rawCandles.length - 1].close)
    } catch (err) {
      addToast('error', err instanceof Error ? err.message : 'Failed to load chart')
    } finally { setLoading(false) }
  }, [state, rangeLimit, themeTokens, clearSeries, addToast])

  useEffect(() => { loadChart() }, [loadChart])
  useEffect(() => {
    if (!state.autoRefresh || activeTab !== 'chart') return
    const t = window.setInterval(loadChart, 3000)
    return () => window.clearInterval(t)
  }, [state.autoRefresh, loadChart, activeTab])

  const addOverlay = async (sym: string) => {
    if (!chartRef.current || state.overlays.some((o) => o.symbol === sym)) return
    const color = OVERLAY_COLORS[state.overlays.length % OVERLAY_COLORS.length]
    upd({ overlays: [...state.overlays, { symbol: sym, color }] })
    try {
      const candles = toChartData(await api.indexOhlc(sym, state.interval, rangeLimit))
      const filtered = (state.marketHoursOnly && state.interval <= 15) ? filterMarketHours(candles) : candles
      const s = chartRef.current.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true })
      s.setData(toLineData(filtered))
      overlaySeriesRef.current.set(sym, s)
    } catch { addToast('error', `Failed to load overlay: ${sym}`) }
  }

  const addLevel = () => {
    const v = parseFloat(levelInput)
    if (isFinite(v) && !state.levels.includes(v)) { upd({ levels: [...state.levels, v] }); setLevelInput('') }
  }

  const TABS_CONF: { key: PageTab; label: string; icon: typeof ChartCandlestick }[] = [
    { key: 'chart', label: 'Live Chart', icon: ChartCandlestick },
    { key: 'performance', label: 'Strategy Performance', icon: TrendingUp },
  ]

  return (
    <div className="flex flex-col gap-3 animate-fade-in h-full">
      {/* Page Tabs */}
      <div className="flex gap-0.5 bg-bg-surface rounded-xl p-1 w-fit">
        {TABS_CONF.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)}
            className={cn('flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-medium transition-colors',
              activeTab === tab.key ? 'bg-bg-elevated text-text-bright' : 'text-text-muted hover:text-text-primary')}>
            <tab.icon className="w-4 h-4" />{tab.label}
            {tab.key === 'chart' && state.autoRefresh && <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse ml-1" />}
          </button>
        ))}
      </div>

      {activeTab === 'performance' ? (
        <StrategyPerfChart strategies={strategies} />
      ) : (
        <>
          {/* Controls Bar */}
          <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
            {/* Symbol search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && query) { upd({ symbol: query.toUpperCase() }); setQuery(''); setSuggestions([]) } }}
                placeholder={state.symbol} className="h-8 pl-8 pr-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-primary focus:outline-none focus:border-primary w-[120px]" />
              {suggestions.length > 0 && (
                <div className="absolute top-full left-0 mt-1 w-[200px] glass rounded-lg border border-border overflow-hidden z-20 shadow-xl">
                  {suggestions.map((s) => (
                    <button key={s.symbol} onClick={() => { upd({ symbol: s.symbol }); setQuery(''); setSuggestions([]) }}
                      className="w-full px-3 py-1.5 text-left text-[12px] text-text-primary hover:bg-bg-hover flex justify-between gap-2">
                      <span className="font-semibold">{s.symbol}</span>
                      <span className="text-text-muted text-[10px]">{s.exchange}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Mode */}
            <div className="flex rounded-lg border border-border overflow-hidden">
              {(['candles','line','area'] as ChartMode[]).map((m) => (
                <button key={m} onClick={() => upd({ mode: m })}
                  className={cn('px-2.5 py-1.5 text-[11px] transition-colors', state.mode === m ? 'bg-primary/15 text-primary' : 'text-text-muted hover:text-text-primary')}>
                  {m === 'candles' ? <ChartCandlestick className="w-3.5 h-3.5" /> : m === 'line' ? <LineChart className="w-3.5 h-3.5" /> : <Activity className="w-3.5 h-3.5" />}
                </button>
              ))}
            </div>

            {/* Intervals */}
            <div className="flex rounded-lg border border-border overflow-hidden">
              {INTERVALS.map((i) => (
                <button key={i} onClick={() => upd({ interval: i })}
                  className={cn('px-2.5 py-1.5 text-[11px] font-medium transition-colors', state.interval === i ? 'bg-primary/15 text-primary' : 'text-text-muted hover:text-text-primary')}>
                  {i < 60 ? `${i}m` : `${i / 60}h`}
                </button>
              ))}
            </div>

            {/* Ranges */}
            <div className="flex rounded-lg border border-border overflow-hidden">
              {RANGES.map((r) => (
                <button key={r.key} onClick={() => upd({ range: r.key })}
                  className={cn('px-2.5 py-1.5 text-[11px] font-medium transition-colors', state.range === r.key ? 'bg-accent/15 text-accent' : 'text-text-muted hover:text-text-primary')}>
                  {r.label}
                </button>
              ))}
            </div>

            <div className="flex-1" />

            {/* Price display */}
            {currentPrice > 0 && <span className="text-sm font-bold text-primary tabular-nums">{formatINR(currentPrice)}</span>}

            {/* Market hours toggle */}
            <button onClick={() => upd({ marketHoursOnly: !state.marketHoursOnly })}
              className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors', state.marketHoursOnly ? 'bg-profit/15 text-profit border-profit/30' : 'border-border text-text-muted')}>
              {state.marketHoursOnly ? '🕘 Market Hrs' : '24h'}
            </button>

            {/* Trade from chart */}
            <button onClick={() => setTradeOpen(true)}
              className="px-3 py-1.5 rounded-lg bg-primary/15 text-primary border border-primary/30 text-[11px] font-semibold flex items-center gap-1.5 hover:bg-primary/25 transition-colors">
              <ShoppingCart className="w-3.5 h-3.5" />Trade
            </button>

            {/* Settings toggle */}
            <button onClick={() => setShowSettings(!showSettings)}
              className={cn('p-1.5 rounded-lg border transition-colors', showSettings ? 'bg-accent/15 border-accent/30 text-accent' : 'border-border text-text-muted hover:border-border-hover')}>
              <Settings className="w-4 h-4" />
            </button>

            {/* Auto refresh */}
            <button onClick={() => upd({ autoRefresh: !state.autoRefresh })}
              className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors', state.autoRefresh ? 'bg-primary/15 text-primary border-primary/40' : 'border-border text-text-muted')}>
              {state.autoRefresh ? <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />LIVE</span> : '⏸ Paused'}
            </button>

            <button onClick={loadChart} className="text-text-muted hover:text-text-primary p-1">
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </button>

            {lastRefreshTime && <span className="text-[10px] text-text-muted hidden md:inline">{Math.round((Date.now() - lastRefreshTime.getTime()) / 1000)}s ago</span>}
          </div>

          {/* Indicators & Overlays Settings Panel */}
          {showSettings && (
            <div className="glass rounded-xl p-4 animate-slide-up">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-[12px]">
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">Indicators</div>
                  {[
                    { key: 'showSma', label: `SMA ${state.smaPeriod}`, periodKey: 'smaPeriod' },
                    { key: 'showEma', label: `EMA ${state.emaPeriod}`, periodKey: 'emaPeriod' },
                    { key: 'showBb', label: `BB(${state.bbPeriod},${state.bbStdDev})`, periodKey: 'bbPeriod' },
                    { key: 'showRsi', label: `RSI ${state.rsiPeriod}`, periodKey: 'rsiPeriod' },
                  ].map((ind) => (
                    <label key={ind.key} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={Boolean(state[ind.key as keyof ChartWorkspaceState])}
                        onChange={(e) => upd({ [ind.key]: e.target.checked })}
                        className="w-3.5 h-3.5 rounded border-border bg-bg-input" />
                      <span className="text-text-secondary flex-1">{ind.label}</span>
                      <input type="number" min={2} max={200} value={Number(state[ind.periodKey as keyof ChartWorkspaceState])}
                        onChange={(e) => upd({ [ind.periodKey]: Number(e.target.value) })}
                        className="w-14 h-6 px-1.5 rounded bg-bg-input border border-border text-[11px] font-mono text-right focus:outline-none focus:border-primary" />
                    </label>
                  ))}
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">Theme</div>
                  {(Object.keys(THEMES) as ThemePreset[]).map((t) => (
                    <label key={t} className="flex items-center gap-2 cursor-pointer">
                      <input type="radio" name="theme" checked={state.theme === t} onChange={() => upd({ theme: t })} className="w-3.5 h-3.5" />
                      <span className="text-text-secondary capitalize">{t.replace('-', ' ')}</span>
                    </label>
                  ))}
                  <div className="mt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={state.showVolume} onChange={(e) => upd({ showVolume: e.target.checked })} className="w-3.5 h-3.5" />
                      <span className="text-text-secondary">Volume bars</span>
                    </label>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">Overlays & Levels</div>
                  <div className="flex gap-1.5">
                    <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Add overlay symbol…"
                      className="flex-1 h-7 px-2 rounded-lg bg-bg-input border border-border text-[11px] text-text-primary focus:outline-none focus:border-primary" />
                    <button onClick={() => { if (query) addOverlay(query.toUpperCase()); setQuery('') }}
                      className="h-7 w-7 rounded-lg bg-primary/15 text-primary border border-primary/30 flex items-center justify-center">
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {state.overlays.map((ov) => (
                    <div key={ov.symbol} className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: ov.color }} />
                      <span className="flex-1 text-[11px] text-text-secondary">{ov.symbol}</span>
                      <button onClick={() => upd({ overlays: state.overlays.filter((o) => o.symbol !== ov.symbol) })} className="text-text-muted hover:text-loss">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  <div className="flex gap-1.5 mt-2">
                    <input value={levelInput} onChange={(e) => setLevelInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addLevel() }}
                      placeholder="Add price level…" type="number"
                      className="flex-1 h-7 px-2 rounded-lg bg-bg-input border border-border text-[11px] text-text-primary focus:outline-none focus:border-primary" />
                    <button onClick={addLevel} className="h-7 w-7 rounded-lg bg-accent/15 text-accent border border-accent/30 flex items-center justify-center"><Plus className="w-3.5 h-3.5" /></button>
                  </div>
                  {state.levels.map((l) => (
                    <div key={l} className="flex items-center gap-2">
                      <span className="flex-1 text-[11px] font-mono text-text-secondary">{formatNum(l, 2)}</span>
                      <button onClick={() => upd({ levels: state.levels.filter((v) => v !== l) })} className="text-text-muted hover:text-loss"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Chart */}
          <div className={cn('glass rounded-xl overflow-hidden relative', themeTokens.panelClass)} style={{ minHeight: '480px', flex: 1 }}>
            {loading && (
              <div className="absolute top-2 right-2 z-10 bg-bg-elevated/80 rounded-md px-2 py-1 flex items-center gap-1.5 text-[11px] text-text-muted">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />Loading…
              </div>
            )}
            <div ref={containerRef} style={{ height: '480px', width: '100%' }} />
          </div>

          {/* Status bar */}
          <div className="flex items-center gap-4 px-1 text-[11px] text-text-muted">
            <span className="font-semibold text-text-secondary">{state.symbol}</span>
            <span>{state.interval < 60 ? `${state.interval}m` : `${state.interval / 60}h`} · {RANGES.find((r) => r.key === state.range)?.label}</span>
            {state.marketHoursOnly && <span className="text-profit">Market hours only</span>}
            {lastRefreshTime && <span>Last update: {lastRefreshTime.toLocaleTimeString()}</span>}
            <span className="flex-1" />
            {state.overlays.length > 0 && (
              <span>Overlays: {state.overlays.map((o) => <span key={o.symbol} className="font-semibold" style={{ color: o.color }}>{o.symbol} </span>)}</span>
            )}
          </div>
        </>
      )}

      {/* Trade Modal */}
      {tradeOpen && (
        <TradeFromChartModal symbol={state.symbol} price={currentPrice || 0} onClose={() => setTradeOpen(false)} />
      )}
    </div>
  )
}

function X({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}
