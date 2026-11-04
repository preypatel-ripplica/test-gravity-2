import { NavLink, useOutletContext, useParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

export default function ProfileTabs({ clientId: clientIdProp, isOwner: isOwnerProp }) {
  const { clientId: routeClientId } = useParams()
  const outlet = useOutletContext() || {}
  const { user } = useAuth()
  const clientId = clientIdProp || outlet.clientId || routeClientId
  const client =
    outlet.client || (user?.clients || []).find((c) => c.id === clientId) || null
  const isOwner = isOwnerProp ?? Boolean(client?.is_owner)
  const base = `/clients/${clientId}/profile`
  return (
    <nav className="profile-tabs" aria-label="Client profile sections">
      <NavLink
        to={`${base}/practice`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Practice details
      </NavLink>
      <NavLink
        to={`${base}/preferences`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Preferences and behaviour
      </NavLink>
      <NavLink
        to={`${base}/deliverables`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Deliverables
      </NavLink>
      <NavLink
        to={`${base}/connections`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Connections
      </NavLink>
      <NavLink
        to={`${base}/keywords`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Keywords and topics
      </NavLink>
      <NavLink
        to={`${base}/script-references`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Generated script references
      </NavLink>
      <NavLink
        to={`${base}/credentials`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Credentials
      </NavLink>
      {isOwner ? (
        <NavLink
          to={`${base}/access`}
          className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
        >
          Access
        </NavLink>
      ) : null}
    </nav>
  )
}
