import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'

export default function WebsiteDeployment() {
  const { client, clientId } = useOutletContext()

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Website', to: `/clients/${clientId}/website` },
              { label: 'Deployment' },
            ]}
          />
          <h1>Deployment</h1>
          <p>Publish the static site to Cloudflare Pages when the pipeline is connected.</p>
        </div>
        <div className="header-actions">
          <div className="connection-status-pill card">
            <span className="status-dot disconnected" />
            <span>Pipeline not connected</span>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled
            title="Deploy not enabled yet"
          >
            <i className="fa-solid fa-rocket" /> Deploy Changes
          </button>
        </div>
      </header>

      <section className="access-panel card animate-fade-in">
        <div className="access-empty-state">
          <i className="fa-solid fa-rocket" />
          <h3>Deploy not enabled yet</h3>
          <p>
            Repo, build, and Cloudflare settings will live here. Until then, use Content API tokens
            on Overview to serve entries and media to the live site.
          </p>
          <button type="button" className="btn btn-primary" disabled title="Deploy not enabled yet">
            <i className="fa-solid fa-rocket" /> Deploy Changes
          </button>
        </div>
      </section>

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>Deployment history</h2>
            <p className="text-muted">Status, logs, and redeploys will appear after the first publish.</p>
          </div>
        </div>
        <div className="access-empty-state">
          <i className="fa-solid fa-clock-rotate-left" />
          <h3>No deployments yet</h3>
          <p>Nothing has been published from Beacon for this client.</p>
        </div>
      </section>
    </>
  )
}
