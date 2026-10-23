/**
 * Development-only visual preview of the React UI: `npm run dev`, then open
 * http://localhost:5173/preview.html
 *
 * It renders the real `App` (same pages, navigation and components) against mock data, with no
 * sign-in and no network. It is NOT part of the application:
 * - `index.html` / `main.tsx` never reference it, so the real app keeps OIDC sign-in enforced;
 * - Vite's production build bundles only what `index.html` reaches, so this file and
 *   `preview.html` are not in `dist/` (checked by `src/preview/preview.test.ts` and the build);
 * - it refuses to run unless `import.meta.env.DEV` is true and the page is on localhost.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { installPreviewApi } from './preview/mockApi'
import { previewAllowed, previewRoute } from './preview/guard'
import { PreviewApp } from './preview/PreviewApp'

const root = createRoot(document.getElementById('root')!)

if (previewAllowed(import.meta.env.DEV, window.location.hostname)) {
  // Before anything renders: from here on no request can leave the browser.
  installPreviewApi(window)
  root.render(
    <StrictMode>
      <PreviewApp initialRoute={previewRoute(window.location.search)} />
    </StrictMode>,
  )
} else {
  root.render(<p role="alert">The UI preview is only available in local development.</p>)
}
