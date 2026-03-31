import { useState, useCallback } from 'react'
import {
  Cpu, Loader2, RefreshCw, Save, ShieldCheck, Trash2,
  Plus, X, ChevronDown, ChevronRight, AlertCircle, CheckCircle2,
  Code2, Settings2, Shield, Cog, List
} from 'lucide-react'
import { useStrategies } from '../hooks'
import { api } from '../lib/api'
import { cn } from '../lib/utils'
import { useUIStore } from '../stores'
import type { StrategyValidationResult } from '../types'

type RawConfig = Record<string, unknown>
type Tab = 'identity' | 'entry' | 'adjustment' | 'exit' | 'json'

// ─── Helpers ────────────────────────────────────────────────────────────────
function FieldGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider pb-1 border-b border-border/50">{label}</div>
      {children}
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="grid grid-cols-[160px_1fr] gap-3 items-start">
      <div>
        <label className="text-[12px] font-medium text-text-secondary">{label}</label>
        {hint && <div className="text-[10px] text-text-muted mt-0.5">{hint}</div>}
      </div>
      <div>{children}</div>
    </div>
  )
}

const inputCls = "w-full h-8 px-2.5 rounded-lg bg-bg-input border border-border text-[12px] text-text-primary focus:outline-none focus:border-primary transition-colors placeholder:text-text-muted"
const selectCls = "w-full h-8 px-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-primary focus:outline-none focus:border-primary transition-colors"

// ─── Leg Editor ───────────────────────────────────────────────────────────────
interface Leg {
  id: string
  option_type: 'CE' | 'PE'
  side: 'BUY' | 'SELL'
  quantity: number
  strike_selection: string
  strike_offset: number
  product: string
  order_type: string
  expiry_offset: number
}

function LegEditor({ leg, onChange, onRemove }: {
  leg: Leg
  onChange: (updated: Leg) => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(true)
  const up = (k: keyof Leg, v: unknown) => onChange({ ...leg, [k]: v })
  return (
    <div className={cn('glass rounded-lg border overflow-hidden', leg.side === 'BUY' ? 'border-profit/20' : 'border-loss/20')}>
      <div className={cn('px-3 py-2 flex items-center gap-2 cursor-pointer', leg.side === 'BUY' ? 'bg-profit/5' : 'bg-loss/5')} onClick={() => setOpen(!open)}>
        <span className={cn('badge text-[11px]', leg.side === 'BUY' ? 'badge-buy' : 'badge-sell')}>{leg.side}</span>
        <span className={cn('badge text-[11px]', leg.option_type === 'CE' ? 'badge-safe' : 'badge-danger')}>{leg.option_type}</span>
        <span className="text-[12px] font-semibold text-text-bright">{leg.quantity} × {leg.strike_selection}{leg.strike_offset !== 0 ? (leg.strike_offset > 0 ? `+${leg.strike_offset}` : leg.strike_offset) : ''}</span>
        <div className="flex-1" />
        <button onClick={(e) => { e.stopPropagation(); onRemove() }} className="text-text-muted hover:text-loss w-6 h-6 flex items-center justify-center rounded hover:bg-loss/10 transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
        {open ? <ChevronDown className="w-3.5 h-3.5 text-text-muted" /> : <ChevronRight className="w-3.5 h-3.5 text-text-muted" />}
      </div>
      {open && (
        <div className="px-3 py-3 grid grid-cols-2 sm:grid-cols-3 gap-3 text-[11px]">
          <div>
            <label className="text-text-muted block mb-1">Option Type</label>
            <select value={leg.option_type} onChange={(e) => up('option_type', e.target.value as 'CE'|'PE')} className={selectCls}>
              <option value="CE">CE (Call)</option>
              <option value="PE">PE (Put)</option>
            </select>
          </div>
          <div>
            <label className="text-text-muted block mb-1">Side</label>
            <select value={leg.side} onChange={(e) => up('side', e.target.value as 'BUY'|'SELL')} className={selectCls}>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </div>
          <div>
            <label className="text-text-muted block mb-1">Quantity</label>
            <input type="number" min={1} value={leg.quantity} onChange={(e) => up('quantity', Number(e.target.value))} className={inputCls} />
          </div>
          <div>
            <label className="text-text-muted block mb-1">Strike Selection</label>
            <select value={leg.strike_selection} onChange={(e) => up('strike_selection', e.target.value)} className={selectCls}>
              <option value="ATM">ATM</option>
              <option value="ATM+1">ATM+1</option>
              <option value="ATM-1">ATM-1</option>
              <option value="ATM+2">ATM+2</option>
              <option value="ATM-2">ATM-2</option>
              <option value="DELTA">Delta-based</option>
              <option value="CUSTOM">Custom Strike</option>
            </select>
          </div>
          <div>
            <label className="text-text-muted block mb-1">Strike Offset</label>
            <input type="number" value={leg.strike_offset} onChange={(e) => up('strike_offset', Number(e.target.value))} className={inputCls} />
          </div>
          <div>
            <label className="text-text-muted block mb-1">Expiry Offset (weeks)</label>
            <input type="number" min={0} value={leg.expiry_offset} onChange={(e) => up('expiry_offset', Number(e.target.value))} className={inputCls} />
          </div>
          <div>
            <label className="text-text-muted block mb-1">Product</label>
            <select value={leg.product} onChange={(e) => up('product', e.target.value)} className={selectCls}>
              <option value="NRML">NRML</option>
              <option value="MIS">MIS</option>
              <option value="CNC">CNC</option>
            </select>
          </div>
          <div>
            <label className="text-text-muted block mb-1">Order Type</label>
            <select value={leg.order_type} onChange={(e) => up('order_type', e.target.value)} className={selectCls}>
              <option value="MARKET">MARKET</option>
              <option value="LIMIT">LIMIT</option>
              <option value="SL-M">SL-MARKET</option>
            </select>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Identity Tab ─────────────────────────────────────────────────────────────
function IdentityTab({ cfg, onChange }: { cfg: RawConfig; onChange: (p: Partial<RawConfig>) => void }) {
  const identity = (cfg.identity as RawConfig | undefined) ?? {}
  const timing = (cfg.timing as RawConfig | undefined) ?? {}
  return (
    <div className="space-y-5">
      <FieldGroup label="Identity">
        <Field label="Strategy Name" hint="Unique identifier (no spaces)">
          <input value={String(cfg.name || '')} onChange={(e) => onChange({ name: e.target.value })} placeholder="my_straddle_nifty" className={inputCls} />
        </Field>
        <Field label="Display Name">
          <input value={String(identity.display_name || cfg.display_name || '')}
            onChange={(e) => onChange({ identity: { ...identity, display_name: e.target.value } })}
            placeholder="My Straddle Strategy" className={inputCls} />
        </Field>
        <Field label="Description">
          <textarea value={String(cfg.description || '')} onChange={(e) => onChange({ description: e.target.value })}
            rows={2} placeholder="Brief strategy description…"
            className="w-full px-2.5 py-2 rounded-lg bg-bg-input border border-border text-[12px] text-text-primary focus:outline-none focus:border-primary resize-none placeholder:text-text-muted" />
        </Field>
      </FieldGroup>

      <FieldGroup label="Instrument">
        <Field label="Underlying">
          <select value={String(identity.underlying || '')} onChange={(e) => onChange({ identity: { ...identity, underlying: e.target.value } })} className={selectCls}>
            {['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX','BANKEX','CRUDEOIL','GOLD','SILVER','COPPER','NATURALGAS'].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Exchange">
          <select value={String(identity.exchange || 'NFO')} onChange={(e) => onChange({ identity: { ...identity, exchange: e.target.value } })} className={selectCls}>
            {['NFO','BFO','MCX','NSE','BSE'].map((ex) => <option key={ex} value={ex}>{ex}</option>)}
          </select>
        </Field>
        <Field label="Mode">
          <div className="flex gap-2">
            {['LIVE','MOCK'].map((m) => (
              <button key={m} onClick={() => onChange({ identity: { ...identity, paper_mode: m === 'MOCK' } })}
                className={cn('flex-1 h-8 rounded-lg text-[12px] font-semibold border transition-colors',
                  ((m === 'MOCK') === Boolean(identity.paper_mode)) ? (m === 'LIVE' ? 'bg-loss/15 text-loss border-loss/30' : 'bg-primary/15 text-primary border-primary/30') : 'border-border text-text-muted hover:border-border-hover')}>
                {m === 'LIVE' ? '🔴 ' : '🔵 '}{m}
              </button>
            ))}
          </div>
        </Field>
      </FieldGroup>

      <FieldGroup label="Schedule">
        <Field label="Entry Window">
          <div className="flex items-center gap-2">
            <input type="time" value={String(timing.entry_window_start || '09:20')} onChange={(e) => onChange({ timing: { ...timing, entry_window_start: e.target.value } })} className={cn(inputCls, 'w-[120px]')} />
            <span className="text-text-muted text-[11px]">to</span>
            <input type="time" value={String(timing.entry_window_end || '14:30')} onChange={(e) => onChange({ timing: { ...timing, entry_window_end: e.target.value } })} className={cn(inputCls, 'w-[120px]')} />
          </div>
        </Field>
        <Field label="EOD Exit Time">
          <input type="time" value={String(timing.eod_exit_time || '15:15')} onChange={(e) => onChange({ timing: { ...timing, eod_exit_time: e.target.value } })} className={cn(inputCls, 'w-[120px]')} />
        </Field>
        <Field label="Max Re-entries" hint="0 = no re-entry">
          <input type="number" min={0} max={10} value={Number(timing.max_reentries ?? 0)} onChange={(e) => onChange({ timing: { ...timing, max_reentries: Number(e.target.value) } })} className={cn(inputCls, 'w-24')} />
        </Field>
        <Field label="DTE Range" hint="Days to expiry">
          <div className="flex items-center gap-2">
            <input type="number" min={0} placeholder="Min" value={Number(timing.dte_min ?? 0)} onChange={(e) => onChange({ timing: { ...timing, dte_min: Number(e.target.value) } })} className={cn(inputCls, 'w-20')} />
            <span className="text-text-muted text-[11px]">—</span>
            <input type="number" min={0} placeholder="Max" value={Number(timing.dte_max ?? 7)} onChange={(e) => onChange({ timing: { ...timing, dte_max: Number(e.target.value) } })} className={cn(inputCls, 'w-20')} />
          </div>
        </Field>
      </FieldGroup>
    </div>
  )
}

// ─── Entry Tab ────────────────────────────────────────────────────────────────
function entryLegsFromConfig(cfg: RawConfig): Leg[] {
  const entry = (cfg.entry as RawConfig | undefined) ?? {}
  const raw = Array.isArray(entry.legs) ? entry.legs as RawConfig[] : []
  return raw.map((l, idx) => ({
    id: String(l.id ?? idx),
    option_type: (String(l.option_type || l.instrument_type || 'CE').toUpperCase()) === 'PE' ? 'PE' : 'CE',
    side: (String(l.side || l.action || 'SELL').toUpperCase()) === 'BUY' ? 'BUY' : 'SELL',
    quantity: Number(l.quantity ?? l.lots ?? 1),
    strike_selection: String(l.strike_selection || l.strike || 'ATM'),
    strike_offset: Number(l.strike_offset ?? 0),
    product: String(l.product || 'NRML'),
    order_type: String(l.order_type || 'MARKET'),
    expiry_offset: Number(l.expiry_offset ?? 0),
  }))
}

function legsToConfig(legs: Leg[]): unknown[] {
  return legs.map(({ id: _, ...l }) => l)
}

function EntryTab({ cfg, onChange }: { cfg: RawConfig; onChange: (p: Partial<RawConfig>) => void }) {
  const [legs, setLegs] = useState<Leg[]>(() => entryLegsFromConfig(cfg))
  const entry = (cfg.entry as RawConfig | undefined) ?? {}

  const updateLegs = (newLegs: Leg[]) => {
    setLegs(newLegs)
    onChange({ entry: { ...entry, legs: legsToConfig(newLegs) } })
  }

  const addLeg = () => updateLegs([...legs, {
    id: Date.now().toString(),
    option_type: legs.length % 2 === 0 ? 'CE' : 'PE',
    side: 'SELL',
    quantity: 1,
    strike_selection: 'ATM',
    strike_offset: 0,
    product: 'NRML',
    order_type: 'MARKET',
    expiry_offset: 0,
  }])

  return (
    <div className="space-y-4">
      <FieldGroup label="Entry Gate Conditions">
        <Field label="Market Condition">
          <select value={String(entry.market_condition || '')} onChange={(e) => onChange({ entry: { ...entry, market_condition: e.target.value } })} className={selectCls}>
            <option value="">None (Always enter)</option>
            <option value="trend_up">Trend Up</option>
            <option value="trend_down">Trend Down</option>
            <option value="high_iv">High IV</option>
            <option value="low_iv">Low IV</option>
            <option value="range_bound">Range Bound</option>
          </select>
        </Field>
        <Field label="Entry Sequence">
          <select value={String(entry.entry_sequence || 'simultaneous')} onChange={(e) => onChange({ entry: { ...entry, entry_sequence: e.target.value } })} className={selectCls}>
            <option value="simultaneous">Simultaneous</option>
            <option value="sequential">Sequential</option>
          </select>
        </Field>
        <Field label="Min Premium (CE+PE)" hint="Skip entry if combined premium below this">
          <input type="number" min={0} step={10} value={Number(entry.min_combined_premium ?? 0)}
            onChange={(e) => onChange({ entry: { ...entry, min_combined_premium: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
      </FieldGroup>

      <FieldGroup label={`Legs (${legs.length})`}>
        <div className="space-y-2">
          {legs.map((leg, idx) => (
            <LegEditor key={leg.id} leg={leg}
              onChange={(updated) => updateLegs(legs.map((l, i) => i === idx ? updated : l))}
              onRemove={() => updateLegs(legs.filter((_, i) => i !== idx))} />
          ))}
        </div>
        <button onClick={addLeg} className="w-full h-9 rounded-lg border border-dashed border-primary/40 text-primary text-[12px] font-semibold hover:bg-primary/5 transition-colors flex items-center justify-center gap-2">
          <Plus className="w-4 h-4" /> Add Leg
        </button>
      </FieldGroup>
    </div>
  )
}

// ─── Adjustment Tab ──────────────────────────────────────────────────────────
function AdjustmentTab({ cfg, onChange }: { cfg: RawConfig; onChange: (p: Partial<RawConfig>) => void }) {
  const adj = (cfg.adjustment as RawConfig | undefined) ?? {}
  return (
    <div className="space-y-5">
      <FieldGroup label="Adjustment Triggers">
        <Field label="Enable Adjustments">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={Boolean(adj.enabled ?? false)} onChange={(e) => onChange({ adjustment: { ...adj, enabled: e.target.checked } })}
              className="w-4 h-4 rounded border-border bg-bg-input text-primary focus:ring-primary" />
            <span className="text-[12px] text-text-secondary">Enable automatic adjustments</span>
          </label>
        </Field>
        <Field label="Delta Breach Trigger" hint="Hedge when combined delta exceeds this">
          <input type="number" step={0.1} value={Number(adj.delta_breach_trigger ?? 0.3)}
            onChange={(e) => onChange({ adjustment: { ...adj, delta_breach_trigger: Number(e.target.value) } })} className={cn(inputCls, 'w-28')} />
        </Field>
        <Field label="Loss Trigger ₹" hint="Adjust when unrealized loss exceeds">
          <input type="number" step={100} value={Number(adj.loss_trigger ?? 0)}
            onChange={(e) => onChange({ adjustment: { ...adj, loss_trigger: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Time Trigger" hint="Adjust at this time (HH:MM)">
          <input type="time" value={String(adj.time_trigger || '')}
            onChange={(e) => onChange({ adjustment: { ...adj, time_trigger: e.target.value } })} className={cn(inputCls, 'w-32')} />
        </Field>
      </FieldGroup>

      <FieldGroup label="Adjustment Action">
        <Field label="Action Type">
          <select value={String(adj.action_type || 'hedge')} onChange={(e) => onChange({ adjustment: { ...adj, action_type: e.target.value } })} className={selectCls}>
            <option value="hedge">Add Hedge</option>
            <option value="roll">Roll Strikes</option>
            <option value="close_itm">Close ITM Legs</option>
            <option value="reduce_qty">Reduce Quantity</option>
            <option value="close_all">Close All & Re-enter</option>
          </select>
        </Field>
        <Field label="Max Adjustments" hint="Per day limit">
          <input type="number" min={0} value={Number(adj.max_adjustments ?? 3)}
            onChange={(e) => onChange({ adjustment: { ...adj, max_adjustments: Number(e.target.value) } })} className={cn(inputCls, 'w-24')} />
        </Field>
      </FieldGroup>
    </div>
  )
}

// ─── Exit Tab ─────────────────────────────────────────────────────────────────
function ExitTab({ cfg, onChange }: { cfg: RawConfig; onChange: (p: Partial<RawConfig>) => void }) {
  const exit = (cfg.exit as RawConfig | undefined) ?? {}
  const risk = (cfg.risk as RawConfig | undefined) ?? exit
  return (
    <div className="space-y-5">
      <FieldGroup label="Profit Target">
        <Field label="Target Profit ₹">
          <input type="number" step={100} value={Number(exit.target_profit ?? risk.target_profit ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, target_profit: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Target % of Premium" hint="e.g. 50 = exit when 50% premium captured">
          <div className="flex items-center gap-2">
            <input type="number" min={0} max={100} value={Number(exit.target_pct ?? 0)}
              onChange={(e) => onChange({ exit: { ...exit, target_pct: Number(e.target.value) } })} className={cn(inputCls, 'w-24')} />
            <span className="text-text-muted text-[12px]">%</span>
          </div>
        </Field>
      </FieldGroup>

      <FieldGroup label="Stop Loss">
        <Field label="Stop Loss ₹">
          <input type="number" step={100} value={Number(exit.stop_loss ?? risk.stop_loss ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, stop_loss: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Trailing SL ₹" hint="Lock in profit as it grows">
          <input type="number" step={50} value={Number(exit.trailing_sl ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, trailing_sl: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Activate Trail At ₹" hint="Only activate trailing after this profit">
          <input type="number" step={100} value={Number(exit.trail_activate_at ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, trail_activate_at: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
      </FieldGroup>

      <FieldGroup label="Greek Limits">
        <Field label="Max Delta" hint="Exit if combined delta exceeds">
          <input type="number" step={0.1} value={Number(exit.max_delta ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, max_delta: Number(e.target.value) } })} className={cn(inputCls, 'w-28')} />
        </Field>
        <Field label="Max Gamma">
          <input type="number" step={0.001} value={Number(exit.max_gamma ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, max_gamma: Number(e.target.value) } })} className={cn(inputCls, 'w-28')} />
        </Field>
        <Field label="Max Theta Decay ₹" hint="Close if theta decay crosses threshold">
          <input type="number" step={10} value={Number(exit.max_theta ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, max_theta: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Max Vega Exposure">
          <input type="number" step={10} value={Number(exit.max_vega ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, max_vega: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
      </FieldGroup>

      <FieldGroup label="Risk Management">
        <Field label="Max Daily Loss ₹">
          <input type="number" step={500} value={Number(exit.max_daily_loss ?? 0)}
            onChange={(e) => onChange({ exit: { ...exit, max_daily_loss: Number(e.target.value) } })} className={cn(inputCls, 'w-32')} />
        </Field>
        <Field label="Auto-exit on EOD">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={Boolean(exit.auto_exit_eod ?? true)} onChange={(e) => onChange({ exit: { ...exit, auto_exit_eod: e.target.checked } })}
              className="w-4 h-4 rounded border-border bg-bg-input" />
            <span className="text-[12px] text-text-secondary">Exit all positions before EOD</span>
          </label>
        </Field>
      </FieldGroup>
    </div>
  )
}

// ─── JSON Tab ──────────────────────────────────────────────────────────────────
function JsonTab({ value, onChange, validation }: {
  value: string
  onChange: (v: string) => void
  validation: StrategyValidationResult | null
}) {
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-text-muted pb-1">
        Raw JSON config — changes here sync with the form above. All fields accepted.
      </div>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} spellCheck={false}
        className="w-full min-h-[500px] max-h-[68vh] bg-bg-base border border-border rounded-lg p-3 text-[11px] font-mono text-text-secondary resize-y focus:outline-none focus:border-primary" />
      {validation && (
        <div className={cn('rounded-lg p-3 text-[11px]', validation.valid ? 'bg-profit/5 border border-profit/20' : 'bg-loss/5 border border-loss/20')}>
          {validation.valid ? (
            <span className="text-profit flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5" /> Valid configuration</span>
          ) : (
            <div className="space-y-1">
              <span className="text-loss flex items-center gap-1.5"><AlertCircle className="w-3.5 h-3.5" /> {(validation.errors || []).length} validation errors</span>
              {(validation.errors || []).map((err, i) => (
                <div key={i} className="text-text-muted ml-5">• {String(err)}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Empty Template ───────────────────────────────────────────────────────────
const EMPTY_TEMPLATE: RawConfig = {
  name: '',
  display_name: '',
  description: '',
  identity: { underlying: 'NIFTY', exchange: 'NFO', paper_mode: false },
  timing: { entry_window_start: '09:20', entry_window_end: '14:30', eod_exit_time: '15:15', max_reentries: 0, dte_min: 0, dte_max: 7 },
  entry: { legs: [], entry_sequence: 'simultaneous', min_combined_premium: 0 },
  adjustment: { enabled: false, delta_breach_trigger: 0.3, loss_trigger: 0, max_adjustments: 3, action_type: 'hedge' },
  exit: { target_profit: 0, target_pct: 50, stop_loss: 0, trailing_sl: 0, trail_activate_at: 0, max_daily_loss: 0, auto_exit_eod: true, max_delta: 0, max_gamma: 0, max_theta: 0, max_vega: 0 },
}

// ─── Tab Config ───────────────────────────────────────────────────────────────
const TABS: { key: Tab; label: string; icon: typeof Cpu }[] = [
  { key: 'identity', label: 'Identity', icon: Settings2 },
  { key: 'entry', label: 'Entry Legs', icon: List },
  { key: 'adjustment', label: 'Adjustments', icon: Cog },
  { key: 'exit', label: 'Exit & Risk', icon: Shield },
  { key: 'json', label: 'JSON', icon: Code2 },
]

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function StrategyBuilderPage() {
  const { data, isLoading, refetch } = useStrategies()
  const { addToast } = useUIStore()
  const strategies = data?.strategies || []

  const [selectedName, setSelectedName] = useState('')
  const [activeTab, setActiveTab] = useState<Tab>('identity')
  const [config, setConfig] = useState<RawConfig>({ ...EMPTY_TEMPLATE })
  const [jsonEditor, setJsonEditor] = useState(JSON.stringify(EMPTY_TEMPLATE, null, 2))
  const [dirty, setDirty] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [validation, setValidation] = useState<StrategyValidationResult | null>(null)
  const [cloneName, setCloneName] = useState('')
  const [renameName, setRenameName] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const syncJsonFromConfig = useCallback((cfg: RawConfig) => {
    setJsonEditor(JSON.stringify(cfg, null, 2))
  }, [])

  const updateConfig = useCallback((patch: Partial<RawConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...patch }
      setJsonEditor(JSON.stringify(next, null, 2))
      setDirty(true)
      return next
    })
    setValidation(null)
  }, [])

  const onJsonChange = useCallback((v: string) => {
    setJsonEditor(v)
    setDirty(true)
    try {
      const parsed = JSON.parse(v) as RawConfig
      setConfig(parsed)
      setValidation(null)
    } catch { /* keep dirty */ }
  }, [])

  async function run(action: string, fn: () => Promise<void>) {
    setBusyAction(action)
    try { await fn() } finally { setBusyAction('') }
  }

  const loadConfig = async (strategyName: string) => {
    await run(`load-${strategyName}`, async () => {
      const cfg = await api.getRawStrategyConfig(strategyName) as RawConfig
      setSelectedName(strategyName)
      setConfig(cfg)
      syncJsonFromConfig(cfg)
      setDirty(false)
      setValidation(null)
      setCloneName(`${strategyName}_COPY`)
      setRenameName(strategyName)
    })
  }

  const validateCurrent = async () => {
    let payload: RawConfig
    try { payload = JSON.parse(jsonEditor) as RawConfig }
    catch { addToast('error', 'Invalid JSON in editor'); return }
    await run('validate', async () => {
      const result = await api.validateStrategyConfig(payload)
      setValidation(result)
      if (result.valid) addToast('success', 'Validation passed ✓')
      else addToast('warning', `${(result.errors || []).length} validation errors`)
    })
  }

  const saveCurrent = async () => {
    let payload: RawConfig
    try { payload = JSON.parse(jsonEditor) as RawConfig }
    catch { addToast('error', 'Invalid JSON'); return }
    const name = String(payload.name || selectedName || '').trim()
    if (!name) { addToast('error', 'Strategy name is required'); return }
    await run('save', async () => {
      if (selectedName) await api.updateStrategyConfig(selectedName, payload)
      else await api.createStrategyConfig(payload)
      await refetch()
      setSelectedName(name)
      setDirty(false)
      addToast('success', `${selectedName ? 'Updated' : 'Created'} "${name}"`)
      await loadConfig(name)
    })
  }

  const cloneCurrent = async () => {
    if (!selectedName || !cloneName.trim()) return
    await run('clone', async () => {
      await api.cloneStrategyConfig(selectedName, cloneName.trim())
      await refetch()
      addToast('success', `Cloned to "${cloneName.trim()}"`)
    })
  }

  const renameCurrent = async () => {
    if (!selectedName || !renameName.trim() || renameName === selectedName) return
    await run('rename', async () => {
      await api.renameStrategyConfig(selectedName, renameName.trim())
      await refetch()
      addToast('success', `Renamed to "${renameName.trim()}"`)
      await loadConfig(renameName.trim())
    })
  }

  const deleteCurrent = async () => {
    if (!selectedName || !window.confirm(`Delete "${selectedName}"?`)) return
    await run('delete', async () => {
      await api.deleteStrategyConfig(selectedName)
      await refetch()
      setSelectedName('')
      setConfig({ ...EMPTY_TEMPLATE })
      syncJsonFromConfig({ ...EMPTY_TEMPLATE })
      setDirty(false)
      addToast('success', 'Strategy deleted')
    })
  }

  const createNew = () => {
    setSelectedName('')
    setConfig({ ...EMPTY_TEMPLATE })
    syncJsonFromConfig({ ...EMPTY_TEMPLATE })
    setDirty(false)
    setValidation(null)
    setActiveTab('identity')
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="glass rounded-xl px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-5 h-5 text-primary shrink-0" />
          <div>
            <h1 className="text-sm font-semibold text-text-bright">Strategy Builder</h1>
            <p className="text-[11px] text-text-muted">Multi-tab config editor with JSON fallback</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-[11px] text-warning flex items-center gap-1"><AlertCircle className="w-3.5 h-3.5" />Unsaved</span>}
          <button onClick={() => refetch()} className="p-1.5 rounded-lg hover:bg-white/5 transition-colors">
            <RefreshCw className={cn('w-4 h-4 text-text-secondary', isLoading && 'animate-spin')} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-4">
        {/* Sidebar: strategy list */}
        <div className={cn('glass rounded-xl overflow-hidden', sidebarOpen ? 'block' : 'hidden xl:block')}>
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <span className="text-[11px] font-semibold text-text-bright">Strategies</span>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="xl:hidden text-text-muted hover:text-text-primary">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-2 space-y-1 max-h-[calc(100vh-260px)] overflow-auto">
            <button onClick={createNew} className="w-full px-3 py-2 rounded-lg border border-dashed border-primary/40 text-primary text-[12px] font-semibold hover:bg-primary/5 transition-colors flex items-center justify-center gap-1.5">
              <Plus className="w-3.5 h-3.5" />New Strategy
            </button>
            {isLoading ? (
              <div className="py-12 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-primary" /></div>
            ) : strategies.length === 0 ? (
              <div className="text-[12px] text-center text-text-muted py-8">No strategies</div>
            ) : strategies.map((s) => (
              <button key={s.name} onClick={() => loadConfig(s.name)}
                className={cn('w-full p-2.5 rounded-lg border text-left transition-colors',
                  selectedName === s.name ? 'border-primary/40 bg-primary/10' : 'border-border hover:border-border-hover bg-bg-surface/30',
                  busyAction === `load-${s.name}` && 'opacity-60')}>
                <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                  <span className={cn('badge text-[10px]', s.mode === 'LIVE' ? 'badge-live' : 'badge-mock')}>{s.mode}</span>
                  <span className={cn('badge text-[10px]', s.status === 'RUNNING' ? 'badge-safe' : 'badge-neutral')}>{s.status}</span>
                </div>
                <div className="text-[12px] font-semibold text-text-bright truncate">{s.display_name || s.name}</div>
                <div className="text-[10px] text-text-muted font-mono truncate">{s.name}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Main editor */}
        <div className="space-y-3">
          {/* Actions bar */}
          <div className="glass rounded-xl p-2.5 flex flex-wrap gap-2 items-center">
            <button onClick={validateCurrent} disabled={!!busyAction}
              className="px-3 py-1.5 rounded-md border border-border text-[11px] font-semibold text-text-secondary disabled:opacity-50 hover:border-border-hover flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />{busyAction === 'validate' ? 'Validating…' : 'Validate'}
            </button>
            <button onClick={saveCurrent} disabled={!!busyAction}
              className="px-3 py-1.5 rounded-md bg-primary text-bg-base text-[11px] font-semibold disabled:opacity-50 flex items-center gap-1 hover:bg-primary/90">
              <Save className="w-3.5 h-3.5" />{busyAction === 'save' ? 'Saving…' : selectedName ? 'Update' : 'Create'}
            </button>

            <div className="h-5 w-px bg-border mx-1" />

            <div className="flex items-center gap-1.5">
              <input value={renameName} onChange={(e) => setRenameName(e.target.value)} placeholder="Rename to…"
                className="h-7 px-2 rounded-md bg-bg-input border border-border text-[11px] w-[140px] focus:outline-none focus:border-primary" />
              <button onClick={renameCurrent} disabled={!selectedName || !!busyAction}
                className="h-7 px-2.5 rounded-md border border-border text-[11px] text-text-secondary disabled:opacity-50 hover:border-border-hover">
                {busyAction === 'rename' ? 'Renaming…' : 'Rename'}
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              <input value={cloneName} onChange={(e) => setCloneName(e.target.value)} placeholder="Clone as…"
                className="h-7 px-2 rounded-md bg-bg-input border border-border text-[11px] w-[140px] focus:outline-none focus:border-primary" />
              <button onClick={cloneCurrent} disabled={!selectedName || !!busyAction}
                className="h-7 px-2.5 rounded-md border border-border text-[11px] text-text-secondary disabled:opacity-50 hover:border-border-hover">
                {busyAction === 'clone' ? 'Cloning…' : 'Clone'}
              </button>
            </div>

            <button onClick={deleteCurrent} disabled={!selectedName || !!busyAction}
              className="ml-auto h-7 px-2.5 rounded-md border border-loss/40 text-loss text-[11px] font-semibold disabled:opacity-50 flex items-center gap-1 hover:bg-loss/10">
              <Trash2 className="w-3.5 h-3.5" />{busyAction === 'delete' ? 'Deleting…' : 'Delete'}
            </button>
          </div>

          {/* Tab Bar */}
          <div className="glass rounded-xl overflow-hidden">
            <div className="flex border-b border-border overflow-x-auto">
              {TABS.map((tab) => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  className={cn(
                    'flex items-center gap-1.5 px-4 py-2.5 text-[12px] font-medium border-b-2 transition-colors shrink-0',
                    activeTab === tab.key
                      ? 'border-primary text-primary bg-primary/5'
                      : 'border-transparent text-text-muted hover:text-text-primary hover:bg-bg-hover',
                  )}>
                  <tab.icon className="w-3.5 h-3.5" />
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'identity' && <IdentityTab cfg={config} onChange={updateConfig} />}
              {activeTab === 'entry' && <EntryTab cfg={config} onChange={updateConfig} />}
              {activeTab === 'adjustment' && <AdjustmentTab cfg={config} onChange={updateConfig} />}
              {activeTab === 'exit' && <ExitTab cfg={config} onChange={updateConfig} />}
              {activeTab === 'json' && <JsonTab value={jsonEditor} onChange={onJsonChange} validation={validation} />}
            </div>
          </div>

          {/* Bottom status */}
          <div className="flex items-center justify-between text-[10px] text-text-muted px-1">
            <span>{selectedName ? `Editing: ${selectedName}` : 'New strategy (unsaved)'}</span>
            <span className={dirty ? 'text-warning' : 'text-profit'}>{dirty ? '● Unsaved changes' : '✓ Synced'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
