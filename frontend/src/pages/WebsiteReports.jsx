import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'

const PILLARS = [
  { id: 'organic', label: 'Organic Growth', hint: 'Clicks & impressions' },
  { id: 'keywords', label: 'Keywords', hint: 'Target rankings' },
  { id: 'authority', label: 'Authority', hint: 'Referring domains' },
  { id: 'health', label: 'Site Health', hint: 'Core Web Vitals' },
  { id: 'aeo', label: 'AEO', hint: 'Answer engines' },
  { id: 'conversion', label: 'Conversions', hint: 'GA4 events' },
]

export default function WebsiteReports() {
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
              { label: 'Reports' },
            ]}
          />
          <h1>Reports</h1>
          <p>SEO and site-health trackers from Search Console, Analytics, and PageSpeed.</p>
        </div>
        <div className="header-actions">
          <div className="connection-status-pill card">
            <span className="status-dot disconnected" />
            <span>Not connected</span>
          </div>
          <button type="button" className="btn btn-secondary" disabled title="Google connect is not wired yet">
            <i className="fa-brands fa-google" /> Connect Google
          </button>
          <button type="button" className="btn btn-primary" disabled title="Snapshots are not wired yet">
            <i className="fa-solid fa-arrows-rotate" /> Refresh snapshot
          </button>
        </div>
      </header>

      <div className="stats-grid" style={{ marginBottom: 24 }}>
        {PILLARS.map((pillar) => (
          <div key={pillar.id} className="stat-card card">
            <div className="stat-card-header">
              <span className="stat-label">{pillar.label}</span>
            </div>
            <div className="stat-value">—</div>
            <div className="stat-meta">{pillar.hint}</div>
          </div>
        ))}
      </div>

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>Page performance</h2>
            <p className="text-muted">Path-level clicks, sessions, and PageSpeed after the first snapshot.</p>
          </div>
        </div>
        <div className="access-empty-state">
          <i className="fa-solid fa-chart-line" />
          <h3>No report data yet</h3>
          <p>Connect Google and refresh a snapshot when SEO trackers are enabled for this workspace.</p>
        </div>
      </section>
    </>
  )
}
