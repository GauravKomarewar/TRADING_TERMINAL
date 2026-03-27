import { create } from 'zustand'
import type { DashboardSnapshot, Toast, ToastType } from '../types'

// ── Dashboard Store ──
interface DashboardState {
  snapshot: DashboardSnapshot | null
  lastUpdate: number
  isLoading: boolean
  errorCount: number
  setSnapshot: (s: DashboardSnapshot) => void
  setLoading: (v: boolean) => void
  incrementError: () => void
  resetError: () => void
}

export const useDashboardStore = create<DashboardState>((set) => ({
  snapshot: null,
  lastUpdate: 0,
  isLoading: false,
  errorCount: 0,
  setSnapshot: (s) => set({ snapshot: s, lastUpdate: Date.now(), errorCount: 0 }),
  setLoading: (v) => set({ isLoading: v }),
  incrementError: () => set((state) => ({ errorCount: state.errorCount + 1 })),
  resetError: () => set({ errorCount: 0 }),
}))

// ── UI Store ──
interface UIState {
  sidebarOpen: boolean
  activeTab: string
  showActiveOnly: boolean
  posManagerMode: boolean
  toasts: Toast[]
  toggleSidebar: () => void
  setSidebarOpen: (v: boolean) => void
  setActiveTab: (t: string) => void
  setShowActiveOnly: (v: boolean) => void
  togglePosManager: () => void
  addToast: (type: ToastType, message: string, duration?: number) => void
  removeToast: (id: string) => void
}

let toastId = 0

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: false,
  activeTab: 'positions',
  showActiveOnly: false,
  posManagerMode: false,
  toasts: [],
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  setActiveTab: (t) => set({ activeTab: t }),
  setShowActiveOnly: (v) => set({ showActiveOnly: v }),
  togglePosManager: () => set((s) => ({ posManagerMode: !s.posManagerMode })),
  addToast: (type, message, duration = 4000) => {
    const id = String(++toastId)
    set((s) => ({ toasts: [...s.toasts, { id, type, message, duration }] }))
    if (duration > 0) setTimeout(() => set((s) => ({ toasts: s.toasts.filter(t => t.id !== id) })), duration)
  },
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter(t => t.id !== id) })),
}))

// ── Auth Store ──
interface AuthState {
  authenticated: boolean
  checking: boolean
  setAuthenticated: (v: boolean) => void
  setChecking: (v: boolean) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  authenticated: false,
  checking: true,
  setAuthenticated: (v) => set({ authenticated: v }),
  setChecking: (v) => set({ checking: v }),
}))
