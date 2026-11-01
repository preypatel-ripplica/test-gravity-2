import { useEffect, useMemo } from 'react'
import { Outlet, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import { NavItem, NavSection } from '../components/NavSection'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientProfileLayout() {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync only when client changes
  }, [token, clientId])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const base = `/clients/${clientId}/profile`

  return (
    <div className="dashboard">
      <aside className="sidebar card">
        <div className="sidebar-header">
          <div className="brand-logo">
            <i className="fa-solid fa-id-card brand-icon" />
            <h3>Client Profile</h3>
          </div>
        </div>

        <div className="user-profile">
          <div className="avatar">
            <i className="fa-solid fa-user" />
          </div>
          <div className="user-info">
            <h4>{user?.username || '—'}</h4>
            <p className="role">{client?.name || 'Client'}</p>
          </div>
        </div>

        <nav className="sidebar-menu">
          <NavSection>
            <NavItem to={`/clients/${clientId}`} icon={<i className="fa-solid fa-arrow-left" />}>
              Client Home
            </NavItem>
          </NavSection>

          <NavSection title="Client Profile">
            <NavItem to={`${base}/practice`} icon={<i className="fa-solid fa-user-doctor" />}>
              Practice details
            </NavItem>
            <NavItem to={`${base}/preferences`} icon={<i className="fa-solid fa-sliders" />}>
              Preferences and behaviour
            </NavItem>
            <NavItem to={`${base}/deliverables`} icon={<i className="fa-solid fa-list-check" />}>
              Deliverables
            </NavItem>
            <NavItem to={`${base}/connections`} icon={<i className="fa-solid fa-link" />}>
              Connections
            </NavItem>
            <NavItem to={`${base}/keywords`} icon={<i className="fa-solid fa-tags" />}>
              Keywords and topics
            </NavItem>
            <NavItem to={`${base}/credentials`} icon={<i className="fa-solid fa-key" />}>
              Credentials
            </NavItem>
            {client?.is_owner ? (
              <NavItem to={`${base}/access`} icon={<i className="fa-solid fa-user-shield" />}>
                Access
              </NavItem>
            ) : null}
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
