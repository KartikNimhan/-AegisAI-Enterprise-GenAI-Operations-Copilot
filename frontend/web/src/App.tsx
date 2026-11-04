import { Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { AdminOnly } from './auth/AdminOnly'
import { AppShell } from './components/Shell/AppShell'
import { ConversationsPage } from './pages/ConversationsPage'
import { CopilotPage } from './pages/CopilotPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { DocumentViewerPage } from './pages/DocumentViewerPage'
import { MemoryPage } from './pages/MemoryPage'
import { OperationsPage } from './pages/OperationsPage'
import { OverviewPage } from './pages/OverviewPage'
import { SystemStatusPage } from './pages/SystemStatusPage'

const PAGE_TITLE: Record<string, string> = {
  '/': 'Copilot',
  '/overview': 'Overview',
  '/conversations': 'Conversations',
  '/documents': 'Documents',
  '/memory': 'Memory',
  '/operations': 'Operations',
  '/system': 'System Status',
}

/** `/?conversation=<id>` opens a saved conversation to continue it. */
function CopilotRoute() {
  const [params] = useSearchParams()
  const id = params.get('conversation') ?? undefined
  return <CopilotPage key={id ?? 'new'} initialConversationId={id} />
}

export function App() {
  const location = useLocation()
  const title =
    PAGE_TITLE[location.pathname] ?? (location.pathname.startsWith('/documents/') ? 'Document' : 'AegisAI')

  return (
    <AppShell title={title}>
      <Routes>
        <Route path="/" element={<CopilotRoute />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/conversations" element={<ConversationsPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentViewerPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/operations" element={<OperationsPage />} />
        <Route
          path="/system"
          element={
            <AdminOnly>
              <SystemStatusPage />
            </AdminOnly>
          }
        />
      </Routes>
    </AppShell>
  )
}
