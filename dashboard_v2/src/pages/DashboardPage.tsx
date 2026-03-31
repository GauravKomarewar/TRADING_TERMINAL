import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDashboardPolling, useStrategies } from '../hooks'
import { useDashboardStore } from '../stores'
import { KPIStrip } from '../components/positions/KPIStrip'
import { PositionsTable } from '../components/positions/PositionsTable'
import { OrdersPanel } from '../components/orders/OrdersPanel'
import { RiskCard } from '../components/common/RiskCard'
import { AccountCard } from '../components/common/AccountCard'
import { TelegramCard } from '../components/common/TelegramCard'
import PlaceOrderModal from '../components/orders/PlaceOrderModal'
import { cn, formatINR, pnlClass } from '../lib/utils'
import {
  Activity,
  BarChart3, ChartCandlestick,
  Plus, ShoppingCart, Wifi, WifiOff
} from 'lucide-react'
import type { Strategy } from '../types'

// ─── Market Status Bar ───────────────────────────────────────────────────────
function MarketStatusBar() {
  const snapshot = useDashboardStore((s) => s.snapshot)
  const broker = snapshot?.system?.heartbeat?.status || 'UNKNOWN'
  const connected = broker === 'CONNECTED'

  const [marketState, setMarketState] = useState<'pre' | 'open' | 'post'>('pre')
  const [clock, setClock] = useState('')

  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const istMs = now.getTime() + (5.5 * 3600000 - now.getTimezoneOffset() * 60000)
      const ist = new Date(istMs)
      const h = ist.getUTCHours(), m = ist.getUTCMinutes()
      const tot = h * 60 + m
      setMarketState(tot < 9 * 60 + 15 ? 'pre' : tot <= 15 * 60 + 30 ? 'open' : 'post')
      setClock(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')} IST`)
    }
    tick()
    const t = window.setInterval(tick, 10000)
    return () => window.clearInterval(t)
  }, [])

  const mktColors = { pre: 'text-text-muted', open: 'text-profit', post: 'text-warning' }
  const mktLabels = { pre: 'Pre-Market', open: 'Market Open', post: 'Market Closed' }

  return (
    <div className="glass rounded-xl px-4 py-2.5 flex items-center gap-4 flex-wrap">
      {/* Market status */}
      <div className="flex items-center gap-2">
        <span className={cn('w-2 h-2 rounded-full', marketState === 'open' ? 'bg-profit animate-pulse' : 'bg-text-muted')} />
        <span className={cn('text-[12px] font-semibold', mktColors[marketState])}>{mktLabels[marketState]}</span>
        <span className="text-[11px] text-text-muted tabular-nums">{clock}</span>
      </div>

      <div className="w-px h-4 bg-border hidden sm:block" />

      {/* Broker status */}
      <div className="flex items-center gap-1.5 text-[12px]">
        {connected ? <Wifi className="w-3.5 h-3.5 text-profit" /> : <WifiOff className="w-3.5 h-3.5 text-loss" />}
        <span className={connected ? 'text-profit' : 'text-loss'}>{broker}</span>
      </div>

      <div className="flex-1" />

      <span className="text-[11px] text-text-muted hidden md:inline">
        Last update: {snapshot ? new Date().toLocaleTimeString() : '—'}
      </span>
    </div>
  )
}

// ─── Strategy Quick Strip ────────────────────────────────────────────────────
function StrategyQuickStrip({ strategies }: { strategies: Strategy[] }) {
  const navigate = useNavigate()
  if (!strategies.length) return null

  const running = strategies.filter((s) => s.status === 'RUNNING')
  const live = running.filter((s) => s.mode === 'LIVE')
  const mock = running.filter((s) => s.mode === 'MOCK')
  const totalPnl = strategies.reduce((sum, s) => sum + (s.combined_pnl ?? s.total_pnl ?? 0), 0)

  return (
    <div className="glass rounded-xl px-4 py-3">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-primary" />
          <span className="text-[12px] font-semibold text-text-bright">Active Strategies</span>
          {live.length > 0 && (
            <span className="flex items-center gap-1 badge badge-live text-[10px]">
              <span className="w-1.5 h-1.5 rounded-full bg-loss animate-ping" />LIVE {live.length}
            </span>
          )}
        </div>
        <button onClick={() => navigate('/strategies')} className="text-[11px] text-primary hover:text-primary/80 font-semibold">
          View all →
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {running.slice(0, 6).map((s) => (
          <div key={s.name}
            className={cn('flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px]',
              s.mode === 'LIVE' ? 'border-loss/30 bg-loss/5' : 'border-profit/20 bg-profit/5')}>
            <span className={cn('w-1.5 h-1.5 rounded-full', s.mode === 'LIVE' ? 'bg-loss animate-ping' : 'bg-profit')} />
            <span className="font-medium text-text-primary">{s.display_name || s.name}</span>
            <span className={cn('font-bold tabular-nums', pnlClass(s.combined_pnl ?? 0))}>
              {formatINR(s.combined_pnl ?? s.total_pnl ?? 0)}
            </span>
          </div>
        ))}
        {running.length === 0 && (
          <span className="text-[12px] text-text-muted italic">No strategies running — <button onClick={() => navigate('/strategies')} className="text-primary underline">start one</button></span>
        )}
      </div>

      <div className="flex items-center gap-6 mt-3 pt-2.5 border-t border-border/50 text-[11px]">
        <div><span className="text-text-muted">Total:</span> <span className="text-text-secondary font-semibold ml-1">{strategies.length}</span></div>
        <div><span className="text-text-muted">Running:</span> <span className="text-primary font-semibold ml-1">{running.length}</span></div>
        {live.length > 0 && <div><span className="text-text-muted">LIVE:</span> <span className="text-loss font-bold ml-1">{live.length}</span></div>}
        {mock.length > 0 && <div><span className="text-text-muted">MOCK:</span> <span className="text-profit font-semibold ml-1">{mock.length}</span></div>}
        <div className="flex-1" />
        <div><span className="text-text-muted">Day P&L:</span> <span className={cn('font-bold tabular-nums ml-1', pnlClass(totalPnl))}>{formatINR(totalPnl)}</span></div>
      </div>
    </div>
  )
}

// ─── Quick Actions ───────────────────────────────────────────────────────────
function QuickActions({ onPlaceOrder }: { onPlaceOrder: () => void }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-wrap gap-2">
      <button onClick={onPlaceOrder}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/15 text-primary border border-primary/30 text-[12px] font-semibold hover:bg-primary/25 transition-colors">
        <ShoppingCart className="w-4 h-4" />Place Order
      </button>
      <button onClick={() => navigate('/builder')}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-accent/15 text-accent border border-accent/30 text-[12px] font-semibold hover:bg-accent/25 transition-colors">
        <Plus className="w-4 h-4" />New Strategy
      </button>
      <button onClick={() => navigate('/charts')}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-elevated border border-border text-[12px] font-semibold text-text-secondary hover:border-border-hover hover:text-text-primary transition-colors">
        <ChartCandlestick className="w-4 h-4" />Live Chart
      </button>
      <button onClick={() => navigate('/option-chain')}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-elevated border border-border text-[12px] font-semibold text-text-secondary hover:border-border-hover hover:text-text-primary transition-colors">
        <BarChart3 className="w-4 h-4" />Option Chain
      </button>
    </div>
  )
}

// ─── Dashboard Page ──────────────────────────────────────────────────────────
export default function DashboardPage() {
  useDashboardPolling()
  const { data: strategiesData } = useStrategies()
  const strategies: Strategy[] = strategiesData?.strategies || []
  const [orderModalOpen, setOrderModalOpen] = useState(false)

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Market Status Bar */}
      <MarketStatusBar />

      {/* Quick Actions */}
      <QuickActions onPlaceOrder={() => setOrderModalOpen(true)} />

      {/* KPI Strip */}
      <KPIStrip />

      {/* Strategy Quick Strip */}
      <StrategyQuickStrip strategies={strategies} />

      {/* Main Grid: 2-column on desktop */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-3">
        {/* Left — Tables */}
        <div className="space-y-3 min-w-0">
          <PositionsTable />
          <OrdersPanel />
        </div>

        {/* Right — Sidebar Cards */}
        <div className="space-y-3">
          <RiskCard />
          <AccountCard />
          <TelegramCard />
        </div>
      </div>

      {orderModalOpen && <PlaceOrderModal open={orderModalOpen} onOpenChange={setOrderModalOpen} />}
    </div>
  )
}
