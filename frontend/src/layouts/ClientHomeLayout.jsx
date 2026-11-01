import { useEffect, useMemo } from 'react'
import { Outlet, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import { NavItem, NavSection } from '../components/NavSection'
import { hasStaticDeliverable, hasVideoDeliverable } from '../components/tracker/trackerUtils'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import { DOMAINS, hasDomainAccess } from '../utils/access'

export default function ClientHomeLayout() {
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

  const base = `/clients/${clientId}`
  const showVideos =
    hasDomainAccess(client, DOMAINS.VIDEOS) && hasVideoDeliverable(client?.tracker_deliverables)
  const showStatics =
    hasDomainAccess(client, DOMAINS.SOCIALMEDIA) &&
    hasStaticDeliverable(client?.tracker_deliverables)
  const showWebsite = hasDomainAccess(client, DOMAINS.WEBSITE)

  return (
    <div className="dashboard">
      <aside className="sidebar card">
        <div className="sidebar-header">
          <div className="brand-logo">
            <i className="fa-solid fa-building brand-icon" />
            <h3>{client?.name || 'Client'}</h3>
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
            <NavItem to="/clients" end icon={<i className="fa-solid fa-arrow-left" />}>
              All Clients
            </NavItem>
          </NavSection>

          <NavSection title="Workspace">
            <NavItem to={`${base}/profile`} icon={<i className="fa-solid fa-id-card" />}>
              Profile
            </NavItem>
            {showVideos ? (
              <NavItem to={`${base}/videos`} icon={<i className="fa-brands fa-youtube" />}>
                Videos
              </NavItem>
            ) : null}
            {showStatics ? (
              <NavItem to={`${base}/social`} icon={<i className="fa-brands fa-instagram" />}>
                Static Posts
              </NavItem>
            ) : null}
            <NavItem to={`${base}/tracker`} icon={<i className="fa-solid fa-calendar-week" />}>
              Tracker
            </NavItem>
            {showWebsite ? (
              <NavItem to={`${base}/website`} icon={<i className="fa-solid fa-globe" />}>
                Website
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
