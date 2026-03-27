/* ══════════════════════════════════════
   CORE TYPES — Trading Platform V2
   ══════════════════════════════════════ */

// ── Position ──
export interface Position {
  tsym?: string
  symbol?: string
  exch?: string
  exchange?: string
  prd?: string
  product?: string
  netqty?: string | number
  lp?: string | number
  ltp?: string | number
  rpnl?: string | number
  urmtom?: string | number
  avgprc?: string | number
  avg_price?: string | number
  _ltp?: number
  // Computed
  _key?: string
  _netPnl?: number
  _qty?: number
  _side?: 'LONG' | 'SHORT' | 'FLAT'
}

// ── Order ──
export interface Order {
  order_id?: string
  norenordno?: string
  symbol?: string
  tsym?: string
  side?: string
  trantype?: string
  qty?: string | number
  quantity?: string | number
  prc?: string | number
  price?: string | number
  trgprc?: string | number
  trigger_price?: string | number
  prctyp?: string
  order_type?: string
  status?: string
  product?: string
  prd?: string
  exch?: string
  exchange?: string
  updated_at?: string
  norentm?: string
  source?: 'SYSTEM' | 'BROKER'
}

// ── Holding ──
export interface Holding {
  symbol?: string
  tsym?: string
  exch?: string
  exchange?: string
  prd?: string
  product?: string
  netqty?: string | number
  lp?: string | number
  ltp?: string | number
  rpnl?: string | number
  urmtom?: string | number
  avgprc?: string | number
  avg_price?: string | number
}

// ── Managed Exit ──
export interface ManagedExit {
  symbol: string
  product?: string
  exchange?: string
  side?: string
  quantity?: number
  stop_loss?: number | null
  target?: number | null
  trailing_value?: number | null
  trailing_type?: string
  trail_when?: number | null
  trailing_activated?: boolean
}

// ── Risk State ──
export interface RiskState {
  daily_pnl?: number
  max_loss_limit?: number
  peak_profit?: number
  loss_hit?: boolean
  human_violation?: boolean
  force_exit?: boolean
  status?: 'SAFE' | 'WARNING' | 'DANGER' | 'EXIT_IN_PROGRESS' | 'VIOLATION'
}

// ── Account/Limits ──
export interface AccountLimits {
  cash?: number | string
  collateral?: number | string
  marginused?: number | string
  margin_used?: number | string
  marginAvail?: number | string
  margin_available?: number | string
  net_available?: number | string
}

// ── Dashboard Snapshot ──
export interface DashboardSnapshot {
  broker?: {
    positions?: Position[]
    positions_summary?: {
      net_pnl?: number
      rpnl?: number
      open_count?: number
    }
    holdings?: Holding[]
    limits?: AccountLimits
    orders?: Order[]
  }
  system?: {
    orders?: Order[]
    open_orders?: Order[]
    control_intents?: unknown[]
    risk?: RiskState
    heartbeat?: {
      timestamp?: number
      status?: string
    }
    telegram_messages?: TelegramMessage[]
    telegram_stats?: {
      total?: number
      success?: number
      failed?: number
      risk?: number
    }
  }
  managed_exits?: ManagedExit[]
}

// ── Telegram ──
export interface TelegramMessage {
  timestamp?: string
  message?: string
  status?: string
  category?: string
}

export interface TelegramPreferences {
  all: boolean
  system: boolean
  strategy: boolean
  reports: boolean
}

// ── Strategy ──
export interface Strategy {
  name: string
  display_name?: string
  status: 'IDLE' | 'RUNNING' | 'PAUSED' | 'STOPPED'
  mode: 'LIVE' | 'MOCK'
  enabled: boolean
  pnl?: number
  cumulative_daily_pnl?: number
  combined_pnl?: number
  total_pnl?: number
  legs?: number
  legs_count?: number
  entry_time?: string
  last_update?: string
  description?: string
}

export interface StrategyPositionMonitor {
  strategy_name: string
  combined_delta?: number
  combined_gamma?: number
  combined_theta?: number
  combined_vega?: number
  total_pnl?: number
  legs?: StrategyLeg[]
}

export interface StrategyLeg {
  symbol: string
  side: string
  qty: number
  ltp?: number
  pnl?: number
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
}

// ── Symbol Search ──
export interface SymbolInfo {
  symbol: string
  exchange: string
  trading_symbol?: string
  tradingsymbol?: string
  lot_size?: number
  tick_size?: number
  instrument?: string
  description?: string
  underlying?: string
  expiry?: string | null
  strike?: number | null
  option_type?: string | null
}

// ── Option Chain ──
export interface OptionChainStrike {
  strike: number
  trading_symbol_ce?: string
  trading_symbol_pe?: string
  ce_ltp?: number
  pe_ltp?: number
  ce_oi?: number
  pe_oi?: number
  ce_volume?: number
  pe_volume?: number
  ce_iv?: number
  pe_iv?: number
  ce_delta?: number
  pe_delta?: number
  ce_gamma?: number
  pe_gamma?: number
  ce_theta?: number
  pe_theta?: number
  ce_vega?: number
  pe_vega?: number
  ce_change?: number
  pe_change?: number
  ce_bid?: number
  pe_bid?: number
  ce_ask?: number
  pe_ask?: number
  ce_last_update?: string
  pe_last_update?: string
}

export interface LoadedOptionChain {
  key: string
  exchange: string
  symbol: string
  expiry: string
  uptime_seconds?: number
  db_path?: string
  source?: string
}

export interface OptionChainSnapshot {
  chain: LoadedOptionChain
  meta: {
    exchange?: string
    symbol?: string
    expiry?: string
    spot_ltp?: number
    fut_ltp?: number
    atm?: number
    snapshot_ts?: number
    snapshot_age?: number
    is_stale?: boolean
  }
  strikes: OptionChainStrike[]
}

export interface HistoricalSymbolCatalog {
  index_symbols: string[]
  option_symbols: Array<{
    symbol: string
    expiry: string
  }>
}

export interface OhlcCandle {
  bucket: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  oi?: number
}

// ── Toast ──
export type ToastType = 'success' | 'error' | 'info' | 'warning'

export interface Toast {
  id: string
  type: ToastType
  message: string
  duration?: number
}
