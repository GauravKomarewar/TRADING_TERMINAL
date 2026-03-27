import { useState, useCallback } from 'react'
import { useStrategies } from '../hooks'
import { useUIStore } from '../stores'
import { api } from '../lib/api'
import { formatINR, pnlClass, cn } from '../lib/utils'
import {
  Play, Square, Search, Zap,
  TrendingUp, Activity, Clock
} from 'lucide-react'

type FilterType = 'all' | 'running' | 'stopped' | 'paused' | 'live' | 'mock'

export default function StrategiesPage() {
  const { data, isLoading } = useStrategies()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterType>('all')
  const strategies = data?.strategies || []

  const filtered = strategies.filter(s => {
    if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false
    if (filter === 'running') return s.status === 'RUNNING'
    if (filter === 'stopped') return s.status === 'STOPPED' || s.status === 'IDLE'
    if (filter === 'paused') return s.status === 'PAUSED'
    if (filter === 'live') return s.mode === 'LIVE'
    if (filter === 'mock') return s.mode === 'MOCK'
    return true
  })

  const runningCount = strategies.filter(s => s.status === 'RUNNING').length
  const liveCount = strategies.filter(s => s.mode === 'LIVE').length
  const totalPnl = strategies.reduce((acc, s) => acc + (s.total_pnl || s.cumulative_daily_pnl || s.pnl || 0), 0)

  const filters: { key: FilterType; label: string; count?: number }[] = [
    { key: 'all', label: 'All', count: strategies.length },
    { key: 'running', label: 'Running', count: runningCount },
    { key: 'live', label: 'LIVE', count: liveCount },
    { key: 'mock', label: 'MOCK', count: strategies.length - liveCount },
    { key: 'stopped', label: 'Stopped' },
    { key: 'paused', label: 'Paused' },
  ]

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Quick Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <StatCard icon={Zap} label="Total" value={String(strategies.length)} color="text-primary" />
        <StatCard icon={Activity} label="Running" value={String(runningCount)} color="text-profit" />
        <StatCard icon={TrendingUp} label="Day's P&L" value={formatINR(totalPnl)} color={pnlClass(totalPnl)} />
        <StatCard icon={Clock} label="LIVE" value={String(liveCount)} color="text-loss" />
      </div>

      {/* Search & Filters */}
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search strategies..."
            className="w-full h-8 pl-8 pr-3 rounded-lg bg-bg-input border border-border text-[12px]
              text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {filters.map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                'px-2.5 py-1 rounded-md text-[11px] font-medium border transition-colors',
                filter === f.key
                  ? 'bg-primary/10 text-primary border-primary/30'
                  : 'text-text-muted border-border hover:border-border-hover'
              )}
            >
              {f.label}
              {f.count != null && <span className="ml-1 opacity-60">{f.count}</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Strategy Cards */}
      {isLoading ? (
        <div className="text-center py-12 text-text-muted">Loading strategies...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-text-muted">No strategies found</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map(s => (
            <StrategyCard key={s.name} strategy={s} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Stat Card ──
function StatCard({ icon: Icon, label, value, color }: { icon: typeof Zap; label: string; value: string; color: string }) {
  return (
    <div className="glass rounded-xl px-4 py-3 flex items-center gap-3">
      <Icon className={cn('w-5 h-5', color)} />
      <div>
        <div className="text-[10px] text-text-muted uppercase tracking-wider">{label}</div>
        <div className={cn('text-base font-bold tabular-nums', color)}>{value}</div>
      </div>
    </div>
  )
}

// ── Strategy Card ──
function StrategyCard({ strategy: s }: { strategy: import('../types').Strategy }) {
  const { addToast } = useUIStore()
  const [loading, setLoading] = useState<string | null>(null)

  const isLive = s.mode === 'LIVE'
  const isRunning = s.status === 'RUNNING'
  const pnl = s.total_pnl || s.cumulative_daily_pnl || s.combined_pnl || s.pnl || 0
  const legs = s.legs_count || s.legs || 0
  const displayName = s.display_name || s.name

  const action = useCallback(async (act: string) => {
    setLoading(act)
    try {
      if (act === 'start') await api.startStrategy(s.name)
      else if (act === 'stop') await api.stopStrategy(s.name)
      addToast('success', `${act} → ${s.name}`)
    } catch (e: unknown) {
      addToast('error', `${act} failed: ${e instanceof Error ? e.message : 'Unknown'}`)
    } finally {
      setLoading(null)
    }
  }, [s.name, addToast])

  return (
    <div className={cn(
      'glass rounded-xl overflow-hidden transition-all hover:border-border-hover',
      isLive && isRunning && 'border-loss/30 shadow-[0_0_20px_rgba(251,113,133,0.05)]',
      !isLive && isRunning && 'border-primary/30',
    )}>
      {/* Header */}
      <div className={cn(
        'px-4 py-3 flex items-center justify-between border-b',
        isLive ? 'border-loss/20 bg-loss/5' : 'border-border bg-bg-surface/30'
      )}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={cn('badge text-[10px]', isLive ? 'badge-live' : 'badge-mock')}>
              {s.mode}
            </span>
            <span className={cn('badge text-[10px]',
              isRunning ? 'badge-safe' : s.status === 'PAUSED' ? 'badge-warning' : 'badge-neutral'
            )}>
              {s.status}
            </span>
          </div>
          <h3 className="text-[13px] font-bold text-text-bright mt-1 truncate">{displayName}</h3>
          {displayName !== s.name ? (
            <div className="text-[10px] text-text-muted font-mono truncate">{s.name}</div>
          ) : null}
        </div>
        <div className={cn('text-right tabular-nums font-bold text-sm', pnlClass(pnl))}>
          {formatINR(pnl)}
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex justify-between text-[11px]">
          <span className="text-text-muted">Legs</span>
          <span className="text-text-secondary">{legs}</span>
        </div>
        {s.entry_time && (
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Entry</span>
            <span className="text-text-secondary">{s.entry_time}</span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="px-4 py-2.5 border-t border-border flex items-center gap-1.5">
        {!isRunning && (
          <ActionBtn icon={Play} label="Start" color="text-profit" onClick={() => action('start')} loading={loading === 'start'} />
        )}
        {isRunning && (
          <ActionBtn icon={Square} label="Stop" color="text-loss" onClick={() => action('stop')} loading={loading === 'stop'} />
        )}
      </div>
    </div>
  )
}

function ActionBtn({ icon: Icon, label, color, onClick, loading }: {
  icon: typeof Play; label: string; color: string; onClick: () => void; loading: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={cn(
        'flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[10px] font-semibold',
        'bg-bg-elevated border border-border hover:border-border-hover transition-all',
        'disabled:opacity-50', color
      )}
    >
      <Icon className="w-3 h-3" />
      {loading ? '...' : label}
    </button>
  )
}
