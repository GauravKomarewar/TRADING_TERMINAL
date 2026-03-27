import { useDashboardStore } from '../../stores'
import { formatINR } from '../../lib/utils'
import { Wallet } from 'lucide-react'

export function AccountCard() {
  const limits = useDashboardStore(s => s.snapshot?.broker?.limits)

  const items = [
    { label: 'Cash Available', value: limits?.cash },
    { label: 'Collateral', value: limits?.collateral },
    { label: 'Margin Used', value: limits?.marginused || limits?.margin_used },
    { label: 'Margin Available', value: limits?.marginAvail || limits?.margin_available },
    { label: 'Net Available', value: limits?.net_available },
  ]

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
        <Wallet className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-text-bright">Account</h3>
      </div>
      <div className="p-4 space-y-2.5">
        {items.map(item => (
          <div key={item.label} className="flex items-center justify-between">
            <span className="text-[11px] text-text-muted">{item.label}</span>
            <span className="text-[12px] text-text-primary tabular-nums font-mono">
              {formatINR(item.value as number)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
