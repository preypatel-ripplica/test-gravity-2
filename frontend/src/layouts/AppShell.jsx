import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import BrandLockup from '../components/BrandLockup'
import { useAuth } from '../context/AuthContext'

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="dashboard">
      <aside className="sidebar sidebar-compact card">
        <div className="sidebar-header">
          <BrandLockup subtitle="Internal workspace" />
        </div>

        <div className="user-profile">
          <div className="avatar">
            <i className="fa-solid fa-user" />
          </div>
          <div className="user-info">
            <h4>{user?.username || user?.email || 'User'}</h4>
            <p className="role">Internal</p>
          </div>
        </div>

        <nav className="sidebar-menu">
          <NavLink
            to="/clients"
            end
            className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
          >
            <i className="fa-solid fa-building" />
            <span>Clients</span>
          </NavLink>
          <NavLink
            to="/tracker"
            className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
          >
            <i className="fa-solid fa-calendar-week" />
            <span>Tracker</span>
          </NavLink>
          <NavLink
            to="/edit-tracker"
            className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
          >
            <i className="fa-solid fa-clapperboard" />
            <span>Edit tracker</span>
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="btn btn-danger btn-block" onClick={handleLogout}>
            <i className="fa-solid fa-right-from-bracket" /> Sign out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
