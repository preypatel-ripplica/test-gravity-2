import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import { NavItem, NavSection } from '../components/NavSection'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function GbpLayout() {
  const { clientId } = useParams()
  const { token, user, logout, patchUser } = useAuth()
  const { toast } = useUI()
  const navigate = useNavigate()
  const [bundle, setBundle] = useState(null)
  const [loadingBundle, setLoadingBundle] = useState(true)
  const [switching, setSwitching] = useState(false)

  const client = useMemo(
    () => (user?.clients || []).find((c) => c.id === clientId) || null,
    [user?.clients, clientId],
  )

  const refreshGbp = useCallback(async () => {
    if (!token || !clientId) return null
    const data = await api.gbpConnectionGet(token, clientId)
    setBundle(data)
    return data
  }, [token, clientId])

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

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false
    setLoadingBundle(true)
    ;(async () => {
      try {
        const data = await api.gbpConnectionGet(token, clientId)
        if (!cancelled) setBundle(data)
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoadingBundle(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, toast])

  const selectedLocations = (bundle?.locations || []).filter((loc) => loc.selected)
  const activeLocation =
    selectedLocations.find((loc) => loc.location_id === bundle?.active_location_id) ||
    selectedLocations[0] ||
    null

  async function handleSwitchLocation(locationId) {
    if (!locationId || locationId === activeLocation?.location_id) return
    setSwitching(true)
    try {
      const data = await api.gbpSetActiveLocation(token, clientId, locationId)
      setBundle(data)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSwitching(false)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const base = `/clients/${clientId}/gbp`

  return (
    <div className="dashboard gbp-shell">
      <aside className="sidebar card">
        <div className="sidebar-header">
          <div className="brand-logo">
            <i className="fa-solid fa-store brand-icon" />
            <h3>Google Business</h3>
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

        {selectedLocations.length > 0 && (
          <div className="gbp-location-switch">
            <label>
              <span>Location</span>
              <select
                value={activeLocation?.location_id || ''}
                onChange={(event) => handleSwitchLocation(event.target.value)}
                disabled={switching}
              >
                {selectedLocations.map((loc) => (
                  <option key={loc.location_id} value={loc.location_id}>
                    {loc.title || loc.location_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <nav className="sidebar-menu">
          <NavSection>
            <NavItem to={`/clients/${clientId}`} end icon={<i className="fa-solid fa-arrow-left" />}>
              Client Home
            </NavItem>
          </NavSection>

          <NavSection title="Google Business">
            <NavItem to={base} end icon={<i className="fa-solid fa-chart-pie" />}>
              Overview
            </NavItem>
            <NavItem to={`${base}/optimize`} icon={<i className="fa-solid fa-wand-magic-sparkles" />}>
              Optimize
            </NavItem>
            <NavItem to={`${base}/profile`} icon={<i className="fa-solid fa-building" />}>
              Profile
            </NavItem>
            <NavItem to={`${base}/reviews`} icon={<i className="fa-solid fa-star" />}>
              Reviews
            </NavItem>
            <NavItem to={`${base}/posts`} icon={<i className="fa-solid fa-bullhorn" />}>
              Posts
            </NavItem>
            <NavItem to={`${base}/media`} icon={<i className="fa-solid fa-images" />}>
              Media
            </NavItem>
            <NavItem to={`${base}/performance`} icon={<i className="fa-solid fa-chart-line" />}>
              Performance
            </NavItem>
            <NavItem to={`${base}/locations`} icon={<i className="fa-solid fa-location-dot" />}>
              Locations
            </NavItem>
            <NavItem to={`${base}/connection`} icon={<i className="fa-solid fa-plug" />}>
              Connection
            </NavItem>
          </NavSection>
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="btn btn-danger btn-block" onClick={handleLogout}>
            <i className="fa-solid fa-right-from-bracket" /> Sign out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet
          context={{
            client,
            clientId,
            bundle,
            loadingBundle,
            refreshGbp,
            activeLocation,
            selectedLocations,
            connected: !!bundle?.connected,
          }}
        />
      </main>
    </div>
  )
}
