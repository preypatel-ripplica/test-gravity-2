import { NavLink } from 'react-router-dom'

export default function ProfileTabs({ clientId }) {
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
        to={`${base}/credentials`}
        className={({ isActive }) => `profile-tab ${isActive ? 'active' : ''}`}
      >
        Credentials
      </NavLink>
    </nav>
  )
}
