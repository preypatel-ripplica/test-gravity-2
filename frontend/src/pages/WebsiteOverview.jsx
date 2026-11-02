import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteOverview() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast, prompt, confirm } = useUI()
  const [apiKeys, setApiKeys] = useState([])
  const [newToken, setNewToken] = useState(null)
  const [collectionCount, setCollectionCount] = useState(null)
  const [mediaCount, setMediaCount] = useState(null)
  const [entryCount, setEntryCount] = useState(null)
  const [loading, setLoading] = useState(true)

  const base = `/clients/${clientId}/website`

  const load = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const [keys, cols, media] = await Promise.all([
        api.listWebsiteApiTokens(token, clientId),
        api.listWebsiteCollections(token, clientId),
        api.listWebsiteMedia(token, clientId),
      ])
      const collections = cols.collections || []
      setApiKeys(keys.api_keys || [])
      setCollectionCount(collections.length)
      setMediaCount((media.media || []).length)
      setEntryCount(
        collections.reduce((sum, col) => sum + (Number(col.entry_count) || 0), 0),
      )
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast])

  useEffect(() => {
    load()
  }, [load])

  async function createToken() {
    const name = await prompt({
      title: 'API token name',
      placeholder: 'Production website',
      defaultValue: 'Production website',
    })
    if (name == null) return
    try {
      const created = await api.createWebsiteApiToken(
        token,
        clientId,
        name.trim() || 'Production website',
      )
      setNewToken(created.token)
      toast('API token created — copy it now; it will not be shown again.', 'success')
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function revokeToken(key) {
    const ok = await confirm({
      title: 'Revoke token?',
      message: `"${key.name}" will stop working immediately for any live site using it.`,
      isDanger: true,
    })
    if (!ok) return
    try {
      await api.revokeWebsiteApiToken(token, clientId, key.id)
      toast('Token revoked', 'success')
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const activeTokens = apiKeys.filter((k) => k.is_active)

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Website' },
            ]}
          />
          <h1>Overview</h1>
          <p>Content workspace for this client’s website — collections, entries, media, and API access.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn btn-primary" onClick={createToken}>
            <i className="fa-solid fa-key" /> Create API token
          </button>
        </div>
      </header>

      <div className="stats-grid" style={{ marginBottom: 24 }}>
        <div className="stat-card card">
          <div className="stat-card-header">
            <span className="stat-label">Collections</span>
          </div>
          <div className="stat-value">{loading ? '—' : collectionCount ?? '—'}</div>
        </div>
        <div className="stat-card card">
          <div className="stat-card-header">
            <span className="stat-label">Entries</span>
          </div>
          <div className="stat-value">{loading ? '—' : entryCount ?? '—'}</div>
        </div>
        <div className="stat-card card">
          <div className="stat-card-header">
            <span className="stat-label">Media</span>
          </div>
          <div className="stat-value">{loading ? '—' : mediaCount ?? '—'}</div>
        </div>
        <div className="stat-card card">
          <div className="stat-card-header">
            <span className="stat-label">API tokens</span>
          </div>
          <div className="stat-value">{loading ? '—' : activeTokens.length}</div>
        </div>
      </div>

      <div className="workspace-grid" style={{ marginBottom: 24 }}>
        <Link to={`${base}/collections`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-layer-group" />
          </div>
          <div className="workspace-card-body">
            <h2>Collections</h2>
            <p>Content types and schemas for blogs, treatments, and pages.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open</span>
        </Link>
        <Link to={`${base}/entries`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-book-open" />
          </div>
          <div className="workspace-card-body">
            <h2>Entries</h2>
            <p>Create and edit published content for each collection.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open</span>
        </Link>
        <Link to={`${base}/media`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-images" />
          </div>
          <div className="workspace-card-body">
            <h2>Media</h2>
            <p>Image and file library used by entry media fields.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open</span>
        </Link>
        <Link to={`${base}/reports`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-chart-line" />
          </div>
          <div className="workspace-card-body">
            <h2>Reports</h2>
            <p>SEO and site-health snapshots — coming soon.</p>
          </div>
          <span className="btn btn-secondary btn-sm">View</span>
        </Link>
      </div>

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>Content API tokens</h2>
            <p className="text-muted">
              Bearer tokens for public <code>website.content.*</code> reads from the live site.
            </p>
          </div>
        </div>

        {newToken ? (
          <div className="cms-token-reveal">
            <strong>Copy this token now</strong>
            <code>{newToken}</code>
            <span className="text-muted">It will not be shown again. Store it in the site env.</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setNewToken(null)}>
              Dismiss
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="inline-loading">
            <i className="fa-solid fa-spinner fa-spin" /> Loading tokens…
          </div>
        ) : activeTokens.length === 0 ? (
          <div className="access-empty-state">
            <i className="fa-solid fa-key" />
            <h3>No active tokens</h3>
            <p>Create a token when the website needs to fetch collections or entries.</p>
            <button type="button" className="btn btn-primary" onClick={createToken}>
              <i className="fa-solid fa-key" /> Create API token
            </button>
          </div>
        ) : (
          <div className="cms-token-list">
            {apiKeys.map((key) => (
              <article key={key.id} className={`cms-token-row ${key.is_active ? '' : 'is-revoked'}`}>
                <div className="cms-token-main">
                  <strong>{key.name}</strong>
                  <span className="text-muted">
                    {key.key_prefix}… · {(key.scopes || []).join(', ') || 'content:read'}
                  </span>
                </div>
                <span className={`access-pill ${key.is_active ? '' : 'access-pill-muted'}`}>
                  {key.is_active ? 'Active' : 'Revoked'}
                </span>
                {key.is_active ? (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => revokeToken(key)}>
                    Revoke
                  </button>
                ) : (
                  <span />
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
