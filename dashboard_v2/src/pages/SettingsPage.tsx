import { Settings, Bell, Grid3X3, Monitor, Shield } from 'lucide-react'

export default function SettingsPage() {
  return (
    <div className="space-y-4 animate-fade-in max-w-3xl">
      <div className="glass rounded-xl px-4 py-3 flex items-center gap-2">
        <Settings className="w-5 h-5 text-primary" />
        <h1 className="text-sm font-semibold text-text-bright">Settings</h1>
      </div>

      <div className="glass rounded-xl px-4 py-3 border border-warning/20 bg-warning/5">
        <p className="text-[12px] text-text-secondary">
          This page is still a preview surface in v2. Operational controls continue to live in the Dashboard, Orderbook, Charts,
          Option Chain, and Diagnostics pages where the backend contracts have been verified.
        </p>
      </div>

      <div className="space-y-3">
        <SettingsSection icon={Grid3X3} title="Option Chain Management">
          <p className="text-[12px] text-text-muted">
            Manage loaded option chains, add new instruments, configure strike gaps and expiry preferences.
          </p>
          <button className="mt-3 px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-[11px] font-semibold border border-primary/30 hover:bg-primary/20 transition-colors">
            Manage Chains
          </button>
        </SettingsSection>

        <SettingsSection icon={Bell} title="Notification Preferences">
          <p className="text-[12px] text-text-muted">
            Configure Telegram notifications for system events, strategy alerts, and daily reports.
            Use the Telegram card on the dashboard for quick toggles.
          </p>
        </SettingsSection>

        <SettingsSection icon={Monitor} title="Display Preferences">
          <p className="text-[12px] text-text-muted">
            Theme, layout, and display customization options. Currently using dark theme optimized for trading.
          </p>
        </SettingsSection>

        <SettingsSection icon={Shield} title="Risk Settings">
          <p className="text-[12px] text-text-muted">
            Risk management parameters are configured via primary.env file.
            Current max loss limit and other risk parameters are shown on the dashboard.
          </p>
        </SettingsSection>
      </div>
    </div>
  )
}

function SettingsSection({ icon: Icon, title, children }: { icon: typeof Settings; title: string; children: React.ReactNode }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-text-secondary" />
        <h2 className="text-[13px] font-semibold text-text-bright">{title}</h2>
      </div>
      {children}
    </div>
  )
}
