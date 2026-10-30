import { NavLink } from 'react-router-dom'

export default function ConnectionTabs({ clientId }) {
  const base = `/clients/${clientId}/profile/connections`
  return (
    <nav className="connection-tabs" aria-label="Account connections">
      <NavLink
        to={`${base}/youtube`}
        className={({ isActive }) => `connection-tab ${isActive ? 'active' : ''}`}
      >
        <i className="fa-brands fa-youtube" />
        YouTube
      </NavLink>
      <NavLink
        to={`${base}/instagram`}
        className={({ isActive }) => `connection-tab ${isActive ? 'active' : ''}`}
      >
        <i className="fa-brands fa-instagram" />
        Instagram
      </NavLink>
      <NavLink
        to={`${base}/facebook`}
        className={({ isActive }) => `connection-tab ${isActive ? 'active' : ''}`}
      >
        <i className="fa-brands fa-facebook" />
        Facebook
      </NavLink>
    </nav>
  )
}
