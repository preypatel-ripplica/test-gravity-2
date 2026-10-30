import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteOverview() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast, prompt } = useUI()
  const [apiKeys, setApiKeys] = useState([])
  const [newToken, setNewToken] = useState(null)

  const loadKeys = useCallback(async () => {
    if (!token || !clientId) return
    try {
      const data = await api.listWebsiteApiTokens(token, clientId)
      setApiKeys(data.api_keys || [])
    } catch (err) {
      toast(err.message, 'error')
    }
  }, [token, clientId, toast])

  useEffect(() => {
    loadKeys()
  }, [loadKeys])

  async function createToken() {
    const name = await prompt({
      title: 'API token name',
      placeholder: 'Production website',
      defaultValue: 'Production website',
    })
    if (name == null) return
    try {
      const created = await api.createWebsiteApiToken(token, clientId, name.trim() || 'Production website')
      setNewToken(created.token)
      toast('API token created — copy it now; it will not be shown again.', 'success')
      loadKeys()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function revokeToken(key) {
    if (!window.confirm(`Revoke token "${key.name}"?`)) return
    try {
      await api.revokeWebsiteApiToken(token, clientId, key.id)
      toast('Token revoked', 'success')
      loadKeys()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

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
          <h1>Website CMS</h1>
          <p>Manage site content collections, entries, media, and public content API tokens.</p>
        </div>
      </header>

      <div className="workspace-grid">
        <Link to={`/clients/${clientId}/website/collections`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-layer-group" />
          </div>
          <div className="workspace-card-body">
            <h2>Collections</h2>
            <p>Schema presets (blogs, products, pages) and entry CRUDL.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Collections</span>
        </Link>

        <Link to={`/clients/${clientId}/website/media`} className="workspace-card card">
          <div className="workspace-card-icon website">
            <i className="fa-solid fa-images" />
          </div>
          <div className="workspace-card-body">
            <h2>Media library</h2>
            <p>URLs and metadata used by entry media fields.</p>
          </div>
          <span className="btn btn-primary btn-sm">Open Media</span>
        </Link>
      </div>

      <section className="card profile-section" style={{ marginTop: 24 }}>
        <h2>Content API tokens</h2>
        <p className="text-muted">
          Public read access for the live site: <code>website.content.*</code> with Bearer token (CMS_NEW style).
        </p>
        <button type="button" className="btn btn-primary" onClick={createToken} style={{ marginBottom: 12 }}>
          Create token
        </button>
        {newToken ? (
          <div className="connect-prompt-container" style={{ marginBottom: 16 }}>
            <p>
              <strong>New token (copy once):</strong>
            </p>
            <code style={{ wordBreak: 'break-all' }}>{newToken}</code>
          </div>
        ) : null}
        {apiKeys.length === 0 ? (
          <p className="text-muted">No tokens yet.</p>
        ) : (
          <ul className="profile-topics">
            {apiKeys.map((key) => (
              <li key={key.id}>
                <strong>{key.name}</strong>
                <span className="text-muted">
                  {' '}
                  · {key.key_prefix}… · {key.is_active ? 'active' : 'revoked'} · {(key.scopes || []).join(', ')}
                </span>
                {key.is_active ? (
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn btn-sm btn-ghost" onClick={() => revokeToken(key)}>
                      Revoke
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
