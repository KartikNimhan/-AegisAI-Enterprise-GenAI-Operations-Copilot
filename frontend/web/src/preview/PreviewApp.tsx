import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import { AuthStateContext, type AuthState } from '../auth/AuthContext'
import { MOCK_USER } from './mockData'

const BANNER_HEIGHT = 32

// A made-up "signed in" state, only so the top bar shows a user. It is not authentication and it
// exists only inside this page: the real app (index.html -> main.tsx) never imports this file.
const PREVIEW_AUTH: AuthState = {
  status: 'signed_in',
  user: MOCK_USER,
  message: null,
  signIn: () => undefined,
  signOut: () => undefined,
}

// The real shell is exactly one viewport tall; shrink it by the banner so the page does not scroll.
// `div.x > div` outranks the shell's single-class rule.
const FRAME_CSS = `div.aegis-preview-frame{padding-top:${BANNER_HEIGHT}px;box-sizing:border-box}
div.aegis-preview-frame > div{height:calc(100vh - ${BANNER_HEIGHT}px)}`

/** Always visible, above the real UI. Says plainly that nothing shown here is live. */
export function PreviewBanner() {
  return (
    <div
      role="note"
      aria-label="Preview mode"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: BANNER_HEIGHT,
        zIndex: 2147483647,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '0 12px',
        background: '#b45309',
        color: '#fff',
        font: '600 12px system-ui, sans-serif',
        textAlign: 'center',
        boxSizing: 'border-box',
      }}
    >
      PREVIEW — mock data. Service status is simulated and not checked: no backend, database or
      Redis is connected. Nothing is saved.
    </div>
  )
}

export function PreviewApp({ initialRoute = '/' }: { initialRoute?: string }) {
  return (
    <AuthStateContext.Provider value={PREVIEW_AUTH}>
      <style>{FRAME_CSS}</style>
      <PreviewBanner />
      <div className="aegis-preview-frame">
        <MemoryRouter initialEntries={[initialRoute]}>
          <App />
        </MemoryRouter>
      </div>
    </AuthStateContext.Provider>
  )
}
