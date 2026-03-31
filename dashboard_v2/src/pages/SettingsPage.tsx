import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bell, Database, Grid3X3, Radio, RefreshCw, Settings } from 'lucide-react'
import { api } from '../lib/api'
import { cn } from '../lib/utils'
import { useUIStore } from '../stores'
import type { MarketDataSettings, OptionChainHealth, OptionInstrument } from '../types'

type LoadedChain = {
  key: string
  exchange: string
  symbol: string
  expiry: string
  source?: string
  uptime_seconds?: number
}

export default function SettingsPage() {
  const { addToast } = useUIStore()
  const [loading, setLoading] = useState(true)
  const [loadingAction, setLoadingAction] = useState('')

  const [availableInstruments, setAvailableInstruments] = useState<OptionInstrument[]>([])
  const [loadedChains, setLoadedChains] = useState<LoadedChain[]>([])
  const [health, setHealth] = useState<OptionChainHealth | null>(null)

  const [selectedInstrumentIdx, setSelectedInstrumentIdx] = useState('')
  const [selectedExpiry, setSelectedExpiry] = useState('')

  const [customExchange, setCustomExchange] = useState('NFO')
  const [customSymbol, setCustomSymbol] = useState('')
  const [customExpiries, setCustomExpiries] = useState<string[]>([])
  const [customExpiry, setCustomExpiry] = useState('')
  const [customStrikeGap, setCustomStrikeGap] = useState('')

  const [marketData, setMarketData] = useState<MarketDataSettings>({
    indices: [],
    ticker_symbols: [],
    sticky_symbols: [],
  })
  const [exchangeFilter, setExchangeFilter] = useState<'ALL' | 'NSE' | 'BSE' | 'MCX'>('ALL')
  const [tickerInput, setTickerInput] = useState('')
  const [stickyInput, setStickyInput] = useState('')

  const selectedInstrument = useMemo(
    () => selectedInstrumentIdx === '' ? null : availableInstruments[Number(selectedInstrumentIdx)] ?? null,
    [availableInstruments, selectedInstrumentIdx],
  )

  const filteredIndices = useMemo(() => {
    if (exchangeFilter === 'ALL') return marketData.indices
    return marketData.indices.filter((idx) => (idx.exchange || '').toUpperCase() === exchangeFilter)
  }, [marketData.indices, exchangeFilter])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    try {
      const [available, chains, healthRes, md] = await Promise.all([
        api.availableOptionInstruments(),
        api.loadedChains(),
        api.optionChainHealth().catch(() => null),
        api.marketDataSettings(),
      ])

      setAvailableInstruments(available)
      setLoadedChains(chains as LoadedChain[])
      setHealth(healthRes)
      setMarketData(md)
      setTickerInput(md.ticker_symbols.join(','))
      setStickyInput(md.sticky_symbols.join(','))
    } catch (error) {
      addToast('error', error instanceof Error ? error.message : 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (!selectedInstrument) {
      setSelectedExpiry('')
      return
    }
    if (!selectedInstrument.expiries.includes(selectedExpiry)) {
      setSelectedExpiry(selectedInstrument.expiries[0] || '')
    }
  }, [selectedInstrument, selectedExpiry])

  const parseSymbols = (raw: string) => raw
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean)

  async function withAction(action: string, fn: () => Promise<void>) {
    setLoadingAction(action)
    try {
      await fn()
    } finally {
      setLoadingAction('')
    }
  }

  const loadSelectedChain = async () => {
    if (!selectedInstrument || !selectedExpiry) return

    await withAction('load-default', async () => {
      await api.loadChain({
        exchange: selectedInstrument.exchange,
        symbol: selectedInstrument.symbol,
        expiry: selectedExpiry,
      })
      addToast('success', `Loaded ${selectedInstrument.exchange}:${selectedInstrument.symbol}:${selectedExpiry}`)
      await refreshAll()
    })
  }

  const lookupCustomExpiries = async () => {
    const sym = customSymbol.trim().toUpperCase()
    if (!sym) {
      addToast('warning', 'Enter a symbol first')
      return
    }

    await withAction('lookup-custom', async () => {
      const data = await api.searchOptionExpiries(customExchange, sym) as {
        expiries?: string[]
        strike_gap?: number
      }
      const expiries = Array.isArray(data.expiries) ? data.expiries : []
      setCustomExpiries(expiries)
      setCustomExpiry(expiries[0] || '')
      if (data.strike_gap) setCustomStrikeGap(String(data.strike_gap))
      if (!expiries.length) addToast('warning', 'No expiries found for symbol')
    })
  }

  const loadCustomChain = async () => {
    const sym = customSymbol.trim().toUpperCase()
    if (!sym || !customExpiry) return

    await withAction('load-custom', async () => {
      await api.loadChain({
        exchange: customExchange,
        symbol: sym,
        expiry: customExpiry,
        strike_gap: customStrikeGap ? Number(customStrikeGap) : undefined,
      })
      addToast('success', `Loaded ${customExchange}:${sym}:${customExpiry}`)
      await refreshAll()
    })
  }

  const unloadChain = async (key: string) => {
    await withAction(`unload-${key}`, async () => {
      await api.unloadChain({ key })
      addToast('success', `Unloaded ${key}`)
      await refreshAll()
    })
  }

  const toggleSubscription = async (symbol: string, subscribed: boolean) => {
    await withAction(`md-${symbol}`, async () => {
      if (subscribed) await api.unsubscribeMarketData(symbol)
      else await api.subscribeMarketData(symbol)
      await refreshAll()
    })
  }

  const saveTickerConfig = async () => {
    await withAction('save-ticker', async () => {
      await api.saveTickerConfig(parseSymbols(tickerInput), parseSymbols(stickyInput))
      addToast('success', 'Ticker ribbon settings saved')
      await refreshAll()
    })
  }

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <Settings className="w-5 h-5 text-primary" />
        <h1 className="text-sm font-semibold text-text-bright">Settings Control Plane</h1>
        <span className="badge badge-safe">Live</span>
        <div className="flex-1" />
        <button
          onClick={refreshAll}
          disabled={loading || !!loadingAction}
          className="text-text-muted hover:text-text-primary p-1 disabled:opacity-50"
          title="Refresh"
        >
          <RefreshCw className={cn('w-4 h-4', (loading || !!loadingAction) && 'animate-spin')} />
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr] gap-4">
        <div className="space-y-4">
          <section className="glass rounded-xl p-4 space-y-3">
            <h2 className="text-[13px] font-semibold text-text-bright flex items-center gap-2">
              <Grid3X3 className="w-4 h-4 text-primary" /> Option Chain Management
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2.5">
              <select
                value={selectedInstrumentIdx}
                onChange={(e) => setSelectedInstrumentIdx(e.target.value)}
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              >
                <option value="">Select instrument</option>
                {availableInstruments.map((item, index) => (
                  <option key={`${item.exchange}:${item.symbol}`} value={String(index)}>
                    {item.exchange}:{item.symbol}
                  </option>
                ))}
              </select>

              <select
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value)}
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
                disabled={!selectedInstrument}
              >
                <option value="">Select expiry</option>
                {(selectedInstrument?.expiries || []).map((expiry) => (
                  <option key={expiry} value={expiry}>{expiry}</option>
                ))}
              </select>

              <button
                onClick={loadSelectedChain}
                disabled={!selectedInstrument || !selectedExpiry || loadingAction === 'load-default'}
                className="h-9 px-4 rounded-lg bg-primary/15 text-primary text-[12px] font-semibold border border-primary/30 disabled:opacity-50"
              >
                {loadingAction === 'load-default' ? 'Loading...' : 'Load Chain'}
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[120px_1fr_auto_auto_auto] gap-2.5">
              <select
                value={customExchange}
                onChange={(e) => setCustomExchange(e.target.value)}
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              >
                <option value="NFO">NFO</option>
                <option value="BFO">BFO</option>
                <option value="MCX">MCX</option>
              </select>

              <input
                value={customSymbol}
                onChange={(e) => setCustomSymbol(e.target.value.toUpperCase())}
                placeholder="Custom symbol (e.g. FINNIFTY)"
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              />

              <button
                onClick={lookupCustomExpiries}
                disabled={!customSymbol.trim() || loadingAction === 'lookup-custom'}
                className="h-9 px-3 rounded-lg border border-border text-[12px] text-text-secondary disabled:opacity-50"
              >
                {loadingAction === 'lookup-custom' ? 'Lookup...' : 'Lookup'}
              </button>

              <select
                value={customExpiry}
                onChange={(e) => setCustomExpiry(e.target.value)}
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
                disabled={!customExpiries.length}
              >
                <option value="">Expiry</option>
                {customExpiries.map((expiry) => (
                  <option key={expiry} value={expiry}>{expiry}</option>
                ))}
              </select>

              <input
                value={customStrikeGap}
                onChange={(e) => setCustomStrikeGap(e.target.value.replace(/[^0-9]/g, ''))}
                placeholder="Gap"
                className="h-9 w-[84px] rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              />
            </div>

            <button
              onClick={loadCustomChain}
              disabled={!customSymbol.trim() || !customExpiry || loadingAction === 'load-custom'}
              className="h-9 px-4 rounded-lg bg-primary text-bg-base text-[12px] font-semibold disabled:opacity-50"
            >
              {loadingAction === 'load-custom' ? 'Loading Custom...' : 'Load Custom Chain'}
            </button>

            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="bg-bg-surface/60 border-b border-border">
                    <th className="text-left px-3 py-2 text-text-muted">Chain</th>
                    <th className="text-left px-3 py-2 text-text-muted">Source</th>
                    <th className="text-right px-3 py-2 text-text-muted">Uptime</th>
                    <th className="text-right px-3 py-2 text-text-muted">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {loadedChains.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-text-muted">No chains loaded</td>
                    </tr>
                  ) : loadedChains.map((chain) => (
                    <tr key={chain.key} className="border-b border-border/30 last:border-b-0">
                      <td className="px-3 py-2 font-mono text-[11px] text-text-primary">{chain.key}</td>
                      <td className="px-3 py-2 text-text-muted">{chain.source || 'unknown'}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-text-secondary">{Math.round(chain.uptime_seconds || 0)}s</td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => unloadChain(chain.key)}
                          disabled={loadingAction === `unload-${chain.key}`}
                          className="px-2.5 py-1 rounded-md text-[11px] border border-loss/40 text-loss disabled:opacity-50"
                        >
                          {loadingAction === `unload-${chain.key}` ? '...' : 'Unload'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="glass rounded-xl p-4 space-y-3">
            <h2 className="text-[13px] font-semibold text-text-bright flex items-center gap-2">
              <Radio className="w-4 h-4 text-primary" /> Market Data Subscriptions
            </h2>

            <div className="flex flex-wrap gap-1.5">
              {(['ALL', 'NSE', 'BSE', 'MCX'] as const).map((exchange) => (
                <button
                  key={exchange}
                  onClick={() => setExchangeFilter(exchange)}
                  className={cn(
                    'px-2.5 py-1 rounded-md border text-[11px] font-medium',
                    exchangeFilter === exchange
                      ? 'border-primary/40 text-primary bg-primary/10'
                      : 'border-border text-text-muted',
                  )}
                >
                  {exchange}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {filteredIndices.map((item) => (
                <button
                  key={item.symbol}
                  onClick={() => toggleSubscription(item.symbol, item.subscribed)}
                  disabled={loadingAction === `md-${item.symbol}`}
                  className={cn(
                    'text-left px-3 py-2 rounded-lg border transition-colors disabled:opacity-50',
                    item.subscribed
                      ? 'border-profit/30 bg-profit/10'
                      : 'border-border bg-bg-surface/40 hover:border-border-hover',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-[12px] font-semibold text-text-bright">{item.symbol}</div>
                      <div className="text-[10px] text-text-muted">{item.exchange || 'NA'} {item.name ? `• ${item.name}` : ''}</div>
                    </div>
                    <span className={cn('badge', item.subscribed ? 'badge-safe' : 'badge-neutral')}>
                      {item.subscribed ? 'Subscribed' : 'Idle'}
                    </span>
                  </div>
                </button>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2">
              <input
                value={stickyInput}
                onChange={(e) => setStickyInput(e.target.value.toUpperCase())}
                placeholder="Sticky symbols: INDIAVIX,NIFTY"
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              />
              <input
                value={tickerInput}
                onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                placeholder="Ticker order: NIFTY,BANKNIFTY,SENSEX"
                className="h-9 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary"
              />
              <button
                onClick={saveTickerConfig}
                disabled={loadingAction === 'save-ticker'}
                className="h-9 px-4 rounded-lg bg-primary text-bg-base text-[12px] font-semibold disabled:opacity-50"
              >
                {loadingAction === 'save-ticker' ? 'Saving...' : 'Save Ticker'}
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-4">
          <StatusCard icon={Database} title="Option Supervisor" rows={[
            { label: 'Loaded Chains', value: String(loadedChains.length) },
            { label: 'Active Chains', value: String(health?.active_chains ?? loadedChains.length) },
            { label: 'Stale Chains', value: String(health?.stale_chains ?? 0), danger: (health?.stale_chains ?? 0) > 0 },
            { label: 'Max Snapshot Age', value: `${Math.round(Number(health?.max_snapshot_age || 0))}s` },
          ]} />

          <StatusCard icon={Radio} title="Market Data" rows={[
            { label: 'Total Indices', value: String(marketData.indices.length) },
            { label: 'Subscribed', value: String(marketData.indices.filter((item) => item.subscribed).length) },
            { label: 'Ticker Symbols', value: String(marketData.ticker_symbols.length) },
            { label: 'Sticky Symbols', value: String(marketData.sticky_symbols.length) },
          ]} />

          <div className="glass rounded-xl p-4">
            <h2 className="text-[13px] font-semibold text-text-bright flex items-center gap-2">
              <Bell className="w-4 h-4 text-primary" /> Notification Scope
            </h2>
            <p className="text-[12px] text-text-muted mt-2">
              Telegram quick controls stay on the dashboard sidebar card for low-latency access during market hours.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusCard({
  icon: Icon,
  title,
  rows,
}: {
  icon: typeof Settings
  title: string
  rows: Array<{ label: string; value: string; danger?: boolean }>
}) {
  return (
    <div className="glass rounded-xl p-4">
      <h2 className="text-[13px] font-semibold text-text-bright flex items-center gap-2">
        <Icon className="w-4 h-4 text-primary" /> {title}
      </h2>
      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between text-[12px]">
            <span className="text-text-muted">{row.label}</span>
            <span className={cn('font-semibold tabular-nums', row.danger ? 'text-loss' : 'text-text-primary')}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
