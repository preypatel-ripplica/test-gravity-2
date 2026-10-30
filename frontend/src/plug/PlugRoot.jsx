import { Navigate, Route, Routes } from 'react-router-dom'
import { PlugAuthProvider } from './AuthContext'
import PlugLayout, { RequirePlugAuth } from './layouts/PlugLayout'
import PlugAnalytics from './pages/PlugAnalytics'
import PlugLogin from './pages/PlugLogin'
import PlugProfile from './pages/PlugProfile'
import PlugRegister from './pages/PlugRegister'
import PlugTopics from './pages/PlugTopics'
import PlugTodos from './pages/PlugTodos'
import './plug.css'

function PlugPage({ children }) {
  return (
    <RequirePlugAuth>
      <PlugLayout>{children}</PlugLayout>
    </RequirePlugAuth>
  )
}

export default function PlugRoot() {
  return (
    <PlugAuthProvider>
      <Routes>
        <Route path="login" element={<PlugLogin />} />
        <Route path="register" element={<PlugRegister />} />
        <Route
          path="profile"
          element={
            <PlugPage>
              <PlugProfile />
            </PlugPage>
          }
        />
        <Route
          path="analytics"
          element={
            <PlugPage>
              <PlugAnalytics />
            </PlugPage>
          }
        />
        <Route
          path="topics"
          element={
            <PlugPage>
              <PlugTopics />
            </PlugPage>
          }
        />
        <Route
          path="todos"
          element={
            <PlugPage>
              <PlugTodos />
            </PlugPage>
          }
        />
        <Route index element={<Navigate to="profile" replace />} />
        <Route path="*" element={<Navigate to="login" replace />} />
      </Routes>
    </PlugAuthProvider>
  )
}
