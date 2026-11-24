import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import BrandLockup from '../components/BrandLockup'
import ConnectionExpiryBanner from '../components/ConnectionExpiryBanner'
import { NavItem, NavSection } from '../components/NavSection'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientLayout() {
  const { clientId, channelId: activeChannelId } = useParams()
  const { token, user, logout, patchUser } = useAuth()
  const { toast } = useUI()
  const navigate = useNavigate()

  const [channels, setChannels] = useState([])
  const [loadingChannels, setLoadingChannels] = useState(true)

  const client = useMemo(
    () => (user?.clients || []).find((c) => c.id === clientId) || null,
    [user?.clients, clientId],
  )

  const activeChannel = useMemo(
    () => channels.find((c) => c.id === activeChannelId) || null,
    [channels, activeChannelId],
  )

  const loadChannels = useCallback(async () => {
    if (!token || !clientId) return []
    setLoadingChannels(true)
    try {
      const data = await api.listChannels(token, clientId)
      const list = data.channels || []
      setChannels(list)
      patchUser({
        channels: list.map((c) => ({ id: c.id, title: c.title })),
        active_client_id: clientId,
        active_channel_id: data.active_channel_id,
      })
      return list
    } catch (err) {
      toast(`Failed to load channels: ${err.message}`, 'error')
      setChannels([])
      return []
    } finally {
      setLoadingChannels(false)
    }
  }, [token, clientId, patchUser, toast])

  // Sync backend active client when URL client changes
  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false

    ;(async () => {
      try {
        if (user?.active_client_id !== clientId) {
          await api.selectClient(token, clientId)
          if (cancelled) return
        }
        if (!cancelled) await loadChannels()
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-run on client change
  }, [token, clientId])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  if (!client && user?.clients) {
    // Client id not in list — redirect
    return (
      <div className="dashboard">
        <main className="main-content">
          <div className="connect-prompt-container card">
            <h2>Client not found</h2>
            <p>This client account does not exist or you no longer have access.</p>
            <Link to="/clients" className="btn btn-primary">
              Back to Clients
            </Link>
          </div>
        </main>
      </div>
    )
  }

  const clientBase = `/clients/${clientId}`
  const base = `${clientBase}/videos`
  const inChannel = !!activeChannelId

  return (
    <div className="dashboard">
      <aside className="sidebar card">
        <div className="sidebar-header">
          <BrandLockup subtitle="Videos" />
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
            <NavItem to={clientBase} icon={<i className="fa-solid fa-arrow-left" />}>
              Client Home
            </NavItem>
          </NavSection>

          {!inChannel && (
            <NavSection title="Client">
              <NavItem to={base} end icon={<i className="fa-solid fa-chart-pie" />}>
                Analytics
              </NavItem>
              <NavItem to={`${base}/library`} icon={<i className="fa-solid fa-film" />}>
                Videos
              </NavItem>
              <NavItem to={`${base}/post`} icon={<i className="fa-solid fa-upload" />}>
                Post Video
              </NavItem>
              <NavItem to={`${base}/content-plan`} icon={<i className="fa-solid fa-lightbulb" />}>
                Content Plan
              </NavItem>
              <NavItem to={`${base}/reports`} icon={<i className="fa-solid fa-file-lines" />}>
                Reports
              </NavItem>
            </NavSection>
          )}

          {inChannel && activeChannel && (
            <NavSection title="Channel">
              <NavItem
                to={base}
                end
                icon={<i className="fa-solid fa-arrow-left" />}
              >
                Back to Client
              </NavItem>
              <NavItem
                to={`${base}/channels/${activeChannelId}`}
                end
                icon={<i className="fa-solid fa-chart-pie" />}
              >
                Overview
              </NavItem>
              <NavItem
                to={`${base}/channels/${activeChannelId}/library`}
                icon={<i className="fa-solid fa-film" />}
              >
                Videos
              </NavItem>
              <NavItem
                to={`${base}/channels/${activeChannelId}/settings`}
                icon={<i className="fa-solid fa-gear" />}
              >
                Settings
              </NavItem>
            </NavSection>
          )}

        </nav>

        <div className="sidebar-footer">
          <button type="button" className="btn btn-danger btn-block" onClick={handleLogout}>
            <i className="fa-solid fa-right-from-bracket" /> Sign out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <ConnectionExpiryBanner clientId={clientId} />
        <Outlet
          context={{
            client,
            clientId,
            channels,
            loadingChannels,
            loadChannels,
          }}
        />
      </main>
    </div>
  )
}
