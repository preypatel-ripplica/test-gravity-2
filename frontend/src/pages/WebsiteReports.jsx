import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import WebsiteMonthlyReportsPanel from '../components/WebsiteMonthlyReportsPanel'
import useWebsiteGscWorkspace from '../hooks/useWebsiteGscWorkspace'

export default function WebsiteReports() {
  const { client, clientId } = useOutletContext()
  const { connected, loading } = useWebsiteGscWorkspace(clientId, {
    loadPerformanceOnConnect: false,
  })

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
          <p>Generate, refine, and download monthly website performance PDFs.</p>
        </div>
        <div className="header-actions">
          <div className="connection-status-pill card">
            <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`} />
            <span>
              {loading ? 'Loading…' : connected ? 'Google connected' : 'Connect Google on Overview'}
            </span>
          </div>
        </div>
      </header>

      <WebsiteMonthlyReportsPanel clientId={clientId} connected={connected} />
    </>
  )
}
