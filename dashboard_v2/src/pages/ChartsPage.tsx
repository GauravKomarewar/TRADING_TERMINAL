import { useCallback, useEffect, useRef, useState } from 'react'
import { createChart, type IChartApi, type ISeriesApi, ColorType, LineStyle, CandlestickSeries, type UTCTimestamp } from 'lightweight-charts'
import { BarChart3, Search, Clock, RefreshCw, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import { cn } from '../lib/utils'
import type { OhlcCandle } from '../types'

const TIMEFRAMES = [
  { label: '1m', interval: 1 },
  { label: '5m', interval: 5 },
  { label: '15m', interval: 15 },
  { label: '1h', interval: 60 },
] as const

function candleTime(bucket: string): UTCTimestamp {
  return Math.floor(Date.parse(bucket.replace(' ', 'T') + 'Z') / 1000) as UTCTimestamp
}

export default function ChartsPage() {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartApiRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const [availableSymbols, setAvailableSymbols] = useState<string[]>([])
  const [symbolInput, setSymbolInput] = useState('NIFTY')
  const [symbol, setSymbol] = useState('NIFTY')
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>(TIMEFRAMES[1])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastLoaded, setLastLoaded] = useState<number | null>(null)

  useEffect(() => {
    api.historicalSymbols()
      .then((catalog) => {
        setAvailableSymbols(catalog.index_symbols || [])
        if ((catalog.index_symbols || []).length) {
          const first = catalog.index_symbols[0]
          setSymbol((current) => catalog.index_symbols.includes(current) ? current : first)
          setSymbolInput((current) => catalog.index_symbols.includes(current) ? current : first)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!chartRef.current) return

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: chartRef.current.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#848e9c',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1e222d', style: LineStyle.Solid },
        horzLines: { color: '#1e222d', style: LineStyle.Solid },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#758696', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2a2e3e' },
        horzLine: { color: '#758696', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2a2e3e' },
      },
      rightPriceScale: {
        borderColor: '#2a2e3e',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: '#2a2e3e',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: { vertTouchDrag: false },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#4ade80',
      downColor: '#fb7185',
      borderDownColor: '#fb7185',
      borderUpColor: '#4ade80',
      wickDownColor: '#fb7185',
      wickUpColor: '#4ade80',
    })

    chartApiRef.current = chart
    seriesRef.current = series

    const observer = new ResizeObserver(() => {
      if (chartRef.current) {
        chart.applyOptions({
          width: chartRef.current.clientWidth,
          height: chartRef.current.clientHeight,
        })
      }
    })
    observer.observe(chartRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [])

  const loadCandles = useCallback(async (nextSymbol = symbol, nextTimeframe = timeframe) => {
    setLoading(true)
    setError('')

    try {
      const candles = await api.indexOhlc(nextSymbol, nextTimeframe.interval, 500)
      if (!candles.length) {
        throw new Error(`No candles available for ${nextSymbol}`)
      }

      seriesRef.current?.setData(
        candles.map((candle: OhlcCandle) => ({
          time: candleTime(candle.bucket),
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        })),
      )

      chartApiRef.current?.timeScale().fitContent()
      setLastLoaded(Date.now())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load candles')
      seriesRef.current?.setData([])
    } finally {
      setLoading(false)
    }
  }, [symbol, timeframe])

  useEffect(() => {
    loadCandles(symbol, timeframe)
  }, [loadCandles, symbol, timeframe])

  return (
    <div className="space-y-3 animate-fade-in h-full flex flex-col">
      <div className="glass rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-2 shrink-0">
        <BarChart3 className="w-5 h-5 text-primary" />

        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
          <input
            list="index-symbols"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setSymbol(symbolInput.trim().toUpperCase())
              }
            }}
            placeholder="NIFTY, BANKNIFTY..."
            className="h-8 pl-7 pr-3 w-[200px] rounded-lg bg-bg-input border border-border text-[12px]
              text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
          />
          <datalist id="index-symbols">
            {availableSymbols.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </div>

        <button
          onClick={() => setSymbol(symbolInput.trim().toUpperCase())}
          className="px-2.5 py-1 rounded-md text-[11px] font-medium border text-text-muted border-border hover:border-border-hover"
        >
          Load
        </button>

        <div className="flex gap-0.5 ml-2">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.label}
              onClick={() => setTimeframe(tf)}
              className={cn(
                'px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
                timeframe.label === tf.label
                  ? 'bg-primary/15 text-primary'
                  : 'text-text-muted hover:text-text-secondary hover:bg-bg-hover',
              )}
            >
              {tf.label}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        <button
          onClick={() => loadCandles()}
          className="text-text-muted hover:text-text-primary p-1"
          title="Refresh"
        >
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>

        <div className="flex items-center gap-1.5 text-[11px] text-text-muted">
          <Clock className="w-3.5 h-3.5" />
          <span>Historical</span>
          {lastLoaded ? <span>{new Date(lastLoaded).toLocaleTimeString('en-IN')}</span> : null}
        </div>
      </div>

      {error ? (
        <div className="glass rounded-xl px-4 py-3 text-[12px] text-loss border border-loss/20">
          {error}
        </div>
      ) : null}

      <div className="glass rounded-xl overflow-hidden flex-1 min-h-[400px] relative">
        <div ref={chartRef} className="w-full h-full" />

        {loading ? (
          <div className="absolute inset-0 bg-bg-base/50 backdrop-blur-[1px] flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-primary" />
          </div>
        ) : null}
      </div>
    </div>
  )
}
