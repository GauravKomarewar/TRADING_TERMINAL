import { useState, useCallback } from 'react'
import { usePositions, useManagedExitsMap } from '../../hooks'
import { useUIStore } from '../../stores'
import { api } from '../../lib/api'
import { formatINR, pnlClass, cn } from '../../lib/utils'
import { Settings, ToggleLeft, ToggleRight, LogOut, Save, Trash2 } from 'lucide-react'

export function PositionsTable() {
  const { filtered, open, all } = usePositions()
  const managedMap = useManagedExitsMap()
  const { showActiveOnly, setShowActiveOnly, posManagerMode, togglePosManager, addToast } = useUIStore()
  const managedCount = Object.keys(managedMap).length
  const [exitingAll, setExitingAll] = useState(false)

  const handleExitAll = useCallback(async () => {
    if (!confirm('Exit ALL open positions?')) return
    setExitingAll(true)
    try {
      await api.exitAll()
      addToast('success', 'Exit all positions submitted')
    } catch (e: unknown) {
      addToast('error', 'Exit all failed: ' + (e instanceof Error ? e.message : 'Unknown'))
    } finally {
      setExitingAll(false)
    }
  }, [addToast])

  return (
    <div className="glass rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold text-text-bright mr-1">Positions</h2>
        <span className="text-[11px] text-text-muted">
          ({open.length} open, {all.length - open.length} flat{managedCount > 0 ? `, ${managedCount} managed` : ''})
        </span>

        <div className="flex-1" />

        {/* Show Active Toggle */}
        <button
          onClick={() => setShowActiveOnly(!showActiveOnly)}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors border',
            showActiveOnly
              ? 'bg-primary/10 text-primary border-primary/30'
              : 'text-text-muted border-border hover:border-border-hover'
          )}
        >
          {showActiveOnly ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
          Active Only
        </button>

        {/* Position Manager Toggle */}
        <button
          onClick={togglePosManager}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors border',
            posManagerMode
              ? 'bg-accent/10 text-accent border-accent/30'
              : 'text-text-muted border-border hover:border-border-hover'
          )}
        >
          <Settings className="w-3.5 h-3.5" />
          <span className="hide-mobile">Manager</span>
        </button>

        {/* Exit All */}
        {open.length > 0 && (
          <button
            onClick={handleExitAll}
            disabled={exitingAll}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold
              bg-loss/10 text-loss border border-loss/30 hover:bg-loss/20 transition-colors
              disabled:opacity-50"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span className="hide-mobile">Exit All</span>
          </button>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border bg-bg-surface/50">
              <th className="text-left px-3 py-2 font-semibold text-text-muted">Symbol</th>
              <th className="text-right px-3 py-2 font-semibold text-text-muted">LTP</th>
              {!posManagerMode && <>
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Net P&L</th>
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Realized</th>
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Unrealized</th>
                <th className="text-center px-3 py-2 font-semibold text-text-muted hide-mobile">Exch</th>
                <th className="text-center px-3 py-2 font-semibold text-text-muted hide-mobile">Product</th>
              </>}
              <th className="text-right px-3 py-2 font-semibold text-text-muted">Qty</th>
              {!posManagerMode && (
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Avg Price</th>
              )}
              {posManagerMode && <>
                <th className="text-right px-3 py-2 font-semibold text-text-muted">SL</th>
                <th className="text-right px-3 py-2 font-semibold text-text-muted">Target</th>
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Trail</th>
                <th className="text-right px-3 py-2 font-semibold text-text-muted hide-mobile">Trail@</th>
                <th className="text-center px-3 py-2 font-semibold text-text-muted">Status</th>
                <th className="text-center px-3 py-2 font-semibold text-text-muted">Manage</th>
              </>}
              <th className="text-center px-3 py-2 font-semibold text-text-muted">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={20} className="text-center py-8 text-text-muted text-[13px]">
                  No positions
                </td>
              </tr>
            ) : (
              filtered.map(p => (
                <PositionRow
                  key={p._key}
                  position={p}
                  managed={p._key ? managedMap[p._key] : undefined}
                  pmMode={posManagerMode}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Position Row ──
interface PositionRowProps {
  position: import('../../types').Position
  managed?: import('../../types').ManagedExit
  pmMode: boolean
}

function PositionRow({ position: p, managed, pmMode }: PositionRowProps) {
  const { addToast } = useUIStore()
  const sym = p.tsym || p.symbol || '—'
  const exch = p.exch || p.exchange || '—'
  const prd = p.prd || p.product || '—'
  const qty = p._qty || 0
  const isFlat = qty === 0
  const ltp = p._ltp || parseFloat(String(p.lp || p.ltp || 0))
  const netPnl = p._netPnl || 0
  const rpnl = parseFloat(String(p.rpnl || 0))
  const urm = parseFloat(String(p.urmtom || 0))
  const avgPrice = parseFloat(String(p.avgprc || p.avg_price || 0))

  // PM fields
  const [sl, setSl] = useState(managed?.stop_loss != null ? String(managed.stop_loss) : '')
  const [target, setTarget] = useState(managed?.target != null ? String(managed.target) : '')
  const [trail, setTrail] = useState(managed?.trailing_value != null ? String(managed.trailing_value) : '')
  const [trailAt, setTrailAt] = useState(managed?.trail_when != null ? String(managed.trail_when) : '')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const markDirty = () => setDirty(true)

  const handleSave = useCallback(async () => {
    const slNum = sl.trim() ? parseFloat(sl) : null
    const tgtNum = target.trim() ? parseFloat(target) : null
    const trailNum = trail.trim() ? parseFloat(trail) : null
    const twNum = trailAt.trim() ? parseFloat(trailAt) : null

    if (!slNum && !tgtNum && !trailNum) {
      addToast('error', 'Set at least SL, Target, or Trail')
      return
    }

    const isManaged = !!managed
    const exitSide = qty > 0 ? 'SELL' : 'BUY'
    const body: Record<string, unknown> = { symbol: sym }
    if (slNum) body.stop_loss = slNum
    if (tgtNum) body.target = tgtNum
    if (trailNum) { body.trailing_value = trailNum; body.trailing_type = 'POINTS' }
    if (twNum) body.trail_when = twNum
    if (!isManaged) {
      body.exchange = exch
      body.side = exitSide
      body.quantity = Math.abs(qty)
      body.product = prd
    }

    setSaving(true)
    try {
      if (isManaged) {
        await api.updateManagedExit(body)
      } else {
        await api.enableManagedExit(body)
      }
      addToast('success', `${isManaged ? 'Updated' : 'Enabled'} manager for ${sym}`)
      setDirty(false)
    } catch (e: unknown) {
      addToast('error', 'Save failed: ' + (e instanceof Error ? e.message : 'Unknown'))
    } finally {
      setSaving(false)
    }
  }, [sl, target, trail, trailAt, managed, qty, sym, exch, prd, addToast])

  const handleDisable = useCallback(async () => {
    try {
      await api.disableManagedExit(sym)
      addToast('success', `Manager disabled for ${sym}`)
    } catch (e: unknown) {
      addToast('error', 'Disable failed: ' + (e instanceof Error ? e.message : 'Unknown'))
    }
  }, [sym, addToast])

  const handleExit = useCallback(async () => {
    try {
      await api.exitPosition(sym, prd)
      addToast('success', `Exit submitted for ${sym}`)
    } catch (e: unknown) {
      addToast('error', 'Exit failed: ' + (e instanceof Error ? e.message : 'Unknown'))
    }
  }, [sym, prd, addToast])

  return (
    <tr className={cn(
      'border-b border-border/50 hover:bg-bg-hover/50 transition-colors',
      isFlat && 'opacity-40'
    )}>
      {/* Symbol */}
      <td className="px-3 py-2.5">
        <span className="font-semibold text-text-bright font-mono text-[11px]">{sym}</span>
      </td>

      {/* LTP */}
      <td className="px-3 py-2.5 text-right tabular-nums font-mono">{formatINR(ltp)}</td>

      {!pmMode && <>
        <td className={cn('px-3 py-2.5 text-right tabular-nums font-bold hide-mobile', pnlClass(netPnl))}>
          {formatINR(netPnl)}
        </td>
        <td className={cn('px-3 py-2.5 text-right tabular-nums hide-mobile', pnlClass(rpnl))}>
          {formatINR(rpnl)}
        </td>
        <td className={cn('px-3 py-2.5 text-right tabular-nums hide-mobile', pnlClass(urm))}>
          {formatINR(urm)}
        </td>
        <td className="px-3 py-2.5 text-center text-text-muted hide-mobile">{exch}</td>
        <td className="px-3 py-2.5 text-center hide-mobile">
          <span className="badge badge-neutral">{prd}</span>
        </td>
      </>}

      {/* Qty */}
      <td className={cn(
        'px-3 py-2.5 text-right font-bold tabular-nums',
        isFlat ? 'text-text-muted' : qty > 0 ? 'text-profit' : 'text-loss'
      )}>
        {p.netqty || 0}
      </td>

      {!pmMode && (
        <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary hide-mobile">
          {formatINR(avgPrice)}
        </td>
      )}

      {/* PM Columns */}
      {pmMode && (
        isFlat ? (
          <td colSpan={6} className="text-center text-text-muted text-[11px] py-2">—</td>
        ) : <>
          <td className="px-1.5 py-1.5">
            <input
              type="number"
              step="any"
              value={sl}
              onChange={e => { setSl(e.target.value); markDirty() }}
              placeholder="—"
              className="w-full h-7 px-2 text-right text-[11px] tabular-nums font-mono
                bg-transparent border border-transparent rounded
                hover:border-border focus:border-primary focus:bg-bg-input
                text-text-primary placeholder:text-text-muted
                outline-none transition-all"
            />
          </td>
          <td className="px-1.5 py-1.5">
            <input
              type="number"
              step="any"
              value={target}
              onChange={e => { setTarget(e.target.value); markDirty() }}
              placeholder="—"
              className="w-full h-7 px-2 text-right text-[11px] tabular-nums font-mono
                bg-transparent border border-transparent rounded
                hover:border-border focus:border-primary focus:bg-bg-input
                text-text-primary placeholder:text-text-muted
                outline-none transition-all"
            />
          </td>
          <td className="px-1.5 py-1.5 hide-mobile">
            <input
              type="number"
              step="any"
              value={trail}
              onChange={e => { setTrail(e.target.value); markDirty() }}
              placeholder="—"
              className="w-full h-7 px-2 text-right text-[11px] tabular-nums font-mono
                bg-transparent border border-transparent rounded
                hover:border-border focus:border-primary focus:bg-bg-input
                text-text-primary placeholder:text-text-muted
                outline-none transition-all"
            />
          </td>
          <td className="px-1.5 py-1.5 hide-mobile">
            <input
              type="number"
              step="any"
              value={trailAt}
              onChange={e => { setTrailAt(e.target.value); markDirty() }}
              placeholder="—"
              className="w-full h-7 px-2 text-right text-[11px] tabular-nums font-mono
                bg-transparent border border-transparent rounded
                hover:border-border focus:border-primary focus:bg-bg-input
                text-text-primary placeholder:text-text-muted
                outline-none transition-all"
            />
          </td>
          <td className="px-2 py-2 text-center">
            <span className={cn('badge', managed ? 'badge-safe' : 'badge-neutral')}>
              {managed ? 'ACTIVE' : 'OFF'}
            </span>
          </td>
          <td className="px-2 py-2 text-center whitespace-nowrap">
            <button
              onClick={handleSave}
              disabled={saving || (!dirty && !!managed)}
              className={cn(
                'inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold transition-all',
                dirty
                  ? 'bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30'
                  : 'bg-bg-elevated text-text-muted border border-border opacity-50'
              )}
            >
              <Save className="w-3 h-3" />{saving ? '...' : 'Save'}
            </button>
            {managed && (
              <button
                onClick={handleDisable}
                className="ml-1 inline-flex items-center p-1 rounded text-loss/70 hover:text-loss hover:bg-loss/10 transition-colors"
                title="Disable"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            )}
          </td>
        </>
      )}

      {/* Action */}
      <td className="px-3 py-2.5 text-center whitespace-nowrap">
        {isFlat ? (
          <span className="text-[10px] text-text-muted">CLOSED</span>
        ) : (
          <div className="flex items-center justify-center gap-1">
            <button
              onClick={handleExit}
              className="px-2 py-1 rounded text-[10px] font-semibold
                bg-loss/10 text-loss border border-loss/30 hover:bg-loss/20 transition-colors"
            >
              EXIT
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}
