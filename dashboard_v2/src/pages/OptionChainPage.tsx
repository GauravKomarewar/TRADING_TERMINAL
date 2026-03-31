import { useCallback, useEffect, useRef, useState, useMemo } from 'react'
import {
  Activity, AlertTriangle, BarChart2, ChevronDown, ChevronRight,
  Loader2, RefreshCw, ShoppingCart, Target, TrendingDown, TrendingUp,
  Zap, X, Trash2, Play
} from 'lucide-react'
import { api } from '../lib/api'
import { useUIStore } from '../stores'
import { cn, formatINR, formatNum } from '../lib/utils'
import type { LoadedOptionChain, OptionChainSnapshot, OptionChainStrike } from '../types'

// ── Types ────────────────────────────────────────────────────────────────────
interface OIPrev { [strike: number]: { ce: number; pe: number } }

interface BasketLeg {
  id: string; label: string; symbol: string; exchange: string
  side: 'BUY' | 'SELL'; qty: number; order_type: 'MARKET' | 'LIMIT'; price: number
}

interface AnalysisData {
  resistance: { strike: number; oi: number } | null
  support: { strike: number; oi: number } | null
  maxPain: number; atmStraddle: number; impliedMove: number; impliedPct: number
  pcr: number; bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL'; biasLabel: string
  buyerZones: Array<{ strike: number; side: 'CE' | 'PE'; vol: number }>
  sellerZones: Array<{ strike: number; side: 'CE' | 'PE'; oi: number }>
  summary: string; shortSummary: string
}

// ── Analysis Engine ──────────────────────────────────────────────────────────
function calcMaxPain(strikes: OptionChainStrike[]): number {
  if (!strikes.length) return 0
  let best = 0, bestStrike = strikes[0].strike
  for (const atPrice of strikes) {
    let totalPain = 0
    for (const s of strikes) {
      const ceOI = s.ce_oi ?? 0, peOI = s.pe_oi ?? 0
      if (atPrice.strike < s.strike) totalPain += ceOI * (s.strike - atPrice.strike)
      if (atPrice.strike > s.strike) totalPain += peOI * (atPrice.strike - s.strike)
    }
    if (best === 0 || totalPain < best) { best = totalPain; bestStrike = atPrice.strike }
  }
  return bestStrike
}

function calcAnalysis(strikes: OptionChainStrike[], spot: number): AnalysisData {
  if (!strikes.length) return {
    resistance: null, support: null, maxPain: 0, atmStraddle: 0,
    impliedMove: 0, impliedPct: 0, pcr: 1, bias: 'NEUTRAL', biasLabel: 'Neutral',
    buyerZones: [], sellerZones: [], summary: '', shortSummary: ''
  }

  const totalCeOI = strikes.reduce((s, r) => s + (r.ce_oi ?? 0), 0)
  const totalPeOI = strikes.reduce((s, r) => s + (r.pe_oi ?? 0), 0)
  const pcr = totalCeOI > 0 ? totalPeOI / totalCeOI : 1

  // Support = max PE OI strike (put writers defending this floor), Resistance = max CE OI
  const maxCeStrike = strikes.reduce((mx, s) => (s.ce_oi ?? 0) > (mx.ce_oi ?? 0) ? s : mx, strikes[0])
  const maxPeStrike = strikes.reduce((mx, s) => (s.pe_oi ?? 0) > (mx.pe_oi ?? 0) ? s : mx, strikes[0])
  const resistance = { strike: maxCeStrike.strike, oi: maxCeStrike.ce_oi ?? 0 }
  const support = { strike: maxPeStrike.strike, oi: maxPeStrike.pe_oi ?? 0 }

  // ATM straddle
  const atmStrike = strikes.find((s) => s.strike >= spot) ?? strikes[Math.floor(strikes.length / 2)]
  const atmStraddle = (atmStrike?.ce_ltp ?? 0) + (atmStrike?.pe_ltp ?? 0)
  const impliedMove = atmStraddle
  const impliedPct = spot > 0 ? (impliedMove / spot) * 100 : 0

  // Max pain
  const maxPain = calcMaxPain(strikes)

  // Bias
  let bias: AnalysisData['bias'] = 'NEUTRAL'
  let biasLabel = 'Neutral'
  if (pcr > 1.2) { bias = 'BULLISH'; biasLabel = `Bullish (PCR ${formatNum(pcr, 2)})` }
  else if (pcr < 0.85) { bias = 'BEARISH'; biasLabel = `Bearish (PCR ${formatNum(pcr, 2)})` }
  else biasLabel = `Neutral (PCR ${formatNum(pcr, 2)})`

  // Proximity override: if spot close to resistance → bearish pressure
  if (spot > 0 && resistance.strike > 0) {
    const distToRes = (resistance.strike - spot) / spot
    const distToSup = (spot - support.strike) / spot
    if (distToRes < 0.005 && bias !== 'BEARISH') { bias = 'NEUTRAL'; biasLabel += ` (near resistance)` }
    if (distToSup < 0.005 && bias !== 'BULLISH') { bias = 'NEUTRAL'; biasLabel += ` (near support)` }
  }

  // Buyer zones: high volume strikes near ATM  
  const atmIdx = strikes.findIndex((s) => s.strike >= spot)
  const nearStrikes = strikes.slice(Math.max(0, atmIdx - 4), atmIdx + 5)
  const buyerZones = nearStrikes
    .flatMap((s) => [
      { strike: s.strike, side: 'CE' as const, vol: s.ce_volume ?? 0 },
      { strike: s.strike, side: 'PE' as const, vol: s.pe_volume ?? 0 },
    ])
    .filter((z) => z.vol > 0)
    .sort((a, b) => b.vol - a.vol)
    .slice(0, 4)

  // Seller zones: high OI far from ATM (gamma risk, theta decay plays)
  const sellerZones = strikes
    .flatMap((s) => [
      { strike: s.strike, side: 'CE' as const, oi: s.ce_oi ?? 0 },
      { strike: s.strike, side: 'PE' as const, oi: s.pe_oi ?? 0 },
    ])
    .filter((z) => z.oi > 0)
    .sort((a, b) => b.oi - a.oi)
    .slice(0, 4)

  const range = `${(spot - impliedMove).toLocaleString('en-IN', { maximumFractionDigits: 0 })}–${(spot + impliedMove).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  const summary = [
    `${bias} market bias (PCR: ${formatNum(pcr, 2)}).`,
    support.strike > 0 ? `Key support at ${support.strike.toLocaleString('en-IN')} (${((support.oi)/1e5).toFixed(1)}L PE OI).` : '',
    resistance.strike > 0 ? `Key resistance at ${resistance.strike.toLocaleString('en-IN')} (${((resistance.oi)/1e5).toFixed(1)}L CE OI).` : '',
    `ATM straddle ₹${formatNum(atmStraddle, 0)} implies ±${formatNum(impliedMove, 0)} pts (${formatNum(impliedPct, 1)}%) move.`,
    `Expected range: ${range}. Max pain at ${maxPain.toLocaleString('en-IN')}.`,
  ].filter(Boolean).join(' ')
  const shortSummary = `${bias === 'BULLISH' ? '🟢' : bias === 'BEARISH' ? '🔴' : '🟡'} ${biasLabel} · Range ${range} · MaxPain ${maxPain.toLocaleString('en-IN')}`

  return { resistance, support, maxPain, atmStraddle, impliedMove, impliedPct, pcr, bias, biasLabel, buyerZones, sellerZones, summary, shortSummary }
}

// ── OI buildup indicator ───────────────────────────────────────────────────
function OIChg({ val, prevVal }: { val: number; prevVal: number }) {
  if (!prevVal || prevVal === 0) return <span className="text-[10px] text-text-muted">—</span>
  const pct = ((val - prevVal) / prevVal) * 100
  if (Math.abs(pct) < 0.5) return <span className="text-[10px] text-text-muted">—</span>
  return (
    <span className={cn('text-[10px] font-semibold tabular-nums', pct > 0 ? 'text-profit' : 'text-loss')}>
      {pct > 0 ? '+' : ''}{formatNum(pct, 1)}%
    </span>
  )
}

function OIBar({ value, max, side }: { value: number; max: number; side: 'ce' | 'pe' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className={cn('h-3 rounded-sm overflow-hidden bg-bg-elevated w-full min-w-[32px]')}>
      <div className={cn('h-full rounded-sm transition-all', side === 'ce' ? 'bg-loss/60' : 'bg-profit/60')}
        style={{ width: `${pct}%`, float: side === 'ce' ? 'right' : 'left' }} />
    </div>
  )
}

function DeltaTag({ val }: { val?: number }) {
  if (val == null) return null
  return (
    <span className={cn('text-[9px] font-bold px-1 py-0.5 rounded border tabular-nums shrink-0',
      Math.abs(val) > 0.5 ? 'border-warning/40 text-warning bg-warning/8' : 'border-border text-text-muted')}>
      Δ{formatNum(val, 2)}
    </span>
  )
}

// ── Trade button ─────────────────────────────────────────────────────────────
function TBtn({ label, side, onClick }: { label: string; side: 'BUY' | 'SELL'; onClick: () => void }) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick() }}
      className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded border transition-colors',
        side === 'BUY' ? 'border-profit/40 text-profit bg-profit/8 hover:bg-profit/20' : 'border-loss/40 text-loss bg-loss/8 hover:bg-loss/20')}>
      {label}
    </button>
  )
}

// ── Strike Row ────────────────────────────────────────────────────────────────
interface StrikeRowProps {
  strike: OptionChainStrike; isATM: boolean; spot: number; maxCeOi: number; maxPeOi: number
  oiPrev: OIPrev; onTrade: (symbol: string, ot: 'CE'|'PE', side: 'BUY'|'SELL', ltp: number) => void
  onBasket: (leg: Omit<BasketLeg, 'id'>) => void; exchange: string
}
function StrikeRow({ strike, isATM, spot, maxCeOi, maxPeOi, oiPrev, onTrade, onBasket, exchange }: StrikeRowProps) {
  const isITMCall = spot > strike.strike
  const isITMPut = spot < strike.strike
  const prevOI = oiPrev[strike.strike] ?? { ce: 0, pe: 0 }
  const ceSymbol = strike.trading_symbol_ce || ''
  const peSymbol = strike.trading_symbol_pe || ''

  const addCe = (side: 'BUY' | 'SELL') => onBasket({
    label: `${ceSymbol || strike.strike + 'CE'} ${side}`,
    symbol: ceSymbol, exchange, side, qty: 50, order_type: 'LIMIT', price: strike.ce_ltp ?? 0,
  })
  const addPe = (side: 'BUY' | 'SELL') => onBasket({
    label: `${peSymbol || strike.strike + 'PE'} ${side}`,
    symbol: peSymbol, exchange, side, qty: 50, order_type: 'LIMIT', price: strike.pe_ltp ?? 0,
  })

  return (
    <tr className={cn('group border-b border-border/40 hover:bg-bg-hover/30 transition-colors text-[11px]',
      isATM && 'bg-primary/5 border-primary/30')}>
      {/* CE OI bar */}
      <td className={cn('px-1 py-1', isITMCall && 'bg-loss/4')}>
        <OIBar value={strike.ce_oi ?? 0} max={maxCeOi} side="ce" />
      </td>
      {/* CE OI chg */}
      <td className={cn('px-1 py-1 text-right', isITMCall && 'bg-loss/4')}>
        <OIChg val={strike.ce_oi ?? 0} prevVal={prevOI.ce} />
      </td>
      {/* CE Vol */}
      <td className={cn('px-1 py-1 text-right tabular-nums text-text-muted hide-mobile', isITMCall && 'bg-loss/4')}>
        {strike.ce_volume != null ? (strike.ce_volume >= 1e5 ? `${(strike.ce_volume/1e5).toFixed(1)}L` : strike.ce_volume >= 1e3 ? `${(strike.ce_volume/1e3).toFixed(0)}k` : String(strike.ce_volume)) : '—'}
      </td>
      {/* CE IV */}
      <td className={cn('px-1 py-1 text-right tabular-nums text-text-muted hide-mobile', isITMCall && 'bg-loss/4')}>
        {strike.ce_iv != null ? `${formatNum(strike.ce_iv, 1)}` : '—'}
      </td>
      {/* CE Delta — always visible */}
      <td className={cn('px-1 py-1 text-right', isITMCall && 'bg-loss/4')}>
        <DeltaTag val={strike.ce_delta} />
      </td>
      {/* CE LTP + actions */}
      <td className={cn('px-2 py-1 text-right border-r-2 border-border', isITMCall ? 'bg-loss/8' : '')}>
        <div className="flex items-center justify-end gap-1">
          <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <TBtn label="B" side="BUY" onClick={() => onTrade(ceSymbol, 'CE', 'BUY', strike.ce_ltp ?? 0)} />
            <TBtn label="S" side="SELL" onClick={() => onTrade(ceSymbol, 'CE', 'SELL', strike.ce_ltp ?? 0)} />
            <button onClick={() => addCe('BUY')} title="Add CE to basket"
              className="text-[9px] px-1 py-0.5 rounded border border-accent/30 text-accent bg-accent/8 hover:bg-accent/20 transition-colors">+B</button>
          </div>
          <span className={cn('font-bold tabular-nums', isITMCall ? 'text-loss' : 'text-text-bright')}>
            {formatINR(strike.ce_ltp)}
          </span>
        </div>
      </td>
      {/* Strike */}
      <td className={cn('px-2 py-1 text-center font-bold tabular-nums whitespace-nowrap', isATM ? 'text-primary' : 'text-text-bright')}>
        {strike.strike.toLocaleString('en-IN')}
        {isATM && <div className="text-[8px] text-primary font-semibold leading-none">ATM</div>}
      </td>
      {/* PE LTP + actions */}
      <td className={cn('px-2 py-1 border-l-2 border-border', isITMPut ? 'bg-profit/8' : '')}>
        <div className="flex items-center gap-1">
          <span className={cn('font-bold tabular-nums', isITMPut ? 'text-profit' : 'text-text-bright')}>
            {formatINR(strike.pe_ltp)}
          </span>
          <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={() => addPe('BUY')} title="Add PE to basket"
              className="text-[9px] px-1 py-0.5 rounded border border-accent/30 text-accent bg-accent/8 hover:bg-accent/20 transition-colors">+B</button>
            <TBtn label="B" side="BUY" onClick={() => onTrade(peSymbol, 'PE', 'BUY', strike.pe_ltp ?? 0)} />
            <TBtn label="S" side="SELL" onClick={() => onTrade(peSymbol, 'PE', 'SELL', strike.pe_ltp ?? 0)} />
          </div>
        </div>
      </td>
      {/* PE Delta — always visible */}
      <td className={cn('px-1 py-1', isITMPut && 'bg-profit/4')}>
        <DeltaTag val={strike.pe_delta} />
      </td>
      {/* PE IV */}
      <td className={cn('px-1 py-1 tabular-nums text-text-muted hide-mobile', isITMPut && 'bg-profit/4')}>
        {strike.pe_iv != null ? `${formatNum(strike.pe_iv, 1)}` : '—'}
      </td>
      {/* PE Vol */}
      <td className={cn('px-1 py-1 tabular-nums text-text-muted hide-mobile', isITMPut && 'bg-profit/4')}>
        {strike.pe_volume != null ? (strike.pe_volume >= 1e5 ? `${(strike.pe_volume/1e5).toFixed(1)}L` : strike.pe_volume >= 1e3 ? `${(strike.pe_volume/1e3).toFixed(0)}k` : String(strike.pe_volume)) : '—'}
      </td>
      {/* PE OI chg */}
      <td className={cn('px-1 py-1', isITMPut && 'bg-profit/4')}>
        <OIChg val={strike.pe_oi ?? 0} prevVal={prevOI.pe} />
      </td>
      {/* PE OI bar */}
      <td className={cn('px-1 py-1', isITMPut && 'bg-profit/4')}>
        <OIBar value={strike.pe_oi ?? 0} max={maxPeOi} side="pe" />
      </td>
    </tr>
  )
}
// ── Straddle Chart (SVG) ───────────────────────────────────────────────────
function StraddleChart({ strikes, spot }: { strikes: OptionChainStrike[]; spot: number }) {
  const W = 320, H = 200, PADDING = { top: 10, bottom: 24, left: 56, right: 8 }
  const filtered = strikes.filter((s) => {
    const atmIdx = strikes.findIndex((x) => x.strike >= spot)
    const idx = strikes.indexOf(s)
    return Math.abs(idx - atmIdx) <= 6
  })
  if (!filtered.length) return <div className="text-center text-text-muted text-[11px] py-8">No data</div>

  const straddles = filtered.map((s) => ({ strike: s.strike, val: (s.ce_ltp ?? 0) + (s.pe_ltp ?? 0) }))
  const maxVal = Math.max(...straddles.map((s) => s.val), 1)
  const chartW = W - PADDING.left - PADDING.right
  const chartH = H - PADDING.top - PADDING.bottom
  const bw = Math.floor(chartW / straddles.length) - 2
  const atmStrike = strikes.find((s) => s.strike >= spot)

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      {straddles.map((s, i) => {
        const bh = (s.val / maxVal) * chartH
        const x = PADDING.left + i * (chartW / straddles.length) + 1
        const y = PADDING.top + chartH - bh
        const isATM = s.strike === atmStrike?.strike
        return (
          <g key={s.strike}>
            <rect x={x} y={y} width={bw} height={bh}
              fill={isATM ? 'rgba(34,211,238,0.7)' : 'rgba(129,140,248,0.5)'}
              rx={2} />
            {isATM && <rect x={x} y={PADDING.top} width={bw} height={chartH} fill="rgba(34,211,238,0.06)" rx={2} />}
            <text x={x + bw / 2} y={H - 4} textAnchor="middle" fontSize={8} fill="#6b7280">
              {(s.strike / 100).toFixed(0)}
            </text>
            {bh > 14 && (
              <text x={x + bw / 2} y={y + 10} textAnchor="middle" fontSize={8} fill="white">
                {s.val < 100 ? formatNum(s.val, 0) : formatNum(s.val, 0)}
              </text>
            )}
          </g>
        )
      })}
      {/* Y axis */}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line x1={PADDING.left - 2} y1={PADDING.top + chartH * (1 - f)} x2={W - PADDING.right} y2={PADDING.top + chartH * (1 - f)}
            stroke="#242b3d" strokeWidth={0.5} />
          <text x={PADDING.left - 4} y={PADDING.top + chartH * (1 - f) + 3} textAnchor="end" fontSize={8} fill="#6b7280">
            {formatNum(maxVal * f, 0)}
          </text>
        </g>
      ))}
      <text x={W / 2} y={12} textAnchor="middle" fontSize={9} fill="#8a95ad">
        Straddle Premium by Strike (₹)
      </text>
    </svg>
  )
}

// ── OI Profile Chart (SVG) ─────────────────────────────────────────────────
function OIProfileChart({ strikes, spot }: { strikes: OptionChainStrike[]; spot: number }) {
  const W = 320, H = 260, PADDING = { top: 10, bottom: 8, left: 56, right: 8 }
  const filtered = strikes.filter((s) => {
    const atmIdx = strikes.findIndex((x) => x.strike >= spot)
    const idx = strikes.indexOf(s)
    return Math.abs(idx - atmIdx) <= 8
  })
  if (!filtered.length) return <div className="text-center text-text-muted text-[11px] py-8">No data</div>

  const maxOI = Math.max(...filtered.flatMap((s) => [s.ce_oi ?? 0, s.pe_oi ?? 0]), 1)
  const rowH = Math.floor((H - PADDING.top - PADDING.bottom) / filtered.length)
  const midX = PADDING.left + (W - PADDING.left - PADDING.right) / 2
  const halfW = (W - PADDING.left - PADDING.right) / 2 - 4
  const atmStrike = filtered.find((s) => s.strike >= spot)

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      <text x={midX / 2 + PADDING.left / 2} y={8} textAnchor="middle" fontSize={9} fill="#fb7185">CE OI</text>
      <text x={midX + halfW / 2} y={8} textAnchor="middle" fontSize={9} fill="#4ade80">PE OI</text>
      {filtered.map((s, i) => {
        const y = PADDING.top + i * rowH
        const ceW = (s.ce_oi ?? 0) / maxOI * halfW
        const peW = (s.pe_oi ?? 0) / maxOI * halfW
        const isATM = s.strike === atmStrike?.strike
        return (
          <g key={s.strike}>
            {isATM && <rect x={PADDING.left} y={y} width={W - PADDING.left - PADDING.right} height={rowH - 1} fill="rgba(34,211,238,0.06)" />}
            {/* CE bar: right to left from midX */}
            <rect x={midX - ceW} y={y + 2} width={ceW} height={rowH - 4} fill="rgba(251,113,133,0.6)" rx={1} />
            {/* PE bar: left to right from midX */}
            <rect x={midX} y={y + 2} width={peW} height={rowH - 4} fill="rgba(74,222,128,0.6)" rx={1} />
            {/* Strike label */}
            <text x={midX} y={y + rowH / 2 + 3} textAnchor="middle" fontSize={8} fill={isATM ? '#22d3ee' : '#6b7280'}>
              {s.strike.toLocaleString('en-IN')}
            </text>
            {/* OI labels */}
            {ceW > 20 && <text x={midX - ceW / 2} y={y + rowH / 2 + 3} textAnchor="middle" fontSize={7} fill="white">
              {(( s.ce_oi ?? 0) / 1e5).toFixed(1)}L
            </text>}
            {peW > 20 && <text x={midX + peW / 2} y={y + rowH / 2 + 3} textAnchor="middle" fontSize={7} fill="white">
              {((s.pe_oi ?? 0) / 1e5).toFixed(1)}L
            </text>}
          </g>
        )
      })}
      <line x1={midX} y1={PADDING.top} x2={midX} y2={H - PADDING.bottom} stroke="#374151" strokeWidth={1} />
    </svg>
  )
}

// ── Market View Panel ──────────────────────────────────────────────────────
function MarketViewPanel({ analysis, spot, atm }: { analysis: AnalysisData; spot: number; atm: number }) {
  const biasClr = analysis.bias === 'BULLISH' ? 'text-profit' : analysis.bias === 'BEARISH' ? 'text-loss' : 'text-warning'
  const biasBg = analysis.bias === 'BULLISH' ? 'bg-profit/8 border-profit/25' : analysis.bias === 'BEARISH' ? 'bg-loss/8 border-loss/25' : 'bg-warning/8 border-warning/25'

  return (
    <div className="space-y-3 text-[11px]">
      {/* Bias banner */}
      <div className={cn('rounded-lg border p-3', biasBg)}>
        <div className={cn('font-bold text-[13px] flex items-center gap-2', biasClr)}>
          {analysis.bias === 'BULLISH' ? <TrendingUp className="w-4 h-4" /> : analysis.bias === 'BEARISH' ? <TrendingDown className="w-4 h-4" /> : <Activity className="w-4 h-4" />}
          {analysis.biasLabel}
        </div>
        <p className="text-text-muted mt-1 leading-relaxed">{analysis.summary}</p>
      </div>

      {/* Key levels */}
      <div className="grid grid-cols-2 gap-2">
        <div className="glass rounded-lg p-2.5 space-y-1.5">
          <div className="text-[10px] font-semibold text-text-muted uppercase">Key Levels</div>
          {analysis.resistance && (
            <div className="flex justify-between items-center">
              <span className="text-text-muted flex items-center gap-1"><AlertTriangle className="w-3 h-3 text-loss" />Resistance</span>
              <span className="font-bold text-loss tabular-nums">{analysis.resistance.strike.toLocaleString('en-IN')}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-text-muted">ATM</span>
            <span className="font-semibold text-primary tabular-nums">{atm.toLocaleString('en-IN')}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Spot</span>
            <span className="font-bold text-text-bright tabular-nums">{spot.toLocaleString('en-IN')}</span>
          </div>
          {analysis.support && (
            <div className="flex justify-between items-center">
              <span className="text-text-muted flex items-center gap-1"><Target className="w-3 h-3 text-profit" />Support</span>
              <span className="font-bold text-profit tabular-nums">{analysis.support.strike.toLocaleString('en-IN')}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-text-muted">Max Pain</span>
            <span className="font-semibold text-warning tabular-nums">{analysis.maxPain.toLocaleString('en-IN')}</span>
          </div>
        </div>

        <div className="glass rounded-lg p-2.5 space-y-1.5">
          <div className="text-[10px] font-semibold text-text-muted uppercase">Expected Move</div>
          <div className="flex justify-between">
            <span className="text-text-muted">ATM Straddle</span>
            <span className="font-bold text-primary tabular-nums">₹{formatNum(analysis.atmStraddle, 0)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Implied ±</span>
            <span className="font-semibold text-text-bright tabular-nums">{formatNum(analysis.impliedMove, 0)} pts</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Move %</span>
            <span className="font-semibold text-accent tabular-nums">{formatNum(analysis.impliedPct, 2)}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">PCR</span>
            <span className={cn('font-bold tabular-nums', analysis.pcr >= 1 ? 'text-profit' : 'text-loss')}>
              {formatNum(analysis.pcr, 2)}
            </span>
          </div>
        </div>
      </div>

      {/* Trader activity */}
      <div className="glass rounded-lg p-2.5 space-y-2">
        <div className="text-[10px] font-semibold text-text-muted uppercase">Where Buyers Are Active</div>
        {analysis.buyerZones.map((z, i) => (
          <div key={i} className="flex justify-between items-center">
            <span className={cn('font-semibold', z.side === 'CE' ? 'text-loss' : 'text-profit')}>
              {z.strike.toLocaleString('en-IN')} {z.side}
            </span>
            <span className="text-text-muted">Vol: {z.vol >= 1e5 ? `${(z.vol/1e5).toFixed(1)}L` : z.vol >= 1e3 ? `${(z.vol/1e3).toFixed(0)}k` : z.vol}</span>
          </div>
        ))}
      </div>

      <div className="glass rounded-lg p-2.5 space-y-2">
        <div className="text-[10px] font-semibold text-text-muted uppercase">Where Sellers Are Positioned</div>
        {analysis.sellerZones.map((z, i) => (
          <div key={i} className="flex justify-between items-center">
            <span className={cn('font-semibold', z.side === 'CE' ? 'text-loss' : 'text-profit')}>
              {z.strike.toLocaleString('en-IN')} {z.side}
            </span>
            <span className="text-text-muted">OI: {z.oi >= 1e5 ? `${(z.oi/1e5).toFixed(1)}L` : z.oi >= 1e3 ? `${(z.oi/1e3).toFixed(0)}k` : z.oi}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Basket Panel ──────────────────────────────────────────────────────────
function BasketPanel({ basket, onRemove, onUpdate, onExecute, onClear, executing = false }: {
  basket: BasketLeg[]; onRemove: (id: string) => void
  onUpdate: (id: string, patch: Partial<BasketLeg>) => void
  onExecute: () => void; onClear: () => void; executing?: boolean
}) {
  const totalLegs = basket.length
  return (
    <div className="space-y-2">
      {totalLegs === 0 ? (
        <div className="text-center text-text-muted text-[11px] py-6 flex flex-col items-center gap-2">
          <ShoppingCart className="w-8 h-8 opacity-30" />
          <span>No legs in basket.<br/>Hover a strike row and click <strong className="text-accent">+B</strong> to add.</span>
        </div>
      ) : (
        <>
          {basket.map((leg) => (
            <div key={leg.id} className="glass rounded-lg p-2 space-y-1.5">
              <div className="flex items-start justify-between gap-2">
                <span className="text-[10px] text-text-secondary font-medium leading-tight flex-1">{leg.label}</span>
                <button onClick={() => onRemove(leg.id)} className="text-text-muted hover:text-loss shrink-0">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <div>
                  <div className="text-[9px] text-text-muted mb-0.5">Side</div>
                  <select value={leg.side} onChange={(e) => onUpdate(leg.id, { side: e.target.value as 'BUY' | 'SELL' })}
                    className={cn('w-full h-6 text-[10px] font-bold rounded border bg-bg-input px-1 focus:outline-none',
                      leg.side === 'BUY' ? 'border-profit/40 text-profit' : 'border-loss/40 text-loss')}>
                    <option value="BUY">BUY</option>
                    <option value="SELL">SELL</option>
                  </select>
                </div>
                <div>
                  <div className="text-[9px] text-text-muted mb-0.5">Qty</div>
                  <input type="number" min={1} value={leg.qty}
                    onChange={(e) => onUpdate(leg.id, { qty: Math.max(1, Number(e.target.value)) })}
                    className="w-full h-6 text-[10px] font-mono rounded border border-border bg-bg-input px-1 focus:outline-none focus:border-primary" />
                </div>
                <div>
                  <div className="text-[9px] text-text-muted mb-0.5">Price</div>
                  <input type="number" step="0.05" value={leg.price}
                    onChange={(e) => onUpdate(leg.id, { price: Number(e.target.value), order_type: Number(e.target.value) > 0 ? 'LIMIT' : 'MARKET' })}
                    className="w-full h-6 text-[10px] font-mono rounded border border-border bg-bg-input px-1 focus:outline-none focus:border-primary" />
                </div>
              </div>
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            <button onClick={onClear} className="flex-1 h-8 rounded-lg border border-border text-[11px] text-text-muted hover:border-loss hover:text-loss flex items-center justify-center gap-1">
              <Trash2 className="w-3.5 h-3.5" />Clear
            </button>
            <button onClick={onExecute} disabled={executing}
              className="flex-[2] h-8 rounded-lg bg-primary text-bg-base text-[11px] font-bold flex items-center justify-center gap-1.5 hover:bg-primary/90 disabled:opacity-60">
              {executing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}Execute {totalLegs} Legs
            </button>
          </div>
        </>
      )}
    </div>
  )
}
// ── Quick Trade Modal (422-fixed) ─────────────────────────────────────────
interface TradeModalParams { symbol: string; optionType: 'CE'|'PE'; side: 'BUY'|'SELL'; ltp: number; exchange: string }
function QuickTradeModal({ params, onClose }: { params: TradeModalParams; onClose: () => void }) {
  const { addToast } = useUIStore()
  const [side, setSide] = useState<'BUY'|'SELL'>(params.side)
  const [qty, setQty] = useState(50)
  const [orderType, setOrderType] = useState<'MARKET'|'LIMIT'>('LIMIT')
  const [price, setPrice] = useState(params.ltp)
  const [product, setProduct] = useState('NRML')
  const [busy, setBusy] = useState(false)

  const handleTrade = async () => {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {
        exchange: params.exchange, symbol: params.symbol,
        side, qty, product, order_type: orderType,
      }
      if (orderType === 'LIMIT' && price > 0) payload.price = price
      await api.placeOrder(payload)
      addToast('success', `${side} ${qty} × ${params.optionType} @ ${orderType === 'MARKET' ? 'MKT' : formatINR(price)}`)
      onClose()
    } catch (err) { addToast('error', err instanceof Error ? err.message : 'Order failed') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="glass rounded-2xl p-5 w-full max-w-xs space-y-4 animate-slide-up">
        <div className="flex justify-between items-start">
          <div>
            <div className="font-bold text-[13px] text-text-bright flex items-center gap-1.5">
              <ShoppingCart className="w-4 h-4 text-primary" />Quick Trade</div>
            <div className="text-[11px] text-text-muted">{params.symbol} · {params.optionType} · LTP ~{formatINR(params.ltp)}</div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary text-xl w-7 h-7 flex items-center justify-center">×</button>
        </div>
        <div className="flex gap-2">
          {(['BUY','SELL'] as const).map((s) => (
            <button key={s} onClick={() => setSide(s)}
              className={cn('flex-1 h-9 rounded-lg text-[12px] font-bold border transition-colors',
                s === side ? (s==='BUY' ? 'bg-profit text-bg-base border-profit' : 'bg-loss text-bg-base border-loss') : 'border-border text-text-muted hover:border-border-hover')}>
              {s}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Qty (lots)</label>
            <input type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))}
              className="w-full h-9 px-2.5 rounded-lg bg-bg-input border border-border text-[13px] font-mono text-text-bright focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Product</label>
            <select value={product} onChange={(e) => setProduct(e.target.value)}
              className="w-full h-9 px-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-bright focus:outline-none focus:border-primary">
              {['NRML','MIS','CNC'].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-text-muted uppercase mb-1 block">Order Type</label>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value as 'MARKET'|'LIMIT')}
              className="w-full h-9 px-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-bright focus:outline-none focus:border-primary">
              <option value="LIMIT">LIMIT</option><option value="MARKET">MARKET</option>
            </select>
          </div>
          {orderType === 'LIMIT' && (
            <div>
              <label className="text-[10px] text-text-muted uppercase mb-1 block">Price</label>
              <input type="number" step="0.05" value={price} onChange={(e) => setPrice(Number(e.target.value))}
                className="w-full h-9 px-2.5 rounded-lg bg-bg-input border border-border text-[13px] font-mono text-text-bright focus:outline-none focus:border-primary" />
            </div>
          )}
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 h-9 rounded-lg border border-border text-[12px] text-text-muted hover:border-border-hover">Cancel</button>
          <button onClick={handleTrade} disabled={busy}
            className={cn('flex-[2] h-9 rounded-lg text-[12px] font-bold flex items-center justify-center gap-1.5',
              side==='BUY' ? 'bg-profit text-bg-base' : 'bg-loss text-bg-base', busy && 'opacity-60 cursor-not-allowed')}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShoppingCart className="w-3.5 h-3.5" />}
            {busy ? 'Placing…' : `${side}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────
type AnalysisTab = 'analysis' | 'straddle' | 'oiprofile' | 'basket'

export default function OptionChainPage() {
  const { addToast } = useUIStore()
  const [chains, setChains] = useState<LoadedOptionChain[]>([])
  const [selectedKey, setSelectedKey] = useState<LoadedOptionChain | null>(null)
  const [snapshot, setSnapshot] = useState<OptionChainSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [analysisTab, setAnalysisTab] = useState<AnalysisTab>('analysis')
  const [tradeModal, setTradeModal] = useState<TradeModalParams | null>(null)
  const [basket, setBasket] = useState<BasketLeg[]>([])
  const [executingBasket, setExecutingBasket] = useState(false)
  const [showAnalysis, setShowAnalysis] = useState(true)
  const oiPrevRef = useRef<OIPrev>({})
  const selectedChain = selectedKey

  const loadChains = useCallback(async () => {
    try {
      const data = await api.loadedChains()
      setChains(data)
      if (data.length && !selectedKey) setSelectedKey(data[0])
    } catch (err) { addToast('error', err instanceof Error ? err.message : 'Failed') }
    finally { setLoading(false) }
  }, [selectedKey, addToast])

  const loadSnapshot = useCallback(async () => {
    if (!selectedKey) return
    try {
      const snap = await api.optionChain(selectedKey!)
      // Store prev OI before updating
      if (snap.strikes.length > 0) {
        const newPrev: OIPrev = {}
        for (const s of snap.strikes) {
          if (oiPrevRef.current[s.strike]) {
            // Only update prev if we already have current
            newPrev[s.strike] = oiPrevRef.current[s.strike]
          }
        }
        // Update prev with previous snapshot's current
        if (snapshot?.strikes.length) {
          for (const s of snapshot.strikes) {
            oiPrevRef.current[s.strike] = { ce: s.ce_oi ?? 0, pe: s.pe_oi ?? 0 }
          }
        }
      }
      setSnapshot(snap)
    } catch { /* silent */ }
  }, [selectedKey, snapshot])

  useEffect(() => { loadChains() }, [loadChains])
  useEffect(() => { if (selectedKey) loadSnapshot() }, [selectedKey])
  useEffect(() => {
    if (!autoRefresh || !selectedKey) return
    const t = window.setInterval(loadSnapshot, 2000)
    return () => window.clearInterval(t)
  }, [autoRefresh, selectedKey, loadSnapshot])

  const strikes = snapshot?.strikes ?? []
  const spot = snapshot?.meta?.spot_ltp ?? snapshot?.meta?.fut_ltp ?? 0
  const atm = snapshot?.meta?.atm ?? (strikes.find((s) => s.strike >= spot)?.strike ?? 0)
  const maxCeOi = useMemo(() => Math.max(...strikes.map((s) => s.ce_oi ?? 0), 1), [strikes])
  const maxPeOi = useMemo(() => Math.max(...strikes.map((s) => s.pe_oi ?? 0), 1), [strikes])
  const analysis = useMemo(() => calcAnalysis(strikes, spot), [strikes, spot])
  const totalCeOI = useMemo(() => strikes.reduce((s, r) => s + (r.ce_oi ?? 0), 0), [strikes])
  const totalPeOI = useMemo(() => strikes.reduce((s, r) => s + (r.pe_oi ?? 0), 0), [strikes])

  const addToBasket = useCallback((leg: Omit<BasketLeg, 'id'>) => {
    setBasket((prev) => [...prev, { ...leg, id: Date.now().toString(36) + Math.random().toString(36).slice(2) }])
    setAnalysisTab('basket')
  }, [])

  const executeBasket = async () => {
    if (!basket.length) return
    setExecutingBasket(true)
    try {
      const orders = basket.map((leg) => {
        const o: Record<string, unknown> = {
          exchange: leg.exchange, symbol: leg.symbol, side: leg.side,
          qty: leg.qty, product: 'NRML', order_type: leg.order_type,
        }
        if (leg.order_type === 'LIMIT' && leg.price > 0) o.price = leg.price
        return o
      })
      await api.submitBasketIntent({ orders, reason: 'WEB_BASKET' })
      addToast('success', `Basket of ${basket.length} legs submitted`)
      setBasket([])
    } catch (err) { addToast('error', err instanceof Error ? err.message : 'Basket failed') }
    finally { setExecutingBasket(false) }
  }

  const ANALYSIS_TABS: { key: AnalysisTab; label: string }[] = [
    { key: 'analysis', label: 'Analysis' },
    { key: 'straddle', label: 'Straddle' },
    { key: 'oiprofile', label: 'OI Map' },
    { key: 'basket', label: `Basket${basket.length > 0 ? ` (${basket.length})` : ''}` },
  ]

  return (
    <div className="flex flex-col gap-3 animate-fade-in h-full">
      {/* Header */}
      <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <BarChart2 className="w-5 h-5 text-primary shrink-0" />
        <span className="font-semibold text-text-bright text-sm hidden sm:block">Option Chain</span>
        <select value={selectedKey?.key ?? ''} onChange={(e) => setSelectedKey(chains.find(c => c.key === e.target.value) ?? null)}
          className="h-8 rounded-lg bg-bg-input border border-border px-3 text-[12px] text-text-primary focus:outline-none focus:border-primary flex-1 max-w-xs">
          {chains.map((c) => <option key={c.key} value={c.key}>{c.exchange}:{c.symbol} {c.expiry}</option>)}
        </select>
        <div className="flex-1" />
        <button onClick={() => setShowAnalysis(!showAnalysis)}
          className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors', showAnalysis ? 'bg-accent/15 text-accent border-accent/30' : 'border-border text-text-muted')}>
          {showAnalysis ? <ChevronRight className="w-3.5 h-3.5 inline" /> : <ChevronDown className="w-3.5 h-3.5 inline" />} Analysis
        </button>
        <button onClick={() => setAutoRefresh(!autoRefresh)}
          className={cn('px-2.5 py-1.5 rounded-lg text-[11px] border transition-colors', autoRefresh ? 'bg-primary/15 text-primary border-primary/40' : 'border-border text-text-muted')}>
          {autoRefresh ? <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />LIVE</span> : '⏸'}
        </button>
        <button onClick={loadSnapshot} className="text-text-muted hover:text-text-primary p-1">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Stats strip */}
      {spot > 0 && (
        <div className={cn('glass rounded-xl px-3 py-2 border-l-4', analysis.bias === 'BULLISH' ? 'border-profit' : analysis.bias === 'BEARISH' ? 'border-loss' : 'border-warning')}>
          <div className="flex flex-wrap gap-x-6 gap-y-1 items-center">
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">Spot</span><span className="font-bold text-text-bright tabular-nums text-sm">{spot.toLocaleString('en-IN')}</span></div>
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">ATM</span><span className="font-bold text-primary tabular-nums">{atm.toLocaleString('en-IN')}</span></div>
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">Straddle</span><span className="font-bold text-accent tabular-nums">₹{formatNum(analysis.atmStraddle, 0)}</span></div>
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">±Move</span><span className="font-bold text-text-bright tabular-nums">{formatNum(analysis.impliedMove, 0)} pts</span></div>
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">PCR</span><span className={cn('font-bold tabular-nums', analysis.pcr >= 1 ? 'text-profit' : 'text-loss')}>{formatNum(analysis.pcr, 2)}</span></div>
            <div><span className="text-[10px] text-text-muted uppercase mr-1.5">MaxPain</span><span className="font-bold text-warning tabular-nums">{analysis.maxPain.toLocaleString('en-IN')}</span></div>
            <div className="hidden md:flex"><span className="text-[10px] text-text-muted uppercase mr-1.5">CE OI</span><span className="font-bold text-loss tabular-nums">{(totalCeOI/1e5).toFixed(1)}L</span></div>
            <div className="hidden md:flex"><span className="text-[10px] text-text-muted uppercase mr-1.5">PE OI</span><span className="font-bold text-profit tabular-nums">{(totalPeOI/1e5).toFixed(1)}L</span></div>
            <div className="flex-1" />
            <div className={cn('text-[11px] font-bold', analysis.bias === 'BULLISH' ? 'text-profit' : analysis.bias === 'BEARISH' ? 'text-loss' : 'text-warning')}>
              {analysis.shortSummary}
            </div>
          </div>
        </div>
      )}

      {/* Main 2-col layout */}
      <div className={cn('flex gap-3 min-h-0', showAnalysis ? 'flex-col xl:flex-row' : '')}>
        {/* Option Chain Table */}
        <div className="glass rounded-xl overflow-hidden flex-1 min-w-0">
          {loading ? (
            <div className="flex items-center justify-center h-[300px]"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
          ) : !chains.length ? (
            <div className="flex items-center justify-center h-[300px] text-text-muted text-[12px]">
              <div className="text-center"><Zap className="w-8 h-8 mx-auto mb-2 opacity-30" />No option chains loaded</div>
            </div>
          ) : (
            <div className="overflow-auto max-h-[calc(100vh-280px)]">
              <table className="w-full text-[11px] border-collapse">
                <thead className="sticky top-0 bg-bg-surface z-10">
                  <tr className="border-b border-border">
                    <th colSpan={6} className="px-2 py-2 text-right text-[10px] font-semibold text-loss uppercase tracking-wider border-r-2 border-border">
                      CALLS (CE)
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-bold text-text-muted uppercase tracking-wider">Strike</th>
                    <th colSpan={6} className="px-2 py-2 text-left text-[10px] font-semibold text-profit uppercase tracking-wider border-l-2 border-border">
                      PUTS (PE)
                    </th>
                  </tr>
                  <tr className="border-b border-border/50 text-[9px] text-text-muted uppercase">
                    <th className="px-1 py-1 text-left w-16">OI Bar</th>
                    <th className="px-1 py-1 text-right">Chg</th>
                    <th className="px-1 py-1 text-right hide-mobile">Vol</th>
                    <th className="px-1 py-1 text-right hide-mobile">IV</th>
                    <th className="px-1 py-1 text-right">Δ</th>
                    <th className="px-2 py-1 text-right border-r-2 border-border">LTP</th>
                    <th className="px-2 py-1 text-center"></th>
                    <th className="px-2 py-1 text-left border-l-2 border-border">LTP</th>
                    <th className="px-1 py-1">Δ</th>
                    <th className="px-1 py-1 hide-mobile">IV</th>
                    <th className="px-1 py-1 hide-mobile">Vol</th>
                    <th className="px-1 py-1">Chg</th>
                    <th className="px-1 py-1 text-right w-16">OI Bar</th>
                  </tr>
                </thead>
                <tbody>
                  {strikes.map((s) => (
                    <StrikeRow key={s.strike} strike={s}
                      isATM={s.strike === atm || (atm === 0 && s.strike >= spot)}
                      spot={spot} maxCeOi={maxCeOi} maxPeOi={maxPeOi}
                      oiPrev={oiPrevRef.current}
                      exchange={selectedChain?.exchange ?? 'NFO'}
                      onTrade={(sym, ot, side, ltp) => setTradeModal({ symbol: sym, optionType: ot, side, ltp, exchange: selectedChain?.exchange ?? 'NFO' })}
                      onBasket={addToBasket}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Analysis Panel */}
        {showAnalysis && (
          <div className="xl:w-[340px] glass rounded-xl overflow-hidden flex flex-col shrink-0">
            {/* Tabs */}
            <div className="flex border-b border-border">
              {ANALYSIS_TABS.map((tab) => (
                <button key={tab.key} onClick={() => setAnalysisTab(tab.key)}
                  className={cn('flex-1 px-2 py-2.5 text-[11px] font-medium transition-colors border-b-2',
                    analysisTab === tab.key ? 'border-primary text-primary bg-primary/5' : 'border-transparent text-text-muted hover:text-text-primary',
                    tab.key === 'basket' && basket.length > 0 && 'text-accent')}>
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="p-3 overflow-y-auto flex-1 max-h-[560px]">
              {analysisTab === 'analysis' && strikes.length > 0 && (
                <MarketViewPanel analysis={analysis} spot={spot} atm={atm} />
              )}
              {analysisTab === 'straddle' && <StraddleChart strikes={strikes} spot={spot} />}
              {analysisTab === 'oiprofile' && <OIProfileChart strikes={strikes} spot={spot} />}
              {analysisTab === 'basket' && (
                <BasketPanel basket={basket}
                  onRemove={(id) => setBasket((p) => p.filter((l) => l.id !== id))}
                  onUpdate={(id, patch) => setBasket((p) => p.map((l) => l.id === id ? { ...l, ...patch } : l))}
                  executing={executingBasket} onExecute={executeBasket} onClear={() => setBasket([])} />
              )}
              {analysisTab === 'analysis' && !strikes.length && (
                <div className="text-center text-text-muted text-[11px] py-8">Select an option chain to see analysis</div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Quick trade modal */}
      {tradeModal && <QuickTradeModal params={tradeModal} onClose={() => setTradeModal(null)} />}
    </div>
  )
}
