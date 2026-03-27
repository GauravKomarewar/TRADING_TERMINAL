import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores'
import { useAuthCheck } from './hooks'
import AppLayout from './components/layout/AppLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import StrategiesPage from './pages/StrategiesPage'
import StrategyBuilderPage from './pages/StrategyBuilderPage'
import OrderbookPage from './pages/OrderbookPage'
import ChartsPage from './pages/ChartsPage'
import OptionChainPage from './pages/OptionChainPage'
import DiagnosticsPage from './pages/DiagnosticsPage'
import SettingsPage from './pages/SettingsPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { authenticated, checking } = useAuthStore()
  if (checking) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-bg-base">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }
  if (!authenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  useAuthCheck()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="strategy-builder" element={<StrategyBuilderPage />} />
        <Route path="orderbook" element={<OrderbookPage />} />
        <Route path="charts" element={<ChartsPage />} />
        <Route path="option-chain" element={<OptionChainPage />} />
        <Route path="diagnostics" element={<DiagnosticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
