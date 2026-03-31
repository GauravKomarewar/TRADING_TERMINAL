import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertCircle, AlertTriangle, BarChart3,
  Loader2, PauseCircle, PlayCircle, RefreshCw,
  Square, Wifi, Zap, ChevronDown
} from 'lucide-react'
import { api } from '../lib/api'
import { useStrategies } from '../hooks'
import { useUIStore } from '../stores'
import { cn, formatINR, formatNum, pnlClass } from '../lib/utils'
import type { Strategy } from '../types'

// ── Types ────────────────────────────────────────────────────────────────────
interface StrategyLeg {
  symbol: string; qty?: number; side?: string
  delta: number; gamma: number; theta: number; vega: number
  realized_pnl: number; unrealized_pnl: number; total_pnl: number
  ltp?: number; avg_price?: number; product?: string
}

interface StrategyPosition {
  strategy_name: string; legs: StrategyLeg[]; leg_count: number
  combined_delta: number; combined_gamma: number; combined_theta: number; combined_vega: number
  total_unrealized_pnl: number; total_realized_pnl: number
}

interface MonitorSummary {
  total_unrealized_pnl: number; total_realized_pnl: number
  portfolio_delta: number; portfolio_gamma: number; portfolio_theta: number; portfolio_vega: number
}

type PageTab = 'strategies' | 'monitor'

// ── Sparkline ────────────────────────────────────────────────────────────────
function Sparkline({ name }: { name: string }) {
  const [pts, setPts] = useState<number[]>([])
  useEffect(() => {
    api.strategySamples(new URLSearchParams({ strategy: name, limit: '60' }).toString())
      .then((r) => {
        type S = { total_pnl?: number; combined_pnl?: number }
        const arr = Array.isArray((r as { samples?: S[] }).samples) ? (r as { samples: S[] }).samples : []
        setPts(arr.map((s) => Number(s.total_pnl ?? s.combined_pnl ?? 0)))
      }).catch(() => {})
  }, [name])
  if (pts.length < 2) return <div className="w-20 h-7 bg-bg-elevated rounded opacity-30" />
  const min = Math.min(...pts), max = Math.max(...pts)
  const range = max - min || 1
  const W = 80, H = 28
  const path = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i / (pts.length - 1)) * W},${H - ((v - min) / range) * H}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg width={W} height={H} className="overflow-visible">
      <path d={path} fill="none" stroke={last >= 0 ? '#4ade80' : '#fb7185'} strokeWidth={1.5} />
      {last >= 0
        ? <circle cx={W} cy={H - ((last - min) / range) * H} r={2.5} fill="#4ade80" />
        : <circle cx={W} cy={H - ((last - min) / range) * H} r={2.5} fill="#fb7185" />
      }
    </svg>
  )
}

// ── Status Badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status, mode }: { status: string; mode: string }) {
  if (status === 'RUNNING') {
    return mode === 'LIVE'
      ? <span className="badge badge-live flex items-center gap-1 text-[10px]"><span className="w-1.5 h-1.5 rounded-full bg-loss animate-ping" />LIVE</span>
      : <span className="badge badge-mock flex items-center gap-1 text-[10px]"><span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse" />MOCK</span>
  }
  if (status === 'PAUSED') return <span className="badge badge-warning text-[10px]">PAUSED</span>
  if (status === 'STOPPED') return <span className="badge text-[10px] border-border">STOPPED</span>
  return <span className="badge text-[10px] border-border">IDLE</span>
}

// ── Strategy Card ─────────────────────────────────────────────────────────────
function StrategyCard({ strategy, onStart, onStop, onPause, externalBusy = false }: {
  strategy: Strategy
  onStart: (name: string) => void; onStop: (name: string) => void; onPause: (name: string) => void
  externalBusy?: boolean
}) {
  const running = strategy.status === 'RUNNING'
  const isLive = strategy.mode === 'LIVE'
  const pnl = strategy.combined_pnl ?? strategy.total_pnl ?? strategy.pnl ?? 0
  const [busy, setBusy] = useState(false)
  const isBusy = busy || externalBusy

  const doAction = async (fn: () => void) => { setBusy(true); try { fn() } finally { setTimeout(() => setBusy(false), 2000) } }

  return (
    <div className={cn('glass rounded-xl overflow-hidden transition-all duration-300',
      running && isLive && 'border-loss/40 shadow-[0_0_14px_rgba(251,113,133,0.12)] animate-pulse-glow',
      running && !isLive && 'border-profit/30 shadow-[0_0_12px_rgba(74,222,128,0.08)]')}>
      {/* Running indicator strip */}
      {running && (
        <div className={cn('h-0.5 w-full', isLive ? 'bg-gradient-to-r from-transparent via-loss to-transparent' : 'bg-gradient-to-r from-transparent via-profit to-transparent')}
          style={{ animation: 'pulse 2s ease-in-out infinite' }} />
      )}
      <div className="p-4">
        {/* Top row */}
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="min-w-0">
            <div className="font-bold text-[13px] text-text-bright truncate">{strategy.display_name || strategy.name}</div>
            <div className="text-[10px] text-text-muted font-mono mt-0.5">{strategy.name}</div>
          </div>
          <StatusBadge status={strategy.status} mode={strategy.mode} />
        </div>
        {/* P&L + Sparkline */}
        <div className="flex items-end justify-between gap-3 mb-3">
          <div>
            <div className="text-[10px] text-text-muted uppercase">Day P&L</div>
            <div className={cn('text-lg font-bold tabular-nums', pnlClass(pnl))}>{formatINR(pnl)}</div>
          </div>
          <Sparkline name={strategy.name} />
        </div>
        {/* Meta */}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-text-muted mb-3">
          {strategy.legs_count != null && <span>{strategy.legs_count} legs</span>}
          {strategy.last_update && <span>Updated {new Date(strategy.last_update).toLocaleTimeString()}</span>}
          {strategy.mode && <span className={cn(strategy.mode === 'LIVE' ? 'text-loss font-semibold' : 'text-profit font-semibold')}>{strategy.mode}</span>}
        </div>
        {/* Actions */}
        <div className="flex gap-2">
          {!running && (
            <button onClick={() => doAction(() => onStart(strategy.name))} disabled={isBusy}
              className="flex-1 h-7 rounded-lg bg-profit/15 text-profit border border-profit/30 text-[11px] font-semibold flex items-center justify-center gap-1 hover:bg-profit/25">
              {isBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}Start
            </button>
          )}
          {running && (
            <>
              <button onClick={() => doAction(() => onPause(strategy.name))} disabled={isBusy}
                className="flex-1 h-7 rounded-lg bg-warning/15 text-warning border border-warning/30 text-[11px] font-semibold flex items-center justify-center gap-1 hover:bg-warning/25">
                <PauseCircle className="w-3.5 h-3.5" />Pause
              </button>
              <button onClick={() => doAction(() => onStop(strategy.name))} disabled={isBusy}
                className="flex-1 h-7 rounded-lg bg-loss/15 text-loss border border-loss/30 text-[11px] font-semibold flex items-center justify-center gap-1 hover:bg-loss/25">
                <Square className="w-3.5 h-3.5" />Stop
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Live Monitor: Portfolio Summary ──────────────────────────────────────────
function PortfolioSummary({ summary, count }: { summary: MonitorSummary; count: number }) {
  const totalPnl = summary.total_unrealized_pnl + summary.total_realized_pnl
  const cards = [
    { label: 'Total P&L', val: formatINR(totalPnl), cls: pnlClass(totalPnl), wide: true },
    { label: 'Unrealized', val: formatINR(summary.total_unrealized_pnl), cls: pnlClass(summary.total_unrealized_pnl) },
    { label: 'Realized', val: formatINR(summary.total_realized_pnl), cls: pnlClass(summary.total_realized_pnl) },
    { label: 'Strategies', val: String(count), cls: 'text-primary' },
    { label: 'Δ Delta', val: formatNum(summary.portfolio_delta, 2), cls: Math.abs(summary.portfolio_delta) > 0.5 ? 'text-warning' : 'text-text-bright' },
    { label: 'Γ Gamma', val: formatNum(summary.portfolio_gamma, 4), cls: 'text-text-bright' },
    { label: 'Θ Theta', val: formatNum(summary.portfolio_theta, 2), cls: summary.portfolio_theta < 0 ? 'text-profit' : 'text-loss' },
    { label: 'ν Vega', val: formatNum(summary.portfolio_vega, 2), cls: 'text-text-bright' },
  ]
  return (
    <div className="grid grid-cols-4 sm:grid-cols-8 gap-2 mb-4">
      {cards.map((c) => (
        <div key={c.label} className={cn('glass rounded-xl px-3 py-2.5', c.wide && 'col-span-2')}>
          <div className="text-[9px] text-text-muted uppercase tracking-wider">{c.label}</div>
          <div className={cn('text-sm font-bold tabular-nums mt-0.5', c.cls)}>{c.val}</div>
        </div>
      ))}
    </div>
  )
}

// ── Strategy Position Card (live monitor) ────────────────────────────────────
function StrategyPositionCard({ pos, strategies, isFlashing = false }: { pos: StrategyPosition; strategies: Strategy[]; isFlashing?: boolean }) {
  const strat = strategies.find((s) => s.name === pos.strategy_name)
  const totalPnl = pos.total_unrealized_pnl + pos.total_realized_pnl
  const [open, setOpen] = useState(true)

  return (
    <div className={cn('glass rounded-xl overflow-hidden transition-all duration-300',
      strat?.mode === 'LIVE' && strat?.status === 'RUNNING' && 'border-loss/30 shadow-[0_0_12px_rgba(251,113,133,0.1)]',
      isFlashing && 'ring-1 ring-primary/60')}>
      {/* Header */}
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-hover/20">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-bold text-[13px] text-text-bright">{pos.strategy_name}</span>
            {strat && <StatusBadge status={strat.status} mode={strat.mode} />}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">{pos.leg_count} legs</div>
        </div>
        <div className="text-right shrink-0">
          <div className={cn('font-bold tabular-nums text-sm', pnlClass(totalPnl))}>{formatINR(totalPnl)}</div>
          <div className="text-[10px] text-text-muted">U:{formatINR(pos.total_unrealized_pnl)} R:{formatINR(pos.total_realized_pnl)}</div>
        </div>
        <div className="text-[10px] text-text-muted space-y-0.5 shrink-0 hidden sm:block">
          <div>Δ {formatNum(pos.combined_delta, 2)}</div>
          <div>Θ {formatNum(pos.combined_theta, 2)}</div>
        </div>
        <ChevronDown className={cn('w-4 h-4 text-text-muted transition-transform shrink-0', open && 'rotate-180')} />
      </button>

      {/* Legs table */}
      {open && pos.legs.length > 0 && (
        <div className="border-t border-border overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="bg-bg-surface/50">
              <tr className="text-[9px] text-text-muted uppercase">
                <th className="px-3 py-1.5 text-left">Symbol</th>
                <th className="px-2 py-1.5 text-right">Unrealized</th>
                <th className="px-2 py-1.5 text-right">Realized</th>
                <th className="px-2 py-1.5 text-right">Total P&L</th>
                <th className="px-2 py-1.5 text-right hide-mobile">Δ</th>
                <th className="px-2 py-1.5 text-right hide-mobile">Θ</th>
                <th className="px-2 py-1.5 text-right hide-mobile">Vega</th>
              </tr>
            </thead>
            <tbody>
              {pos.legs.map((leg, i) => (
                <tr key={i} className="border-t border-border/30 hover:bg-bg-hover/20">
                  <td className="px-3 py-1.5">
                    <div className="font-semibold text-text-primary font-mono text-[10px]">{leg.symbol}</div>
                    {leg.side && <div className={cn('text-[9px]', leg.side === 'BUY' ? 'text-profit' : 'text-loss')}>{leg.side} {leg.qty}</div>}
                  </td>
                  <td className={cn('px-2 py-1.5 text-right tabular-nums font-semibold', pnlClass(leg.unrealized_pnl))}>
                    {formatINR(leg.unrealized_pnl)}
                  </td>
                  <td className={cn('px-2 py-1.5 text-right tabular-nums', pnlClass(leg.realized_pnl))}>
                    {formatINR(leg.realized_pnl)}
                  </td>
                  <td className={cn('px-2 py-1.5 text-right tabular-nums font-bold', pnlClass(leg.total_pnl))}>
                    {formatINR(leg.total_pnl)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-text-muted hide-mobile">{formatNum(leg.delta, 3)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-text-muted hide-mobile">{formatNum(leg.theta, 2)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-text-muted hide-mobile">{formatNum(leg.vega, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Live Monitor Panel ────────────────────────────────────────────────────────
function LiveMonitorPanel({ strategies }: { strategies: Strategy[] }) {
  const [data, setData] = useState<{ strategy_positions: StrategyPosition[]; summary: MonitorSummary } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const prevPnlRef = useRef<Record<string, number>>({})
  const [flashing, setFlashing] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    try {
      type RawData = { strategy_positions?: StrategyPosition[]; summary?: MonitorSummary }
      const raw = await api.strategyPositions() as RawData
      const positions = raw.strategy_positions ?? []
      const summary = raw.summary ?? { total_unrealized_pnl: 0, total_realized_pnl: 0, portfolio_delta: 0, portfolio_gamma: 0, portfolio_theta: 0, portfolio_vega: 0 }

      // Flash changed P&L
      const newFlashing = new Set<string>()
      for (const p of positions) {
        const newPnl = p.total_unrealized_pnl + p.total_realized_pnl
        const prev = prevPnlRef.current[p.strategy_name]
        if (prev != null && Math.abs(newPnl - prev) > 0.01) newFlashing.add(p.strategy_name)
        prevPnlRef.current[p.strategy_name] = newPnl
      }
      if (newFlashing.size > 0) {
        setFlashing(newFlashing)
        setTimeout(() => setFlashing(new Set()), 800)
      }

      setData({ strategy_positions: positions, summary })
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load positions')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!autoRefresh) return
    const t = window.setInterval(load, 2000)
    return () => window.clearInterval(t)
  }, [autoRefresh, load])

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="glass rounded-xl px-4 py-3 flex items-center gap-3">
        <Wifi className="w-4 h-4 text-primary" />
        <span className="text-sm font-semibold text-text-bright">Live Position Monitor</span>
        <div className="flex-1" />
        {autoRefresh && <span className="flex items-center gap-1.5 text-[11px] text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-ping" />Polling 2s</span>}
        <button onClick={() => setAutoRefresh(!autoRefresh)}
          className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors', autoRefresh ? 'bg-primary/15 text-primary border-primary/40' : 'border-border text-text-muted')}>
          {autoRefresh ? 'Pause' : 'Resume'}
        </button>
        <button onClick={load} className="text-text-muted hover:text-text-primary p-1">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {error && (
        <div className="glass rounded-xl px-4 py-3 border border-warning/30 flex items-center gap-2 text-[12px] text-warning">
          <AlertTriangle className="w-4 h-4 shrink-0" />{error}
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
      )}

      {data && (
        <>
          <PortfolioSummary summary={data.summary} count={data.strategy_positions.length} />

          {data.strategy_positions.length === 0 ? (
            <div className="glass rounded-xl p-8 text-center text-text-muted text-[12px]">
              <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-30" />
              No open positions. Positions appear as strategies trade.
            </div>
          ) : (
            <div className="space-y-2">
              {data.strategy_positions.map((pos) => (
                <StrategyPositionCard key={pos.strategy_name} pos={pos} strategies={strategies} isFlashing={flashing.has(pos.strategy_name)} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Strategies Tab ────────────────────────────────────────────────────────────
function StrategiesTab({ strategies, onRefresh }: { strategies: Strategy[]; onRefresh: () => void }) {
  const { addToast } = useUIStore()
  const [filter, setFilter] = useState<'all' | 'running' | 'live' | 'mock'>('all')
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({})

  const doStart = async (name: string) => {
    setBusyMap((p) => ({ ...p, [name]: true }))
    try { await api.startStrategy(name); addToast('success', `${name} started`); onRefresh() }
    catch (e) { addToast('error', e instanceof Error ? e.message : 'Start failed') }
    finally { setTimeout(() => setBusyMap((p) => ({ ...p, [name]: false })), 1500) }
  }
  const doStop = async (name: string) => {
    setBusyMap((p) => ({ ...p, [name]: true }))
    try { await api.stopStrategy(name); addToast('success', `${name} stopped`); onRefresh() }
    catch (e) { addToast('error', e instanceof Error ? e.message : 'Stop failed') }
    finally { setTimeout(() => setBusyMap((p) => ({ ...p, [name]: false })), 1500) }
  }
  const doPause = async (name: string) => {
    setBusyMap((p) => ({ ...p, [name]: true }))
    try { addToast('info', `Pause not yet implemented for ${name}`) }
    finally { setTimeout(() => setBusyMap((p) => ({ ...p, [name]: false })), 500) }
  }

  const filtered = strategies.filter((s) => {
    if (filter === 'running') return s.status === 'RUNNING'
    if (filter === 'live') return s.mode === 'LIVE' && s.status === 'RUNNING'
    if (filter === 'mock') return s.mode === 'MOCK' && s.status === 'RUNNING'
    return true
  })

  const running = strategies.filter((s) => s.status === 'RUNNING')
  const liveCount = running.filter((s) => s.mode === 'LIVE').length
  const totalPnl = strategies.reduce((sum, s) => sum + (s.combined_pnl ?? s.total_pnl ?? 0), 0)

  return (
    <div className="space-y-3">
      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Total</div>
          <div className="text-lg font-bold text-text-bright">{strategies.length}</div>
        </div>
        <div className={cn('glass rounded-xl px-3 py-2.5', running.length > 0 && 'border-primary/25')}>
          <div className="text-[10px] text-text-muted uppercase">Running</div>
          <div className="text-lg font-bold text-primary flex items-center gap-2">
            {running.length}
            {running.length > 0 && <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />}
          </div>
        </div>
        <div className={cn('glass rounded-xl px-3 py-2.5', liveCount > 0 && 'border-loss/25 bg-loss/5')}>
          <div className="text-[10px] text-text-muted uppercase flex items-center gap-1">
            {liveCount > 0 && <span className="w-1.5 h-1.5 rounded-full bg-loss animate-ping" />}LIVE
          </div>
          <div className="text-lg font-bold text-loss">{liveCount}</div>
        </div>
        <div className="glass rounded-xl px-3 py-2.5">
          <div className="text-[10px] text-text-muted uppercase">Day P&L</div>
          <div className={cn('text-lg font-bold tabular-nums', pnlClass(totalPnl))}>{formatINR(totalPnl)}</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex gap-1 flex-wrap">
        {(['all', 'running', 'live', 'mock'] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            className={cn('px-3 py-1.5 rounded-lg text-[11px] font-medium border transition-colors capitalize',
              filter === f ? 'bg-primary/15 text-primary border-primary/40' : 'border-border text-text-muted hover:text-text-primary')}>
            {f === 'all' ? `All (${strategies.length})` : f === 'running' ? `Running (${running.length})` : f === 'live' ? `LIVE (${liveCount})` : `Mock (${running.filter(s => s.mode==='MOCK').length})`}
          </button>
        ))}
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <div className="glass rounded-xl p-8 text-center text-text-muted text-[12px]">
          <Zap className="w-8 h-8 mx-auto mb-2 opacity-30" />No strategies match filter
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((s) => (
            <StrategyCard key={s.name} strategy={s} externalBusy={busyMap[s.name] ?? false}
              onStart={doStart} onStop={doStop} onPause={doPause} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function StrategiesPage() {
  const { data, refetch, isLoading } = useStrategies()
  const strategies: Strategy[] = data?.strategies ?? []
  const [activeTab, setActiveTab] = useState<PageTab>('strategies')
  const running = strategies.filter((s) => s.status === 'RUNNING')
  const liveCount = running.filter((s) => s.mode === 'LIVE').length

  const TABS = [
    { key: 'strategies' as PageTab, label: 'Strategies', icon: BarChart3 },
    { key: 'monitor' as PageTab, label: 'Live Monitor', icon: Activity,
      indicator: running.length > 0 },
  ]

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Page tabs */}
      <div className="flex gap-0.5 bg-bg-surface rounded-xl p-1 w-fit">
        {TABS.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)}
            className={cn('flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-medium transition-colors',
              activeTab === tab.key ? 'bg-bg-elevated text-text-bright' : 'text-text-muted hover:text-text-primary')}>
            <tab.icon className="w-4 h-4" />
            {tab.label}
            {tab.indicator && (
              <span className="flex items-center gap-1 ml-1">
                {liveCount > 0
                  ? <span className="w-1.5 h-1.5 rounded-full bg-loss animate-ping" />
                  : <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse" />}
              </span>
            )}
          </button>
        ))}
        <div className="px-2 flex items-center">
          <button onClick={() => refetch()} className="text-text-muted hover:text-text-primary p-1">
            <RefreshCw className={cn('w-3.5 h-3.5', isLoading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {activeTab === 'strategies'
        ? <StrategiesTab strategies={strategies} onRefresh={() => refetch()} />
        : <LiveMonitorPanel strategies={strategies} />}
    </div>
  )
}
