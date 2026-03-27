import { useState } from 'react'
import { Cpu, ChevronDown, ChevronUp, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { useStrategies } from '../hooks'
import { api } from '../lib/api'
import { cn } from '../lib/utils'

type RawConfig = Record<string, unknown>

export default function StrategyBuilderPage() {
  const { data, isLoading, refetch } = useStrategies()
  const strategies = data?.strategies || []

  const [expanded, setExpanded] = useState<string | null>(null)
  const [configs, setConfigs] = useState<Record<string, RawConfig | null>>({})
  const [loadingName, setLoadingName] = useState<string | null>(null)

  async function toggleStrategy(name: string) {
    const next = expanded === name ? null : name
    setExpanded(next)

    if (next && !(name in configs)) {
      setLoadingName(name)
      try {
        const config = await api.getRawStrategyConfig(name)
        setConfigs((prev) => ({ ...prev, [name]: config }))
      } catch {
        setConfigs((prev) => ({ ...prev, [name]: null }))
      } finally {
        setLoadingName(null)
      }
    }
  }

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="glass rounded-xl px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-5 h-5 text-primary" />
          <div>
            <h1 className="text-sm font-semibold text-text-bright">Strategy Builder</h1>
            <p className="text-[11px] text-text-muted">Read-only in v2 to protect the live config schema</p>
          </div>
        </div>

        <button
          onClick={() => refetch()}
          className="p-1.5 rounded-lg hover:bg-white/5 transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4 text-text-secondary" />
        </button>
      </div>

      <div className="glass rounded-xl px-4 py-3 border border-warning/20 bg-warning/5">
        <div className="flex items-start gap-2">
          <ShieldAlert className="w-4 h-4 text-warning mt-0.5" />
          <p className="text-[12px] text-text-secondary">
            The original editor payload did not match the production strategy schema, so edits are intentionally disabled here.
            This screen is now a safe inspector for live strategy configs.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-56">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      ) : strategies.length === 0 ? (
        <div className="glass rounded-xl p-8 text-center text-[12px] text-text-muted">
          No strategies discovered.
        </div>
      ) : (
        <div className="space-y-2">
          {strategies.map((strategy) => {
            const config = configs[strategy.name]
            const identity = (config?.identity as RawConfig | undefined) ?? {}
            const timing = (config?.timing as RawConfig | undefined) ?? {}
            const entry = (config?.entry as RawConfig | undefined) ?? {}
            const legs = Array.isArray(entry.legs) ? entry.legs.length : strategy.legs_count || 0

            return (
              <div key={strategy.name} className="glass rounded-xl overflow-hidden">
                <button
                  onClick={() => toggleStrategy(strategy.name)}
                  className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[.02] transition-colors"
                >
                  <div className="text-left min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cn('badge', strategy.mode === 'LIVE' ? 'badge-live' : 'badge-mock')}>
                        {strategy.mode}
                      </span>
                      <span className={cn('badge',
                        strategy.status === 'RUNNING' ? 'badge-safe'
                          : strategy.status === 'PAUSED' ? 'badge-warning'
                            : 'badge-neutral'
                      )}>
                        {strategy.status}
                      </span>
                    </div>
                    <div className="text-[13px] font-semibold text-text-bright mt-1 truncate">
                      {strategy.display_name || strategy.name}
                    </div>
                    {(strategy.display_name || strategy.name) !== strategy.name ? (
                      <div className="text-[10px] text-text-muted font-mono truncate">{strategy.name}</div>
                    ) : null}
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <div className="text-right text-[11px] text-text-muted">
                      <div>{legs} legs</div>
                      <div>{String(identity.underlying ?? 'Underlying n/a')}</div>
                    </div>
                    {expanded === strategy.name ? (
                      <ChevronUp className="w-4 h-4 text-text-secondary" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-text-secondary" />
                    )}
                  </div>
                </button>

                {expanded === strategy.name ? (
                  <div className="px-4 pb-4 border-t border-border space-y-3">
                    {loadingName === strategy.name ? (
                      <div className="py-8 flex items-center justify-center">
                        <Loader2 className="w-5 h-5 animate-spin text-primary" />
                      </div>
                    ) : config ? (
                      <>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3">
                          <InfoField label="Underlying" value={String(identity.underlying ?? '—')} />
                          <InfoField label="Exchange" value={String(identity.exchange ?? '—')} />
                          <InfoField label="Entry Window" value={String(timing.entry_window_start ?? '—')} />
                          <InfoField label="Exit Time" value={String(timing.eod_exit_time ?? '—')} />
                        </div>

                        <div className="rounded-xl bg-bg-base border border-border p-3">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-[11px] font-semibold text-text-secondary">Raw Config</span>
                            <span className="text-[10px] text-text-muted">Read-only</span>
                          </div>
                          <pre className="text-[10px] text-text-muted font-mono overflow-x-auto max-h-[420px] overflow-y-auto">
                            {JSON.stringify(config, null, 2)}
                          </pre>
                        </div>
                      </>
                    ) : (
                      <div className="py-6 text-[12px] text-text-muted">
                        Unable to load this strategy config.
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function InfoField({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg-base border border-border rounded-lg px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-text-muted">{label}</div>
      <div className="text-[12px] text-text-primary font-medium mt-1">{value}</div>
    </div>
  )
}
