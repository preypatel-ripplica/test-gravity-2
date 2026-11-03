import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import CustomSelect from '../components/CustomSelect'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteCollections() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast, prompt, confirm } = useUI()
  const navigate = useNavigate()
  const [collections, setCollections] = useState([])
  const [presets, setPresets] = useState([])
  const [presetId, setPresetId] = useState('blogs')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

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
      setShowCreate(false)
      navigate(`/clients/${clientId}/website/entries?collection=${encodeURIComponent(col.id)}`)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(col) {
    const ok = await confirm({
      title: 'Delete collection?',
      message: `"${col.name}" and all of its entries will be removed.`,
      isDanger: true,
    })
    if (!ok) return
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
          <p>Content types for this site — each collection has its own schema and entries.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowCreate((v) => !v)}
          >
            <i className={`fa-solid ${showCreate ? 'fa-xmark' : 'fa-plus'}`} />
            {showCreate ? 'Cancel' : 'New collection'}
          </button>
        </div>
      </header>

      {showCreate ? (
        <form
          className="access-invite card animate-fade-in"
          onSubmit={(e) => {
            e.preventDefault()
            handleCreate()
          }}
        >
          <div className="access-invite-head">
            <h2>New collection</h2>
            <p>Pick a schema preset, then name the collection.</p>
          </div>
          <div className="access-invite-grid">
            <label className="access-invite-email">
              Schema preset
              <CustomSelect
                value={presetId}
                ariaLabel="Schema preset"
                onChange={setPresetId}
                options={presets.map((p) => ({ value: p.id, label: p.label }))}
              />
            </label>
            {activePreset ? <p className="text-muted">{activePreset.description}</p> : null}
          </div>
          <div className="access-invite-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? 'Creating…' : 'Continue'}
            </button>
          </div>
        </form>
      ) : null}

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>All collections</h2>
            <p className="text-muted">
              {loading
                ? 'Loading…'
                : `${collections.length} ${collections.length === 1 ? 'collection' : 'collections'}`}
            </p>
          </div>
        </div>

        {loading ? (
          <div className="inline-loading">
            <i className="fa-solid fa-spinner fa-spin" /> Loading collections…
          </div>
        ) : collections.length === 0 ? (
          <div className="access-empty-state">
            <i className="fa-solid fa-layer-group" />
            <h3>No collections yet</h3>
            <p>Create a content type (blogs, treatments, pages) to start adding entries.</p>
            {!showCreate ? (
              <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
                <i className="fa-solid fa-plus" /> New collection
              </button>
            ) : null}
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
                    <Link
                      to={`/clients/${clientId}/website/entries?collection=${encodeURIComponent(col.id)}`}
                    >
                      {col.name}
                    </Link>
                  </h3>
                  <p className="text-muted">/{col.slug}</p>
                </div>
                <div className="cms-card-actions">
                  <Link
                    className="btn btn-primary btn-sm"
                    to={`/clients/${clientId}/website/entries?collection=${encodeURIComponent(col.id)}`}
                  >
                    Open entries
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleDelete(col)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
