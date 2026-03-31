import type {
  AccountLimits,
  DashboardSnapshot,
  HistoricalSymbolCatalog,
  Holding,
  MarketDataSettings,
  LoadedOptionChain,
  OhlcCandle,
  OptionChainHealth,
  OptionInstrument,
  OptionChainSnapshot,
  OptionChainStrike,
  OrderModifyPayload,
  Order,
  Position,
  RiskState,
  Strategy,
  StrategyValidationResult,
  SymbolInfo,
  TelegramMessage,
  TelegramPreferences,
} from '../types'
import { appRoute, slugify, toNumber } from './utils'

type JsonRecord = Record<string, unknown>

function loginRoute() {
  return appRoute('/login')
}

let loginRedirectInProgress = false

function redirectToLogin() {
  const target = loginRoute()
  const currentPath = window.location.pathname.replace(/\/+$/, '') || '/'
  const targetPath = new URL(target, window.location.origin).pathname.replace(/\/+$/, '') || '/'

  // Prevent reload loops when unauthorized checks happen on the login route.
  if (currentPath === targetPath || loginRedirectInProgress) {
    return
  }

  loginRedirectInProgress = true
  window.location.replace(target)
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  const isFormBody = options?.body instanceof FormData || options?.body instanceof URLSearchParams

  if (!headers.has('Content-Type') && options?.body && !isFormBody) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(url, {
    credentials: 'include',
    ...options,
    headers,
  })

  if (res.status === 401) {
    redirectToLogin()
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : typeof body?.message === 'string'
        ? body.message
        : `Request failed: ${res.status}`
    throw new Error(detail)
  }

  const contentType = res.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    return undefined as T
  }

  return res.json() as Promise<T>
}

function get<T>(url: string) {
  return request<T>(url)
}

function post<T>(url: string, body?: unknown) {
  const payload = body instanceof FormData || body instanceof URLSearchParams
    ? body
    : body != null
      ? JSON.stringify(body)
      : undefined

  return request<T>(url, { method: 'POST', body: payload })
}

function normalizeHeartbeat(data: JsonRecord | undefined): { timestamp?: number; status?: string } {
  if (!data || Object.keys(data).length === 0) {
    return { status: 'UNKNOWN' }
  }

  const rawStatus = String(data.status ?? data.connection_status ?? data.state ?? 'UNKNOWN').toUpperCase()
  return {
    status: rawStatus,
    timestamp: toNumber(data.timestamp as number | string | undefined, 0) || undefined,
  }
}

function normalizeRisk(data: JsonRecord | undefined): RiskState {
  const dailyPnl = toNumber(data?.daily_pnl as number | string | undefined, 0)
  const maxLoss = toNumber(
    data?.dynamic_max_loss as number | string | undefined
      ?? data?.max_loss_limit as number | string | undefined
      ?? data?.base_max_loss as number | string | undefined,
    0,
  )
  const peakProfit = toNumber(
    data?.highest_profit as number | string | undefined
      ?? data?.peak_profit as number | string | undefined,
    0,
  )
  const lossHit = Boolean(data?.daily_loss_hit ?? data?.loss_hit)
  const humanViolation = Boolean(data?.human_violation_detected ?? data?.human_violation)
  const forceExit = Boolean(data?.force_exit_in_progress ?? data?.force_exit)

  let status: RiskState['status'] = 'SAFE'
  if (forceExit) status = 'EXIT_IN_PROGRESS'
  else if (humanViolation) status = 'VIOLATION'
  else if (lossHit) status = 'DANGER'
  else if (maxLoss !== 0 && dailyPnl < 0 && Math.abs(dailyPnl) >= Math.abs(maxLoss) * 0.75) status = 'WARNING'

  return {
    daily_pnl: dailyPnl,
    max_loss_limit: maxLoss,
    peak_profit: peakProfit,
    loss_hit: lossHit,
    human_violation: humanViolation,
    force_exit: forceExit,
    status,
  }
}

function normalizeSystemOrder(order: JsonRecord): Order {
  return {
    order_id: String(order.command_id ?? ''),
    symbol: String(order.symbol ?? ''),
    tsym: String(order.symbol ?? ''),
    side: String(order.side ?? ''),
    qty: toNumber(order.quantity as number | string | undefined, 0),
    quantity: toNumber(order.quantity as number | string | undefined, 0),
    price: toNumber(order.price as number | string | undefined, 0),
    prc: toNumber(order.price as number | string | undefined, 0),
    order_type: String(order.order_type ?? ''),
    prctyp: String(order.order_type ?? ''),
    product: String(order.product ?? ''),
    prd: String(order.product ?? ''),
    status: String(order.status ?? ''),
    source: 'SYSTEM',
    updated_at: String(order.updated_at ?? ''),
    exchange: String(order.exchange ?? ''),
    exch: String(order.exchange ?? ''),
  }
}

function normalizeBrokerOrder(order: JsonRecord): Order {
  const source = String(order.source ?? 'BROKER').toUpperCase()
  return {
    ...order as Order,
    order_id: String(order.order_id ?? order.norenordno ?? ''),
    symbol: String(order.symbol ?? order.tsym ?? ''),
    tsym: String(order.tsym ?? order.symbol ?? ''),
    side: String(order.side ?? order.trantype ?? ''),
    qty: order.qty as number | string | undefined,
    quantity: order.quantity as number | string | undefined,
    price: order.price as number | string | undefined,
    prc: order.prc as number | string | undefined,
    order_type: String(order.order_type ?? order.prctyp ?? ''),
    prctyp: String(order.prctyp ?? order.order_type ?? ''),
    product: String(order.product ?? order.prd ?? ''),
    prd: String(order.prd ?? order.product ?? ''),
    status: String(order.status ?? ''),
    source: source === 'SYSTEM' ? 'SYSTEM' : 'BROKER',
    updated_at: String(order.updated_at ?? order.norentm ?? ''),
    exchange: String(order.exchange ?? order.exch ?? ''),
    exch: String(order.exch ?? order.exchange ?? ''),
  }
}

function normalizeDashboardSnapshot(data: JsonRecord): DashboardSnapshot {
  const broker = (data.broker as JsonRecord | undefined) ?? {}
  const system = (data.system as JsonRecord | undefined) ?? {}
  const summary = (broker.positions_summary as JsonRecord | undefined) ?? {}

  return {
    broker: {
      positions: Array.isArray(broker.positions) ? broker.positions as Position[] : [],
      positions_summary: {
        net_pnl: toNumber(summary.net_pnl as number | string | undefined, 0),
        rpnl: toNumber(summary.gross_realized as number | string | undefined, 0),
        open_count: toNumber(summary.open_count as number | string | undefined, 0),
      },
      holdings: Array.isArray(broker.holdings) ? broker.holdings as Holding[] : [],
      limits: (broker.limits as AccountLimits) ?? {},
      orders: Array.isArray(broker.orders)
        ? (broker.orders as JsonRecord[]).map(normalizeBrokerOrder)
        : [],
    },
    system: {
      orders: Array.isArray(system.orders)
        ? (system.orders as JsonRecord[]).map(normalizeSystemOrder)
        : [],
      open_orders: Array.isArray(system.open_orders)
        ? (system.open_orders as JsonRecord[]).map(normalizeSystemOrder)
        : [],
      control_intents: Array.isArray(system.control_intents) ? system.control_intents : [],
      risk: normalizeRisk(system.risk as JsonRecord | undefined),
      heartbeat: normalizeHeartbeat(system.heartbeat as JsonRecord | undefined),
      telegram_messages: Array.isArray(system.telegram_messages) ? system.telegram_messages as TelegramMessage[] : [],
      telegram_stats: (system.telegram_stats as {
        total?: number
        success?: number
        failed?: number
        risk?: number
        alerts?: number
        last_ts?: number
      } | undefined) ?? {},
    },
    managed_exits: Array.isArray(data.managed_exits) ? data.managed_exits as DashboardSnapshot['managed_exits'] : [],
  }
}

function normalizeTelegramPrefs(data: JsonRecord): TelegramPreferences {
  const prefs = (data.preferences as JsonRecord | undefined) ?? data
  return {
    all: Boolean(prefs.all),
    system: Boolean(prefs.system),
    strategy: Boolean(prefs.strategy),
    reports: Boolean(prefs.reports),
  }
}

function modeFromConfig(config: JsonRecord | null | undefined): 'LIVE' | 'MOCK' {
  const identity = (config?.identity as JsonRecord | undefined) ?? {}
  const paperMode = Boolean(identity.paper_mode ?? config?.paper_mode)
  const testMode = identity.test_mode ?? config?.test_mode
  return paperMode || Boolean(testMode) ? 'MOCK' : 'LIVE'
}

function normalizeStrategyStatus(status: unknown): Strategy['status'] {
  const raw = String(status ?? 'IDLE').toUpperCase()
  if (raw === 'RUNNING' || raw === 'PAUSED' || raw === 'STOPPED') return raw
  return 'IDLE'
}

function strategyKeys(...values: Array<unknown>): string[] {
  return values
    .map((value) => typeof value === 'string' ? slugify(value) : '')
    .filter(Boolean)
}

function normalizeSymbolInfo(item: JsonRecord): SymbolInfo {
  const tradingSymbol = String(item.trading_symbol ?? item.tradingsymbol ?? item.symbol ?? '')
  const symbol = String(item.symbol ?? item.underlying ?? tradingSymbol)

  return {
    symbol,
    exchange: String(item.exchange ?? ''),
    trading_symbol: tradingSymbol,
    tradingsymbol: tradingSymbol,
    lot_size: item.lot_size ? toNumber(item.lot_size as number | string | undefined, 0) : undefined,
    tick_size: item.tick_size ? toNumber(item.tick_size as number | string | undefined, 0) : undefined,
    instrument: item.instrument ? String(item.instrument) : undefined,
    description: item.underlying ? String(item.underlying) : undefined,
    underlying: item.underlying ? String(item.underlying) : undefined,
    expiry: item.expiry ? String(item.expiry) : null,
    strike: item.strike != null ? toNumber(item.strike as number | string | undefined, 0) : null,
    option_type: item.option_type ? String(item.option_type) : null,
  }
}

function normalizeOrderbook(data: JsonRecord): { orders: Order[] } {
  const systemOrders = Array.isArray(data.system_orders)
    ? (data.system_orders as JsonRecord[]).map(normalizeSystemOrder)
    : []
  const brokerOrders = Array.isArray(data.broker_orders)
    ? (data.broker_orders as JsonRecord[]).map(normalizeBrokerOrder)
    : []

  return { orders: [...systemOrders, ...brokerOrders] }
}

function mapOptionRows(chain: LoadedOptionChain, data: JsonRecord): OptionChainSnapshot {
  const grouped = new Map<number, OptionChainStrike>()
  const rows = Array.isArray(data.rows) ? data.rows as JsonRecord[] : []

  for (const row of rows) {
    const strike = toNumber(row.strike as number | string | undefined, 0)
    const optionType = String(row.option_type ?? '').toUpperCase()
    if (!grouped.has(strike)) {
      grouped.set(strike, { strike })
    }

    const current = grouped.get(strike)!
    const prefix = optionType === 'PE' ? 'pe' : 'ce'

    Object.assign(current, {
      [`trading_symbol_${prefix}`]: row.trading_symbol ? String(row.trading_symbol) : undefined,
      [`${prefix}_ltp`]: row.ltp != null ? toNumber(row.ltp as number | string | undefined, 0) : undefined,
      [`${prefix}_oi`]: row.oi != null ? toNumber(row.oi as number | string | undefined, 0) : undefined,
      [`${prefix}_volume`]: row.volume != null ? toNumber(row.volume as number | string | undefined, 0) : undefined,
      [`${prefix}_iv`]: row.iv != null ? toNumber(row.iv as number | string | undefined, 0) : undefined,
      [`${prefix}_delta`]: row.delta != null ? toNumber(row.delta as number | string | undefined, 0) : undefined,
      [`${prefix}_gamma`]: row.gamma != null ? toNumber(row.gamma as number | string | undefined, 0) : undefined,
      [`${prefix}_theta`]: row.theta != null ? toNumber(row.theta as number | string | undefined, 0) : undefined,
      [`${prefix}_vega`]: row.vega != null ? toNumber(row.vega as number | string | undefined, 0) : undefined,
      [`${prefix}_change`]: row.change_pct != null ? toNumber(row.change_pct as number | string | undefined, 0) : undefined,
      [`${prefix}_bid`]: row.bid != null ? toNumber(row.bid as number | string | undefined, 0) : undefined,
      [`${prefix}_ask`]: row.ask != null ? toNumber(row.ask as number | string | undefined, 0) : undefined,
      [`${prefix}_last_update`]: row.last_update ? String(row.last_update) : undefined,
    })
  }

  return {
    chain,
    meta: (data.meta as OptionChainSnapshot['meta']) ?? {},
    strikes: Array.from(grouped.values()).sort((a, b) => a.strike - b.strike),
  }
}

async function fetchStrategies(): Promise<{ strategies: Strategy[]; total: number }> {
  const [catalogData, statusData, positionsData] = await Promise.all([
    get<JsonRecord>('/dashboard/strategies/list'),
    get<JsonRecord>('/dashboard/monitoring/all-strategies-status'),
    get<JsonRecord>('/dashboard/monitoring/strategy-positions').catch(() => ({})),
  ])

  const catalog = Array.isArray(catalogData.strategies) ? catalogData.strategies as JsonRecord[] : []
  const statuses = Array.isArray(statusData.strategies) ? statusData.strategies as JsonRecord[] : []
  const rawStrategyPositions = (positionsData as JsonRecord).strategy_positions
  const positions = Array.isArray(rawStrategyPositions) ? rawStrategyPositions as JsonRecord[] : []

  const statusMap = new Map<string, JsonRecord>()
  for (const entry of statuses) {
    for (const key of strategyKeys(entry.name)) {
      statusMap.set(key, entry)
    }
  }

  const positionMap = new Map<string, JsonRecord>()
  for (const entry of positions) {
    for (const key of strategyKeys(entry.strategy_name)) {
      positionMap.set(key, entry)
    }
  }

  const configEntries = await Promise.all(
    catalog.map(async (entry) => {
      const strategyKey = String(entry.slug ?? entry.id ?? entry.label ?? '')
      const config = await get<JsonRecord>(`/dashboard/strategy/config/${encodeURIComponent(strategyKey)}`).catch(() => null)
      return [slugify(strategyKey), config] as const
    }),
  )
  const configMap = new Map(configEntries)

  const strategies = catalog.map((entry) => {
    const safeName = String(entry.slug ?? entry.id ?? entry.label ?? '')
    const slug = slugify(safeName)
    const statusMatch = statusMap.get(slug)
    const config = configMap.get(slug)
    const position = positionMap.get(slug)
    const timing = (config?.timing as JsonRecord | undefined) ?? {}
    const entryConfig = (config?.entry as JsonRecord | undefined) ?? {}
    const legs = Array.isArray(entryConfig.legs) ? entryConfig.legs.length : 0
    const totalPnl =
      toNumber(position?.total_pnl as number | string | undefined, 0)
      || (toNumber(position?.total_realized_pnl as number | string | undefined, 0)
        + toNumber(position?.total_unrealized_pnl as number | string | undefined, 0))

    return {
      name: safeName,
      display_name: String(entry.label ?? config?.name ?? statusMatch?.name ?? safeName),
      status: normalizeStrategyStatus(statusMatch?.status ?? config?.status),
      mode: modeFromConfig(config),
      enabled: Boolean(config?.enabled ?? true),
      total_pnl: totalPnl,
      legs_count: legs,
      entry_time: timing.entry_window_start ? String(timing.entry_window_start) : undefined,
      last_update: statusMatch?.status_updated_at ? String(statusMatch.status_updated_at) : undefined,
      description: config?.description ? String(config.description) : undefined,
    } satisfies Strategy
  })

  return { strategies, total: strategies.length }
}

export const api = {
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams()
    formData.append('username', username || 'dashboard')
    formData.append('password', password)
    const res = await fetch('/auth/login', {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })

    if (res.status === 401) {
      throw new Error('Unauthorized')
    }

    if (!res.ok) {
      throw new Error(`Request failed: ${res.status}`)
    }

    return res.json() as Promise<{ authenticated: boolean }>
  },
  logout: () => post<{ authenticated: boolean }>('/auth/logout'),
  authStatus: () => get<{ authenticated: boolean }>('/auth/status'),

  dashboardStatus: async () => normalizeDashboardSnapshot(await get<JsonRecord>('/dashboard/home/status')),

  exitPosition: (symbol: string, product: string) =>
    post('/dashboard/positions/exit', { symbol, product }),
  exitAll: (product?: string) =>
    post('/dashboard/positions/exit-all', product ? { product } : {}),
  enableManagedExit: (data: Record<string, unknown>) =>
    post('/dashboard/positions/managed-exit/enable', data),
  updateManagedExit: (data: Record<string, unknown>) =>
    post('/dashboard/positions/managed-exit/update', data),
  disableManagedExit: (symbol: string, product?: string) =>
    post('/dashboard/positions/managed-exit/disable', { symbol, product: product || null }),

  orderbook: async (limit = 500) =>
    normalizeOrderbook(await get<JsonRecord>(`/dashboard/orderbook?limit=${limit}`)),
  cancelOrder: (orderId: string) =>
    post('/dashboard/orders/cancel/system', { order_id: orderId }),
  cancelBrokerOrder: (orderId: string) =>
    post('/dashboard/orders/cancel/broker', { order_id: orderId }),
  cancelAllSystemOrders: () =>
    post('/dashboard/orders/cancel/system/all', {}),
  cancelAllBrokerOrders: () =>
    post('/dashboard/orders/cancel/broker/all', {}),
  modifySystemOrder: (payload: OrderModifyPayload) =>
    post('/dashboard/orders/modify/system', payload),
  modifyBrokerOrder: (payload: OrderModifyPayload) =>
    post('/dashboard/orders/modify/broker', payload),

  listStrategies: fetchStrategies,
  getStrategyConfig: (name: string) =>
    get<JsonRecord>(`/dashboard/strategy/config/${encodeURIComponent(name)}`),
  getRawStrategyConfig: (name: string) =>
    get<JsonRecord>(`/dashboard/strategy/config/${encodeURIComponent(name)}`),
  validateStrategyConfig: (config: JsonRecord) =>
    post<StrategyValidationResult>('/dashboard/strategy/validate', config),
  createStrategyConfig: (config: JsonRecord) =>
    post('/dashboard/strategy/create', config),
  updateStrategyConfig: (name: string, config: JsonRecord) =>
    request(`/dashboard/strategy/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  deleteStrategyConfig: (name: string) =>
    request(`/dashboard/strategy/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  cloneStrategyConfig: (name: string, newName: string, underlying?: string) =>
    post(`/dashboard/strategy/config/${encodeURIComponent(name)}/clone`, {
      new_name: newName,
      ...(underlying ? { underlying } : {}),
    }),
  renameStrategyConfig: (name: string, newName: string) =>
    post(`/dashboard/strategy/config/${encodeURIComponent(name)}/rename`, { new_name: newName }),
  startStrategy: (name: string, freshStart = false) =>
    post(`/dashboard/strategy/${encodeURIComponent(name)}/start-execution`, { fresh_start: freshStart }),
  stopStrategy: (name: string) =>
    post(`/dashboard/strategy/${encodeURIComponent(name)}/stop-execution`),

  strategyPositions: () =>
    get('/dashboard/monitoring/strategy-positions'),

  searchSymbols: async (q: string) => {
    const results = await get<JsonRecord[]>(`/dashboard/symbols/search?q=${encodeURIComponent(q)}`)
    return Array.isArray(results) ? results.map(normalizeSymbolInfo) : []
  },
  getExpiries: (exchange: string, symbol: string) =>
    get(`/dashboard/symbols/expiries?exchange=${encodeURIComponent(exchange)}&symbol=${encodeURIComponent(symbol)}`),
  getContracts: (exchange: string, symbol: string, expiry: string) =>
    get(`/dashboard/symbols/contracts?exchange=${encodeURIComponent(exchange)}&symbol=${encodeURIComponent(symbol)}&expiry=${encodeURIComponent(expiry)}`),

  loadedChains: async () => {
    const data = await get<JsonRecord>('/dashboard/settings/option-chains/loaded')
    return Array.isArray(data.chains) ? data.chains as LoadedOptionChain[] : []
  },
  availableOptionInstruments: async () => {
    const data = await get<JsonRecord>('/dashboard/settings/option-chains/available')
    return Array.isArray(data.instruments) ? data.instruments as OptionInstrument[] : []
  },
  optionChainHealth: () =>
    get<OptionChainHealth>('/dashboard/settings/option-chains/health'),
  searchOptionExpiries: (exchange: string, symbol: string) =>
    get(`/dashboard/settings/option-chains/search-expiries?exchange=${encodeURIComponent(exchange)}&symbol=${encodeURIComponent(symbol)}`),
  loadChain: (data: unknown) => post('/dashboard/settings/option-chains/load', data),
  unloadChain: (data: unknown) => post('/dashboard/settings/option-chains/unload', data),
  optionChain: async (chain: LoadedOptionChain) => {
    const params = new URLSearchParams({
      exchange: chain.exchange,
      symbol: chain.symbol,
      expiry: chain.expiry,
    })
    const data = await get<JsonRecord>(`/dashboard/option-chain?${params.toString()}`)
    return mapOptionRows(chain, data)
  },

  getTelegramPrefs: async () => normalizeTelegramPrefs(await get<JsonRecord>('/dashboard/telegram/preferences')),
  setTelegramPrefs: (prefs: Partial<TelegramPreferences>) =>
    post('/dashboard/telegram/preferences', prefs),
  testTelegram: () => post<{ sent: boolean; error?: string }>('/dashboard/telegram/test'),

  analyticsHealth: async () => {
    const health = await get<JsonRecord>('/dashboard/analytics/history/health')
    return {
      ...health,
      status: health.ok ? 'ok' : 'error',
    }
  },
  strategySamples: (params: string) =>
    get(`/dashboard/analytics/history/strategy-samples?${params}`),
  strategyEvents: (params: string) =>
    get(`/dashboard/analytics/history/strategy-events?${params}`),
  indexTicks: (params: string) =>
    get(`/dashboard/analytics/history/index-ticks?${params}`),

  runnerStatus: async () => {
    const runner = await get<JsonRecord>('/dashboard/runner/status')
    return {
      ...runner,
      status: runner.is_running || runner.runner_active ? 'running' : 'stopped',
      active_strategies: runner.strategies_active ?? runner.active_strategies ?? 0,
    }
  },
  runnerFileLogs: async (params: {
    lines?: number
    strategy?: string
    level?: string
    component?: string
  }) => {
    const query = new URLSearchParams()
    if (params.lines != null) query.set('lines', String(params.lines))
    if (params.strategy) query.set('strategy', params.strategy)
    if (params.level) query.set('level', params.level)
    if (params.component) query.set('component', params.component)
    const payload = await get<JsonRecord>(`/dashboard/runner/file-logs?${query.toString()}`)
    return {
      lines: Array.isArray(payload.lines) ? payload.lines.map(String) : [],
      path: typeof payload.path === 'string' ? payload.path : '',
      component: typeof payload.component === 'string' ? payload.component : '',
      updated_at: typeof payload.updated_at === 'string' ? payload.updated_at : '',
    }
  },

  historicalSymbols: () => get<HistoricalSymbolCatalog>('/dashboard/historical/available-symbols'),
  indexOhlc: async (symbol: string, interval: number, limit = 500) => {
    const params = new URLSearchParams({
      symbol: symbol.toUpperCase(),
      interval: String(interval),
      limit: String(limit),
    })
    const data = await get<JsonRecord>(`/dashboard/historical/index-ohlc?${params.toString()}`)
    return Array.isArray(data.candles) ? data.candles as OhlcCandle[] : []
  },

  submitIntent: (data: unknown) => post('/dashboard/intent/generic', data),
  submitBasketIntent: (data: unknown) => post('/dashboard/intent/basket', data),
  submitAdvancedIntent: (data: unknown) => post('/dashboard/intent/advanced', data),
  submitStrategyIntent: (data: unknown) => post('/dashboard/intent/strategy', data),
  forceExit: (strategyName: string) =>
    post('/dashboard/system/force-exit', { strategy_name: strategyName }),

  marketDataSettings: async () => {
    const data = await get<JsonRecord>('/dashboard/settings/market-data/available')
    return {
      indices: Array.isArray(data.indices) ? data.indices : [],
      ticker_symbols: Array.isArray(data.ticker_symbols) ? data.ticker_symbols.map(String) : [],
      sticky_symbols: Array.isArray(data.sticky_symbols) ? data.sticky_symbols.map(String) : [],
    } satisfies MarketDataSettings
  },
  subscribeMarketData: (symbol: string) =>
    post('/dashboard/settings/market-data/subscribe', { symbol }),
  unsubscribeMarketData: (symbol: string) =>
    post('/dashboard/settings/market-data/unsubscribe', { symbol }),
  saveTickerConfig: (tickerSymbols: string[], stickySymbols: string[]) =>
    post('/dashboard/settings/market-data/ticker-config', {
      ticker_symbols: tickerSymbols,
      sticky_symbols: stickySymbols,
    }),

  placeOrder: (data: unknown) => post('/dashboard/intent/generic', data),
}
