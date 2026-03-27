import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useDashboardStore, useAuthStore, useUIStore } from '../stores'
import type { ManagedExit, Position } from '../types'

// ── Polling Dashboard Data ──
export function useDashboardPolling(enabled = true) {
  const { setSnapshot, setLoading, incrementError, errorCount } = useDashboardStore()
  const interval = errorCount >= 3 ? 10000 : 3000

  return useQuery({
    queryKey: ['dashboard-status'],
    queryFn: async () => {
      setLoading(true)
      try {
        const data = await api.dashboardStatus()
        setSnapshot(data)
        return data
      } catch (err) {
        incrementError()
        throw err
      } finally {
        setLoading(false)
      }
    },
    refetchInterval: enabled ? interval : false,
    enabled,
    retry: 2,
  })
}

// ── Auth Check ──
export function useAuthCheck() {
  const { setAuthenticated, setChecking } = useAuthStore()
  useEffect(() => {
    api.authStatus()
      .then((r) => setAuthenticated(r.authenticated))
      .catch(() => setAuthenticated(false))
      .finally(() => setChecking(false))
  }, [setAuthenticated, setChecking])
}

// ── Derived Position Data ──
export function usePositions() {
  const snapshot = useDashboardStore(s => s.snapshot)
  const showActiveOnly = useUIStore(s => s.showActiveOnly)
  const positions = snapshot?.broker?.positions || []

  // Build LTP map (consolidated)
  const ltpMap: Record<string, number> = {}
  for (const p of positions) {
    const sym = p.tsym || p.symbol || ''
    const lp = parseFloat(String(p.lp || p.ltp || 0))
    if (lp > 0 && (!ltpMap[sym] || lp > ltpMap[sym])) ltpMap[sym] = lp
  }

  const enriched: Position[] = positions.map(p => {
    const sym = p.tsym || p.symbol || ''
    const qty = parseInt(String(p.netqty || 0))
    return {
      ...p,
      _ltp: ltpMap[sym] || parseFloat(String(p.lp || p.ltp || 0)),
      _key: sym + '|' + (p.prd || p.product || ''),
      _netPnl: parseFloat(String(p.rpnl || 0)) + parseFloat(String(p.urmtom || 0)),
      _qty: qty,
      _side: qty > 0 ? 'LONG' as const : qty < 0 ? 'SHORT' as const : 'FLAT' as const,
    }
  })

  const open = enriched.filter(p => p._qty !== 0)
  const filtered = showActiveOnly ? open : enriched

  return { all: enriched, open, filtered, summary: snapshot?.broker?.positions_summary }
}

// ── Managed Exits Map ──
export function useManagedExitsMap(): Record<string, ManagedExit> {
  const snapshot = useDashboardStore(s => s.snapshot)
  const map: Record<string, ManagedExit> = {}
  if (snapshot?.managed_exits) {
    for (const me of snapshot.managed_exits) {
      const key = me.symbol + '|' + (me.product || '')
      map[key] = me
    }
  }
  return map
}

// ── Previous Value Flash Detection ──
export function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T>(undefined)
  useEffect(() => { ref.current = value }, [value])
  return ref.current
}

// ── Strategies ──
export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: () => api.listStrategies(),
    refetchInterval: 15000,
  })
}

// ── Orderbook ──
export function useOrderbook() {
  return useQuery({
    queryKey: ['orderbook'],
    queryFn: () => api.orderbook(),
    refetchInterval: 5000,
  })
}

// ── Telegram Preferences ──
export function useTelegramPrefs() {
  return useQuery({
    queryKey: ['telegram-prefs'],
    queryFn: () => api.getTelegramPrefs(),
  })
}
