import { useCallback, useEffect, useMemo, useState } from 'react'
import { Grid3X3, RefreshCw, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import { cn, formatINR, formatNum } from '../lib/utils'
import type { LoadedOptionChain, OptionChainSnapshot } from '../types'

export default function OptionChainPage() {
  const [chains, setChains] = useState<LoadedOptionChain[]>([])
  const [selectedKey, setSelectedKey] = useState('')
  const [snapshot, setSnapshot] = useState<OptionChainSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const selectedChain = useMemo(
    () => chains.find((chain) => chain.key === selectedKey) || chains[0],
    [chains, selectedKey],
  )

  const loadChains = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const nextChains = await api.loadedChains()
      setChains(nextChains)
      if (nextChains.length) {
        setSelectedKey((current) => current || nextChains[0].key)
      }
      if (!nextChains.length) {
        setSnapshot(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load option chains')
      setSnapshot(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadSnapshot = useCallback(async (chain: LoadedOptionChain) => {
    setLoading(true)
    setError('')

    try {
      setSnapshot(await api.optionChain(chain))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load option chain')
      setSnapshot(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadChains()
  }, [loadChains])

  useEffect(() => {
    if (selectedChain) {
      loadSnapshot(selectedChain)
    }
  }, [loadSnapshot, selectedChain])

  const spotPrice = snapshot?.meta.spot_ltp ?? snapshot?.meta.fut_ltp ?? snapshot?.meta.atm ?? 0
  const strikes = snapshot?.strikes || []
  const atmIndex = strikes.findIndex((strike) => strike.strike >= spotPrice)
  const totalCeOi = strikes.reduce((sum, strike) => sum + (strike.ce_oi || 0), 0)
  const totalPeOi = strikes.reduce((sum, strike) => sum + (strike.pe_oi || 0), 0)
  const pcr = totalCeOi > 0 ? totalPeOi / totalCeOi : 0
  const snapshotAge = snapshot?.meta.snapshot_age ?? 0

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <Grid3X3 className="w-5 h-5 text-primary" />
        <h1 className="text-sm font-semibold text-text-bright">Option Chain</h1>

        <select
          value={selectedChain?.key || ''}
          onChange={(e) => setSelectedKey(e.target.value)}
          className="h-8 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary focus:outline-none focus:border-primary"
        >
          {chains.map((chain) => (
            <option key={chain.key} value={chain.key}>
              {chain.exchange}:{chain.symbol}:{chain.expiry}
            </option>
          ))}
        </select>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-text-muted">Spot:</span>
          <span className="text-sm font-bold text-primary tabular-nums">
            {spotPrice ? formatINR(spotPrice) : '—'}
          </span>
        </div>

        <button onClick={() => selectedChain && loadSnapshot(selectedChain)} className="text-text-muted hover:text-text-primary p-1">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {error ? (
        <div className="glass rounded-xl px-4 py-3 text-[12px] text-loss border border-loss/20">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <MiniStat label="Total CE OI" value={formatNum(totalCeOi, 0)} color="text-profit" />
        <MiniStat label="Total PE OI" value={formatNum(totalPeOi, 0)} color="text-loss" />
        <MiniStat label="PCR" value={formatNum(pcr)} color="text-warning" />
        <MiniStat
          label="Snapshot Age"
          value={snapshot ? `${formatNum(snapshotAge, 1)}s` : '—'}
          color={snapshot?.meta.is_stale ? 'text-loss' : 'text-primary'}
        />
      </div>

      <div className="glass rounded-xl overflow-hidden relative">
        {loading ? (
          <div className="absolute inset-0 z-10 bg-bg-base/50 backdrop-blur-[1px] flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-primary" />
          </div>
        ) : null}

        {strikes.length === 0 ? (
          <div className="px-4 py-12 text-center text-[12px] text-text-muted">
            No option-chain rows available.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th colSpan={5} className="text-center py-2 text-profit font-bold text-[12px] bg-profit/5 border-r border-border">
                    CALLS
                  </th>
                  <th className="text-center py-2 text-primary font-bold bg-primary/5">STRIKE</th>
                  <th colSpan={5} className="text-center py-2 text-loss font-bold text-[12px] bg-loss/5 border-l border-border">
                    PUTS
                  </th>
                </tr>
                <tr className="border-b border-border bg-bg-surface/50">
                  <th className="text-right px-2 py-1.5 font-semibold text-text-muted">OI</th>
                  <th className="text-right px-2 py-1.5 font-semibold text-text-muted hide-mobile">Chg%</th>
                  <th className="text-right px-2 py-1.5 font-semibold text-text-muted hide-mobile">Vol</th>
                  <th className="text-right px-2 py-1.5 font-semibold text-text-muted hide-mobile">IV</th>
                  <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-r border-border">LTP</th>
                  <th className="text-center px-2 py-1.5 font-bold text-primary">Strike</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-text-muted border-l border-border">LTP</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-text-muted hide-mobile">IV</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-text-muted hide-mobile">Vol</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-text-muted hide-mobile">Chg%</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-text-muted">OI</th>
                </tr>
              </thead>
              <tbody>
                {strikes.map((strike, index) => {
                  const isATM = index === atmIndex
                  const isITMCall = strike.strike < spotPrice
                  const isITMPut = strike.strike > spotPrice

                  return (
                    <tr
                      key={strike.strike}
                      className={cn(
                        'border-b border-border/30 hover:bg-bg-hover/30 transition-colors',
                        isATM && 'bg-primary/5 border-primary/20',
                      )}
                    >
                      <td className={cn('px-2 py-2 text-right tabular-nums', isITMCall && 'bg-profit/5')}>
                        {formatNum(strike.ce_oi, 0)}
                      </td>
                      <td className={cn(
                        'px-2 py-2 text-right tabular-nums hide-mobile',
                        isITMCall && 'bg-profit/5',
                        (strike.ce_change || 0) >= 0 ? 'text-profit' : 'text-loss',
                      )}>
                        {strike.ce_change != null ? formatNum(strike.ce_change) : '—'}
                      </td>
                      <td className={cn('px-2 py-2 text-right tabular-nums text-text-muted hide-mobile', isITMCall && 'bg-profit/5')}>
                        {formatNum(strike.ce_volume, 0)}
                      </td>
                      <td className={cn('px-2 py-2 text-right tabular-nums text-text-muted hide-mobile', isITMCall && 'bg-profit/5')}>
                        {strike.ce_iv != null ? `${formatNum(strike.ce_iv)}%` : '—'}
                      </td>
                      <td className={cn('px-2 py-2 text-right tabular-nums font-semibold border-r border-border', isITMCall && 'bg-profit/5 text-profit')}>
                        {formatINR(strike.ce_ltp)}
                      </td>

                      <td className={cn(
                        'px-2 py-2 text-center font-bold tabular-nums',
                        isATM ? 'text-primary bg-primary/10' : 'text-text-bright',
                      )}>
                        {strike.strike.toLocaleString('en-IN')}
                        {isATM ? <span className="ml-1 text-[9px] text-primary">ATM</span> : null}
                      </td>

                      <td className={cn('px-2 py-2 text-left tabular-nums font-semibold border-l border-border', isITMPut && 'bg-loss/5 text-loss')}>
                        {formatINR(strike.pe_ltp)}
                      </td>
                      <td className={cn('px-2 py-2 text-left tabular-nums text-text-muted hide-mobile', isITMPut && 'bg-loss/5')}>
                        {strike.pe_iv != null ? `${formatNum(strike.pe_iv)}%` : '—'}
                      </td>
                      <td className={cn('px-2 py-2 text-left tabular-nums text-text-muted hide-mobile', isITMPut && 'bg-loss/5')}>
                        {formatNum(strike.pe_volume, 0)}
                      </td>
                      <td className={cn(
                        'px-2 py-2 text-left tabular-nums hide-mobile',
                        isITMPut && 'bg-loss/5',
                        (strike.pe_change || 0) >= 0 ? 'text-profit' : 'text-loss',
                      )}>
                        {strike.pe_change != null ? formatNum(strike.pe_change) : '—'}
                      </td>
                      <td className={cn('px-2 py-2 text-left tabular-nums', isITMPut && 'bg-loss/5')}>
                        {formatNum(strike.pe_oi, 0)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="glass rounded-xl px-3 py-2.5">
      <div className="text-[10px] text-text-muted uppercase tracking-wider">{label}</div>
      <div className={cn('text-base font-bold tabular-nums', color)}>{value}</div>
    </div>
  )
}
