import { NavLink } from 'react-router-dom'

export default function TrackerViewSwitch({ clientId }) {
  const base = `/clients/${clientId}/tracker`
  return (
    <div className="segmented-control tracker-view-switch">
      <NavLink to={base} end className={({ isActive }) => (isActive ? 'active' : '')}>
        Default trackers
      </NavLink>
      <NavLink to={`${base}/custom`} className={({ isActive }) => (isActive ? 'active' : '')}>
        Custom trackers
      </NavLink>
    </div>
  )
}
