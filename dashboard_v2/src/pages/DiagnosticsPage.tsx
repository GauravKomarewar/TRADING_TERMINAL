import { useState, useEffect } from 'react'
import { Activity, RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle, Clock } from 'lucide-react'
import { cn, timeAgo } from '../lib/utils'
import { api } from '../lib/api'

interface HealthData {
  status?: string
  uptime?: number
  broker_connected?: boolean
  websocket_status?: string
  strategy_runner?: string
  risk_status?: string
  last_heartbeat?: number
  [key: string]: unknown
}

export default function DiagnosticsPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [runner, setRunner] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [snapshot, h, r] = await Promise.all([
        api.dashboardStatus().catch(() => null),
        api.analyticsHealth().catch(() => null) as Promise<HealthData | null>,
        api.runnerStatus().catch(() => null) as Promise<Record<string, unknown> | null>,
      ])

      const heartbeat = snapshot?.system?.heartbeat
      const risk = snapshot?.system?.risk

      setHealth({
        ...h,
        status: h?.status || 'ok',
        broker_connected: heartbeat?.status === 'CONNECTED',
        websocket_status: heartbeat?.status || 'UNKNOWN',
        strategy_runner: String((r?.status as string | undefined) || 'unknown'),
        risk_status: risk?.status || 'UNKNOWN',
        last_heartbeat: heartbeat?.timestamp,
      })
      setRunner(r)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { fetchAll() }, [])

  const StatusIcon = ({ ok }: { ok: boolean | undefined }) =>
    ok ? <CheckCircle2 className="w-3.5 h-3.5 text-profit" />
      : ok === false ? <XCircle className="w-3.5 h-3.5 text-loss" />
      : <AlertTriangle className="w-3.5 h-3.5 text-warning" />

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="glass rounded-xl px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary" />
          <h1 className="text-sm font-semibold text-text-bright">Diagnostics</h1>
        </div>
        <button
          onClick={fetchAll}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-white/5 transition-colors"
        >
          <RefreshCw className={cn('w-4 h-4 text-text-secondary', loading && 'animate-spin')} />
        </button>
      </div>

      {loading && !health ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {/* System Status */}
          <DiagCard title="System Status">
            <DiagRow icon={<StatusIcon ok={health?.status === 'ok' || health?.status === 'running'} />} label="Overall" value={health?.status ?? 'Unknown'} />
            <DiagRow icon={<Clock className="w-3.5 h-3.5 text-text-muted" />} label="Uptime" value={health?.uptime ? `${Math.floor(health.uptime / 3600)}h ${Math.floor((health.uptime % 3600) / 60)}m` : 'N/A'} />
            {health?.last_heartbeat && (
              <DiagRow icon={<Activity className="w-3.5 h-3.5 text-text-muted" />} label="Last Heartbeat" value={timeAgo(health.last_heartbeat)} />
            )}
          </DiagCard>

          {/* Broker Connection */}
          <DiagCard title="Broker Connection">
            <DiagRow icon={<StatusIcon ok={health?.broker_connected} />} label="Connected" value={health?.broker_connected ? 'Yes' : health?.broker_connected === false ? 'No' : 'Unknown'} />
            <DiagRow icon={<StatusIcon ok={health?.websocket_status === 'connected'} />} label="WebSocket" value={health?.websocket_status ?? 'N/A'} />
          </DiagCard>

          {/* Strategy Runner */}
          <DiagCard title="Strategy Runner">
            <DiagRow icon={<StatusIcon ok={runner?.status === 'running' || health?.strategy_runner === 'running'} />}
              label="Status" value={runner?.status as string ?? health?.strategy_runner ?? 'Unknown'} />
            {runner?.active_strategies !== undefined && (
              <DiagRow icon={<Activity className="w-3.5 h-3.5 text-text-muted" />} label="Active Strategies" value={String(runner.active_strategies)} />
            )}
          </DiagCard>

          {/* Risk Manager */}
          <DiagCard title="Risk Manager">
            <DiagRow icon={<StatusIcon ok={health?.risk_status === 'SAFE'} />} label="Status" value={health?.risk_status ?? 'N/A'} />
          </DiagCard>

          {/* Raw Health Data */}
          {health && (
            <div className="sm:col-span-2 lg:col-span-3 glass rounded-xl p-4">
              <h2 className="text-[11px] font-semibold text-text-secondary mb-2">Raw Health Response</h2>
              <pre className="text-[10px] text-text-muted font-mono bg-bg-base rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(health, null, 2)}
              </pre>
            </div>
          )}

          {runner && (
            <div className="sm:col-span-2 lg:col-span-3 glass rounded-xl p-4">
              <h2 className="text-[11px] font-semibold text-text-secondary mb-2">Runner Status</h2>
              <pre className="text-[10px] text-text-muted font-mono bg-bg-base rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(runner, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DiagCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="glass rounded-xl p-4">
      <h2 className="text-[11px] font-semibold text-text-secondary mb-3">{title}</h2>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function DiagRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-[11px] text-text-muted">{label}</span>
      </div>
      <span className="text-[11px] text-text-primary font-medium">{value}</span>
    </div>
  )
}
