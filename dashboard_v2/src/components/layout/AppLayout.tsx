import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useUIStore, useDashboardStore } from '../../stores'
import { timeAgo } from '../../lib/utils'
import { api } from '../../lib/api'
import {
  LayoutDashboard, BarChart3, BookOpen, Grid3X3,
  Settings, Activity, Menu, X, LogOut, Zap, Cpu, ShoppingCart, Stethoscope
} from 'lucide-react'
import { ToastContainer } from '../common/Toast'
import PlaceOrderModal from '../orders/PlaceOrderModal'

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', exact: true },
  { to: '/strategies', icon: Zap, label: 'Strategies' },
  { to: '/strategy-builder', icon: Cpu, label: 'Strategy Builder', badge: 'Read only' },
  { to: '/orderbook', icon: BookOpen, label: 'Orderbook' },
  { to: '/charts', icon: BarChart3, label: 'Charts' },
  { to: '/option-chain', icon: Grid3X3, label: 'Option Chain' },
  { to: '/diagnostics', icon: Stethoscope, label: 'Diagnostics' },
  { to: '/settings', icon: Settings, label: 'Settings', badge: 'Preview' },
]

export default function AppLayout() {
  const { sidebarOpen, setSidebarOpen } = useUIStore()
  const lastUpdate = useDashboardStore(s => s.lastUpdate)
  const snapshot = useDashboardStore(s => s.snapshot)
  const location = useLocation()
  const navigate = useNavigate()
  const [orderOpen, setOrderOpen] = useState(false)

  const brokerStatus = snapshot?.system?.heartbeat?.status || 'UNKNOWN'
  const riskStatus = snapshot?.system?.risk?.status || 'SAFE'

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className={`
        fixed inset-y-0 left-0 z-50 w-[220px] bg-bg-surface border-r border-border
        flex flex-col transition-transform duration-200 ease-out
        lg:static lg:translate-x-0
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        {/* Brand */}
        <div className="flex items-center gap-2 px-4 h-14 border-b border-border shrink-0">
          <Activity className="w-5 h-5 text-primary" />
          <span className="text-sm font-bold text-text-bright tracking-wide">SHOONYA <span className="text-primary">OMS</span></span>
          <button onClick={() => setSidebarOpen(false)} className="ml-auto lg:hidden text-text-muted hover:text-text-primary">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.exact}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) => `
                flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] font-medium
                transition-colors duration-150
                ${isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}
              `}
            >
              <item.icon className="w-[18px] h-[18px] shrink-0" />
              <span className="flex-1">{item.label}</span>
              {item.badge ? (
                <span className="text-[9px] uppercase tracking-wider text-text-muted">
                  {item.badge}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        {/* Place Order Button */}
        <div className="px-3 pb-2">
          <button
            onClick={() => { setOrderOpen(true); setSidebarOpen(false) }}
            className="w-full py-2.5 rounded-xl bg-primary text-bg-base text-[12px] font-bold flex items-center justify-center gap-2 hover:bg-primary/90 transition-colors shadow-[0_0_15px_rgba(34,211,238,.2)]"
          >
            <ShoppingCart className="w-4 h-4" /> Place Order
          </button>
        </div>

        {/* Status Footer */}
        <div className="px-3 py-3 border-t border-border space-y-1.5 shrink-0">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-muted">Broker</span>
            <span className={`badge ${brokerStatus === 'CONNECTED' ? 'badge-safe' : 'badge-neutral'}`}>
              {brokerStatus}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-muted">Risk</span>
            <span className={`badge ${riskStatus === 'SAFE' ? 'badge-safe' : riskStatus === 'WARNING' ? 'badge-warning' : 'badge-danger'}`}>
              {riskStatus}
            </span>
          </div>
          <div className="text-[10px] text-text-muted text-center mt-1">
            Updated {timeAgo(lastUpdate || null)}
          </div>
        </div>
      </aside>

      {/* Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Bar */}
        <header className="flex items-center gap-3 px-4 h-12 bg-bg-surface border-b border-border shrink-0">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden text-text-muted hover:text-text-primary">
            <Menu className="w-5 h-5" />
          </button>

          {/* Page Title */}
          <h1 className="text-sm font-semibold text-text-bright capitalize">
            {location.pathname.split('/').filter(Boolean).pop() || 'Dashboard'}
          </h1>

          <div className="flex-1" />

          {/* Live Dot */}
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
            <span className="text-[11px] text-text-muted hide-mobile">LIVE</span>
          </div>

          {/* Logout */}
          <button
            onClick={async () => {
              try {
                await api.logout()
              } finally {
                navigate('/login', { replace: true })
              }
            }}
            className="text-text-muted hover:text-loss transition-colors p-1.5"
            title="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-3 md:p-4 lg:p-5">
          <Outlet />
        </main>
      </div>

      <ToastContainer />
      <PlaceOrderModal open={orderOpen} onOpenChange={setOrderOpen} />
    </div>
  )
}
