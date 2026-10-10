import { Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/Shell/AppShell'
import { CopilotPage } from './pages/CopilotPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { OperationsPage } from './pages/OperationsPage'
import { SystemStatusPage } from './pages/SystemStatusPage'

const PAGE_TITLE: Record<string, string> = {
  '/': 'Copilot',
  '/documents': 'Documents',
  '/operations': 'Operations',
  '/system': 'System Status',
}

export function App() {
  const location = useLocation()
  const title = PAGE_TITLE[location.pathname] ?? 'AegisAI'

  return (
    <AppShell title={title}>
      <Routes>
        <Route path="/" element={<CopilotPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/operations" element={<OperationsPage />} />
        <Route path="/system" element={<SystemStatusPage />} />
      </Routes>
    </AppShell>
  )
}
