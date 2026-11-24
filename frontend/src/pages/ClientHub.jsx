import { Link, useParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import { hasStaticDeliverable, hasVideoDeliverable } from '../components/tracker/trackerUtils'
import { useAuth } from '../context/AuthContext'
import { DOMAINS, hasDomainAccess, hasTrackerAccess } from '../utils/access'

export default function ClientHub() {
  const { clientId } = useParams()
  const { user } = useAuth()
  const client = (user?.clients || []).find((c) => c.id === clientId)
  const showVideos =
    hasDomainAccess(client, DOMAINS.VIDEOS) && hasVideoDeliverable(client?.tracker_deliverables)
  const showStatics =
    hasDomainAccess(client, DOMAINS.SOCIALMEDIA) &&
    hasStaticDeliverable(client?.tracker_deliverables)
  const showWebsite = hasDomainAccess(client, DOMAINS.WEBSITE)
  const showTracker = hasTrackerAccess(client)

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs items={[{ label: 'Clients', to: '/clients' }, { label: client?.name || 'Client' }]} />
          <p className="page-kicker">Client</p>
          <h1>{client?.name || 'Client'}</h1>
          <p>Choose the workspace you want to manage.</p>
        </div>
      </header>

      <div className="workspace-grid">
        <Link to={`/clients/${clientId}/profile`} className="workspace-card card">
          <div className="workspace-card-icon profile">
            <i className="fa-solid fa-id-card" />
          </div>
          <div className="workspace-card-body">
            <h2>Client Profile</h2>
            <p>Practice details, connections, deliverables, keywords and topics, and credentials.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Profile</span>
        </Link>

        {showVideos ? (
        <Link to={`/clients/${clientId}/videos`} className="workspace-card card">
          <div className="workspace-card-icon videos">
            <i className="fa-solid fa-play" />
          </div>
          <div className="workspace-card-body">
            <h2>Videos</h2>
            <p>YouTube and Instagram analytics, video library, content planning, and reports.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Videos</span>
        </Link>
        ) : null}

        {showStatics ? (
        <Link to={`/clients/${clientId}/social`} className="workspace-card card">
          <div className="workspace-card-icon statics">
            <i className="fa-solid fa-image" />
          </div>
          <div className="workspace-card-body">
            <h2>Static Posts</h2>
            <p>Generate static posts from scripts or recommended keywords.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Static Posts</span>
        </Link>
        ) : null}

        {showTracker ? (
        <Link to={`/clients/${clientId}/tracker`} className="workspace-card card">
          <div className="workspace-card-icon tracker">
            <i className="fa-solid fa-calendar-week" />
          </div>
          <div className="workspace-card-body">
            <h2>Tracker</h2>
            <p>Weekly default trackers and custom to-do lists for this client.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Tracker</span>
        </Link>
        ) : null}

        {showWebsite ? (
        <Link to={`/clients/${clientId}/website`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-globe" />
          </div>
          <div className="workspace-card-body">
            <h2>Website</h2>
            <p>CMS collections, entries, media, and public content APIs for this client.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Website</span>
        </Link>
        ) : null}

        <Link to={`/clients/${clientId}/gbp`} className="workspace-card card">
          <div className="workspace-card-icon gbp">
            <i className="fa-solid fa-store" />
          </div>
          <div className="workspace-card-body">
            <h2>Google Business Profile</h2>
            <p>Listing, reviews, posts, photos, and search recommendations for this client.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Google Business</span>
        </Link>

        <Link to="/bot" className="workspace-card card">
          <div className="workspace-card-icon whatsapp">
            <i className="fa-brands fa-whatsapp" />
          </div>
          <div className="workspace-card-body">
            <h2>WhatsApp</h2>
            <p>Inbox, leads, templates, broadcasts, and calls.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open WhatsApp</span>
        </Link>
      </div>
    </>
  )
}
