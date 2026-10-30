import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function WebsiteMedia() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [media, setMedia] = useState([])
  const [url, setUrl] = useState('')
  const [filename, setFilename] = useState('')
  const [alt, setAlt] = useState('')
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)

  const load = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const data = await api.listWebsiteMedia(token, clientId)
      setMedia(data.media || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast])

  useEffect(() => {
    load()
  }, [load])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!url.trim()) {
      toast('URL is required', 'error')
      return
    }
    try {
      if (editingId) {
        await api.updateWebsiteMedia(token, clientId, editingId, {
          url: url.trim(),
          filename: filename.trim(),
          alt_text: alt.trim(),
        })
        toast('Media updated', 'success')
      } else {
        await api.createWebsiteMedia(token, clientId, {
          url: url.trim(),
          filename: filename.trim(),
          alt_text: alt.trim(),
        })
        toast('Media added', 'success')
      }
      setUrl('')
      setFilename('')
      setAlt('')
      setEditingId(null)
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  function startEdit(item) {
    setEditingId(item.id)
    setUrl(item.url || '')
    setFilename(item.filename || '')
    setAlt(item.alt_text || '')
  }

  async function handleDelete(item) {
    if (!window.confirm('Remove this media item?')) return
    try {
      await api.deleteWebsiteMedia(token, clientId, item.id)
      toast('Media removed', 'success')
      if (editingId === item.id) {
        setEditingId(null)
        setUrl('')
        setFilename('')
        setAlt('')
      }
      load()
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
              { label: 'Website', to: `/clients/${clientId}/website` },
              { label: 'Media' },
            ]}
          />
          <h1>Media library</h1>
          <p>Register image/file URLs for website entries (media_id fields in schemas).</p>
        </div>
      </header>

      <form className="card profile-section" onSubmit={handleSubmit} style={{ marginBottom: 24 }}>
        <h2>{editingId ? 'Edit media' : 'Add media'}</h2>
        <div className="input-group">
          <label htmlFor="media-url">URL</label>
          <input id="media-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" required />
        </div>
        <div className="input-group">
          <label htmlFor="media-filename">Filename</label>
          <input id="media-filename" value={filename} onChange={(e) => setFilename(e.target.value)} />
        </div>
        <div className="input-group">
          <label htmlFor="media-alt">Alt text</label>
          <input id="media-alt" value={alt} onChange={(e) => setAlt(e.target.value)} />
        </div>
        <div className="profile-form-actions">
          <button type="submit" className="btn btn-primary">
            {editingId ? 'Update media' : 'Add media'}
          </button>
          {editingId ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setEditingId(null)
                setUrl('')
                setFilename('')
                setAlt('')
              }}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </form>

      {loading ? (
        <p className="text-muted">Loading…</p>
      ) : media.length === 0 ? (
        <p className="text-muted">No media yet.</p>
      ) : (
        <div className="clients-grid">
          {media.map((item) => (
            <div key={item.id} className="client-card card">
              <div className="client-card-body">
                <h3>{item.filename || item.id.slice(0, 10)}</h3>
                <p className="text-muted" style={{ wordBreak: 'break-all' }}>
                  <a href={item.preview_url || item.url} target="_blank" rel="noreferrer">
                    {item.url}
                  </a>
                </p>
                {item.alt_text ? <p>{item.alt_text}</p> : null}
                <p className="text-muted">
                  <code>{item.id}</code>
                </p>
              </div>
              <div className="header-actions">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => startEdit(item)}>
                  Edit
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => handleDelete(item)}>
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
