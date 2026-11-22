import { Link } from 'react-router-dom'
import Breadcrumbs from '../Breadcrumbs'

export function GbpHeader({ client, clientId, title, subtitle, connected, extra }) {
  return (
    <header className="content-header">
      <div className="greeting">
        <Breadcrumbs
          items={[
            { label: 'Clients', to: '/clients' },
            { label: client?.name || 'Client', to: `/clients/${clientId}` },
            { label: 'Google Business', to: `/clients/${clientId}/gbp` },
            { label: title },
          ]}
        />
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="connection-status-pill">
        <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`} />
        {connected ? 'Connected' : 'Not connected'}
        {extra}
      </div>
    </header>
  )
}

export function GbpConnectPrompt({ clientId }) {
  return (
    <section className="card profile-form social-card">
      <h2>Connect Google Business Profile</h2>
      <p className="profile-section-desc">
        Sign in with the Google account that manages this clinic. We list the Business Profile
        locations on that account — we do not search Google Maps for the business.
      </p>
      <Link className="btn btn-primary" to={`/clients/${clientId}/gbp/connection`}>
        Open connection
      </Link>
    </section>
  )
}

export function GbpPickLocation({ clientId }) {
  return (
    <section className="card profile-form social-card">
      <h2>Choose a location</h2>
      <p className="profile-section-desc">Select one or more Google Business locations to manage.</p>
      <Link className="btn btn-primary" to={`/clients/${clientId}/gbp/locations`}>
        Choose locations
      </Link>
    </section>
  )
}
