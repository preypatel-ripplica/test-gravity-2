import { Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { StoreProvider, useStore } from './store'
import { lazyRetry } from './lib/lazy'
import ErrorBoundary from './components/ErrorBoundary'
import App from './App'
import Inbox from './pages/Inbox'
import './index.css'

const LeadsGrid = lazyRetry(() => import('./pages/LeadsGrid'))
const Broadcasts = lazyRetry(() => import('./pages/Broadcasts'))
const Templates = lazyRetry(() => import('./pages/Templates'))
const Contacts = lazyRetry(() => import('./pages/Contacts'))
const Calls = lazyRetry(() => import('./pages/Calls'))

function Gate({ feature, children }) {
  const { features, loading } = useStore()
  if (loading) return null
  return features[feature] ? children : <Navigate to="/bot/inbox" replace />
}

function IndexRedirect() {
  return <Navigate to="/bot/inbox" replace />
}

function BotShell({ children }) {
  const { theme } = useStore()
  return (
    <div className="bot-app" data-theme={theme === 'dark' ? 'dark' : 'light'}>
      {children}
    </div>
  )
}

/** WhatsApp bot CRM — same UI as auto-whatsapp/crm, mounted at /bot/* */
export default function BotRoot() {
  return (
    <ErrorBoundary>
      <StoreProvider>
        <BotShell>
          <Suspense fallback={null}>
            <Routes>
              <Route element={<App />}>
                <Route index element={<IndexRedirect />} />
                <Route path="leads" element={<Gate feature="leads"><LeadsGrid /></Gate>} />
                <Route path="inbox" element={<Inbox />} />
                <Route path="inbox/:id" element={<Inbox />} />
                <Route path="broadcasts" element={<Gate feature="campaigns"><Broadcasts /></Gate>} />
                <Route path="broadcasts/:id" element={<Gate feature="campaigns"><Broadcasts /></Gate>} />
                <Route path="templates" element={<Gate feature="templates"><Templates /></Gate>} />
                <Route path="contacts" element={<Gate feature="contacts"><Contacts /></Gate>} />
                <Route path="calls" element={<Gate feature="calls"><Calls /></Gate>} />
                <Route path="*" element={<IndexRedirect />} />
              </Route>
            </Routes>
          </Suspense>
        </BotShell>
      </StoreProvider>
    </ErrorBoundary>
  )
}
