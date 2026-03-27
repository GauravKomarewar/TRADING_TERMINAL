import { useState, useCallback } from 'react'
import { useTelegramPrefs } from '../../hooks'
import { useUIStore } from '../../stores'
import { api } from '../../lib/api'
import { Bell, Send }  from 'lucide-react'
import { cn } from '../../lib/utils'
import { useQueryClient } from '@tanstack/react-query'

export function TelegramCard() {
  const { data: prefs, isLoading } = useTelegramPrefs()
  const { addToast } = useUIStore()
  const client = useQueryClient()
  const [testing, setTesting] = useState(false)

  const togglePref = useCallback(async (key: string, value: boolean) => {
    try {
      await api.setTelegramPrefs({ [key]: value })
      client.invalidateQueries({ queryKey: ['telegram-prefs'] })
      addToast('success', `Telegram ${key} ${value ? 'enabled' : 'disabled'}`)
    } catch {
      addToast('error', 'Failed to update preferences')
    }
  }, [addToast, client])

  const handleTest = useCallback(async () => {
    setTesting(true)
    try {
      const res = await api.testTelegram()
      if (res.sent) addToast('success', 'Test message sent!')
      else addToast('error', 'Test failed: ' + (res.error || 'Unknown'))
    } catch (e: unknown) {
      addToast('error', 'Test failed: ' + (e instanceof Error ? e.message : 'Unknown'))
    } finally {
      setTesting(false)
    }
  }, [addToast])

  const categories = [
    { key: 'all', label: 'All Messages' },
    { key: 'system', label: 'System / Status' },
    { key: 'strategy', label: 'Strategy / Orders' },
    { key: 'reports', label: 'Reports / Summaries' },
  ]

  const allOff = !prefs?.all && !prefs?.system && !prefs?.strategy && !prefs?.reports
  const partial = prefs && !prefs.all && (prefs.system || prefs.strategy || prefs.reports)

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Bell className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold text-text-bright">Telegram</h3>
        </div>
        <span className={cn('badge',
          allOff ? 'badge-danger' : partial ? 'badge-warning' : 'badge-safe'
        )}>
          {allOff ? 'OFF' : partial ? 'PARTIAL' : 'ALL ON'}
        </span>
      </div>

      <div className="p-4 space-y-2">
        {isLoading ? (
          <div className="text-[12px] text-text-muted text-center py-4">Loading...</div>
        ) : (
          categories.map(cat => {
            const isOn = prefs?.[cat.key as keyof typeof prefs] ?? false
            return (
              <div key={cat.key} className="flex items-center justify-between py-1">
                <span className="text-[12px] text-text-secondary">{cat.label}</span>
                <button
                  onClick={() => togglePref(cat.key, !isOn)}
                  className={cn(
                    'w-9 h-5 rounded-full transition-colors relative',
                    isOn ? 'bg-primary' : 'bg-bg-elevated border border-border'
                  )}
                >
                  <span className={cn(
                    'absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform shadow-sm',
                    isOn ? 'left-[18px]' : 'left-0.5'
                  )} />
                </button>
              </div>
            )
          })
        )}

        {/* Test Button */}
        <button
          onClick={handleTest}
          disabled={testing}
          className="w-full mt-2 flex items-center justify-center gap-1.5 py-2 rounded-lg
            bg-bg-elevated border border-border text-[11px] font-medium text-text-secondary
            hover:border-border-hover hover:text-text-primary transition-colors
            disabled:opacity-50"
        >
          <Send className="w-3.5 h-3.5" />
          {testing ? 'Sending...' : 'Send Test Message'}
        </button>
      </div>
    </div>
  )
}
