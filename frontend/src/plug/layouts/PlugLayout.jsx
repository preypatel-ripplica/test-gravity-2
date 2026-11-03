import { Navigate, useNavigate } from 'react-router-dom'
import { NavItem, NavSection } from '../../components/NavSection'
import { usePlugAuth } from '../AuthContext'
import PlugMark from '../components/PlugMark'

export default function PlugLayout({ children }) {
  const { creator, logout } = usePlugAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/plug/login', { replace: true })
  }

  const displayName = creator?.name?.trim() || creator?.username || 'Creator'
  const shortName = displayName.split(/\s+/)[0].toUpperCase()

  return (
    <div className="plug-app">
      <div className="plug-shell">
        <div className="plug-rail" aria-hidden="true" />
        <aside className="plug-sidebar">
          <div className="plug-brand">
            <PlugMark size={36} />
            <div className="plug-brand-copy">
              <h3>Plug</h3>
              <p>Grow content with consistency and discipline</p>
              <span className="plug-brand-bar" />
            </div>
          </div>

          <div className="plug-user">
            <div className="plug-avatar">
              <i className="fa-solid fa-user" />
            </div>
            <div className="plug-user-info">
              <h4>{displayName}</h4>
              <p className="role">{creator?.niche?.trim() || 'Content creator'}</p>
            </div>
          </div>

          <nav className="sidebar-menu">
            <NavSection title="Workspace">
              <NavItem to="/plug/profile" icon={<i className="fa-solid fa-id-card" />}>
                Profile
              </NavItem>
              <NavItem to="/plug/analytics" icon={<i className="fa-brands fa-instagram" />}>
                Analytics
              </NavItem>
              <NavItem to="/plug/topics" icon={<i className="fa-solid fa-lightbulb" />}>
                Topics
              </NavItem>
              <NavItem to="/plug/todos" icon={<i className="fa-solid fa-list-check" />}>
                Todos
              </NavItem>
            </NavSection>
          </nav>

          <div className="plug-sidebar-footer">
            <button type="button" className="btn btn-danger btn-block" onClick={handleLogout}>
              <i className="fa-solid fa-right-from-bracket" /> Sign out
            </button>
          </div>
        </aside>

        <div className="plug-workspace">
          <main className="plug-main">{children}</main>
          <footer className="plug-footer">PLUG &nbsp;·&nbsp; BY RIPPLICA &nbsp;·&nbsp; {shortName}</footer>
        </div>
      </div>
    </div>
  )
}

export function RequirePlugAuth({ children }) {
  const { token, creator, loading } = usePlugAuth()

  if (loading) {
    return (
      <div className="plug-app plug-auth-loading">
        <p>Loading...</p>
      </div>
    )
  }

  if (!token || !creator) {
    return <Navigate to="/plug/login" replace />
  }

  return children
}
