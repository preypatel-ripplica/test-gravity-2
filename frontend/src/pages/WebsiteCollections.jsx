import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteCollections() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast, prompt } = useUI()
  const navigate = useNavigate()
  const [collections, setCollections] = useState([])
  const [presets, setPresets] = useState([])
  const [presetId, setPresetId] = useState('blogs')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const [list, presetRes] = await Promise.all([
        api.listWebsiteCollections(token, clientId),
        api.listWebsiteSchemaPresets(token),
      ])
      setCollections(list.collections || [])
      const rows = presetRes.presets || []
      setPresets(rows)
      if (rows.length && !rows.find((p) => p.id === presetId)) {
        setPresetId(rows[0].id)
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast, presetId])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, clientId])

  async function handleCreate() {
    const name = await prompt({
      title: 'New collection',
      placeholder: 'e.g. Blogs, Products, Pages…',
    })
    if (!name?.trim()) return
    setCreating(true)
    try {
      const col = await api.createWebsiteCollection(token, clientId, {
        name: name.trim(),
        preset: presetId,
      })
      toast(`Collection "${col.name}" created`, 'success')
      navigate(`/clients/${clientId}/website/collections/${col.id}`)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(col) {
    if (!window.confirm(`Delete collection "${col.name}" and all its entries?`)) return
    try {
      await api.deleteWebsiteCollection(token, clientId, col.id)
      toast('Collection deleted', 'success')
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const activePreset = presets.find((p) => p.id === presetId)

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Website', to: `/clients/${clientId}/website` },
              { label: 'Collections' },
            ]}
          />
          <h1>Collections</h1>
          <p>CMS content types — schema presets from CMS_NEW (blogs, products, pages, other).</p>
        </div>
      </header>

      <section className="card profile-section" style={{ marginBottom: 24 }}>
        <h2>New collection</h2>
        <div className="input-group">
          <label htmlFor="preset">Schema preset</label>
          <select id="preset" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        {activePreset ? <p className="text-muted">{activePreset.description}</p> : null}
        <button type="button" className="btn btn-primary" onClick={handleCreate} disabled={creating}>
          <i className="fa-solid fa-plus" /> {creating ? 'Creating…' : 'Create collection'}
        </button>
      </section>

      {loading ? (
        <p className="text-muted">Loading…</p>
      ) : collections.length === 0 ? (
        <div className="connect-prompt-container card">
          <h2>No collections yet</h2>
          <p>Pick a preset above and create your first content type.</p>
        </div>
      ) : (
        <div className="clients-grid">
          {collections.map((col) => (
            <div key={col.id} className="client-card card">
              <div className="client-card-icon">
                <i className="fa-solid fa-folder" />
              </div>
              <div className="client-card-body">
                <h3>
                  <Link to={`/clients/${clientId}/website/collections/${col.id}`}>{col.name}</Link>
                </h3>
                <p className="text-muted">/{col.slug}</p>
              </div>
              <div className="header-actions">
                <Link
                  className="btn btn-primary btn-sm"
                  to={`/clients/${clientId}/website/collections/${col.id}`}
                >
                  Open
                </Link>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => handleDelete(col)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
