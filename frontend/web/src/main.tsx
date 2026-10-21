import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App.tsx'
import { AuthGate } from './auth/AuthGate'
import { OidcAuthProvider } from './auth/OidcAuthProvider'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <OidcAuthProvider>
        <AuthGate>
          <App />
        </AuthGate>
      </OidcAuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
