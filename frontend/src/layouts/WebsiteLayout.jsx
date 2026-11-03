import { useEffect, useMemo } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import BrandLockup from '../components/BrandLockup'
import { NavItem, NavSection } from '../components/NavSection'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteLayout() {
  const { clientId } = useParams()
  const { token, user, logout, patchUser } = useAuth()
  const { toast } = useUI()
  const navigate = useNavigate()

  const client = useMemo(
    () => (user?.clients || []).find((c) => c.id === clientId) || null,
    [user?.clients, clientId],
  )

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false

    ;(async () => {
      try {
        if (user?.active_client_id !== clientId) {
          await api.selectClient(token, clientId)
          if (cancelled) return
        }
        patchUser({
          active_client_id: clientId,
          active_channel_id: null,
        })
      } catch (err) {
        if (!cancelled) {
          toast(err.message, 'error')
          navigate('/clients', { replace: true })
        }
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, clientId])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const base = `/clients/${clientId}/website`

  return (
    <div className="dashboard">
      <aside className="sidebar card">
        <div className="sidebar-header">
          <BrandLockup subtitle="Website" />
        </div>

        <div className="user-profile">
          <div className="avatar">
            <i className="fa-solid fa-user" />
          </div>
          <div className="user-info">
            <h4>{user?.username || user?.email || 'User'}</h4>
            <p className="role">{client?.name || 'Client'}</p>
          </div>
        </div>

        <nav className="sidebar-menu">
          <NavSection>
            <NavItem to={`/clients/${clientId}`} icon={<i className="fa-solid fa-arrow-left" />}>
              Client Home
            </NavItem>
          </NavSection>

          <NavSection title="Website">
            <NavLink to={base} end className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
              <i className="fa-solid fa-house" />
              <span>Overview</span>
            </NavLink>
            <NavLink
              to={`${base}/collections`}
              className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
            >
              <i className="fa-solid fa-layer-group" />
              <span>Collections</span>
            </NavLink>
            <NavLink
              to={`${base}/entries`}
              className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
            >
              <i className="fa-solid fa-book-open" />
              <span>Entries</span>
            </NavLink>
            <NavLink
              to={`${base}/media`}
              className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
            >
              <i className="fa-solid fa-images" />
              <span>Media</span>
            </NavLink>
            <NavLink
              to={`${base}/reports`}
              className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
            >
              <i className="fa-solid fa-chart-line" />
              <span>Reports</span>
            </NavLink>
            <NavLink
              to={`${base}/deployment`}
              className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
            >
              <i className="fa-solid fa-rocket" />
              <span>Deployment</span>
            </NavLink>
          </NavSection>
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="btn btn-danger btn-block" onClick={handleLogout}>
            <i className="fa-solid fa-right-from-bracket" /> Sign out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet context={{ client, clientId }} />
      </main>
    </div>
  )
}
