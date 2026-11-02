import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

function looksLikeImage(url) {
  return !!url && /\.(png|jpe?g|gif|webp|svg|avif)(\?|$)/i.test(url)
}

export default function WebsiteMedia() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast, confirm } = useUI()
  const [media, setMedia] = useState([])
  const [url, setUrl] = useState('')
  const [filename, setFilename] = useState('')
  const [alt, setAlt] = useState('')
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)

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

  function resetForm() {
    setEditingId(null)
    setUrl('')
    setFilename('')
    setAlt('')
    setShowForm(false)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!url.trim()) {
      toast('URL is required', 'error')
      return
    }
    setSaving(true)
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
      resetForm()
      load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  function startEdit(item) {
    setEditingId(item.id)
    setUrl(item.url || '')
    setFilename(item.filename || '')
    setAlt(item.alt_text || '')
    setShowForm(true)
  }

  async function handleDelete(item) {
    const ok = await confirm({
      title: 'Remove media?',
      message: `"${item.filename || item.id}" will be removed from the library.`,
      isDanger: true,
    })
    if (!ok) return
    try {
      await api.deleteWebsiteMedia(token, clientId, item.id)
      toast('Media removed', 'success')
      if (editingId === item.id) resetForm()
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
          <h1>Media</h1>
          <p>Library of image and file URLs used by entry media fields.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              if (showForm && !editingId) resetForm()
              else {
                setEditingId(null)
                setUrl('')
                setFilename('')
                setAlt('')
                setShowForm(true)
              }
            }}
          >
            <i className={`fa-solid ${showForm && !editingId ? 'fa-xmark' : 'fa-plus'}`} />
            {showForm && !editingId ? 'Cancel' : 'Add media'}
          </button>
        </div>
      </header>

      {showForm ? (
        <form className="profile-form card animate-fade-in" onSubmit={handleSubmit}>
          <section className="profile-section">
            <h2>{editingId ? 'Edit media' : 'Add media'}</h2>
            <p className="profile-section-desc">
              Paste a public URL. Entries can reference this asset via <code>media_id</code>.
            </p>
            <div className="input-group">
              <label htmlFor="media-url">URL</label>
              <input
                id="media-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
                required
                autoFocus
              />
            </div>
            <div className="cms-two-col">
              <div className="input-group">
                <label htmlFor="media-filename">Filename</label>
                <input
                  id="media-filename"
                  value={filename}
                  onChange={(e) => setFilename(e.target.value)}
                />
              </div>
              <div className="input-group">
                <label htmlFor="media-alt">Alt text</label>
                <input id="media-alt" value={alt} onChange={(e) => setAlt(e.target.value)} />
              </div>
            </div>
          </section>
          <div className="profile-form-actions">
            <button type="button" className="btn btn-ghost" onClick={resetForm}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : editingId ? 'Update media' : 'Add media'}
            </button>
          </div>
        </form>
      ) : null}

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>Library</h2>
            <p className="text-muted">
              {loading
                ? 'Loading…'
                : `${media.length} ${media.length === 1 ? 'asset' : 'assets'}`}
            </p>
          </div>
        </div>

        {loading ? (
          <div className="inline-loading">
            <i className="fa-solid fa-spinner fa-spin" /> Loading media…
          </div>
        ) : media.length === 0 ? (
          <div className="access-empty-state">
            <i className="fa-solid fa-images" />
            <h3>No media yet</h3>
            <p>Add image URLs so entries can pick them for hero and gallery fields.</p>
            {!showForm ? (
              <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
                <i className="fa-solid fa-plus" /> Add media
              </button>
            ) : null}
          </div>
        ) : (
          <div className="cms-media-grid">
            {media.map((item) => {
              const preview = item.preview_url || item.url
              return (
                <article key={item.id} className="cms-media-card card">
                  <div className="cms-media-thumb">
                    {looksLikeImage(preview) ? (
                      <img src={preview} alt={item.alt_text || item.filename || ''} />
                    ) : (
                      <span className="cms-media-fallback">
                        <i className="fa-solid fa-file" />
                      </span>
                    )}
                  </div>
                  <div className="cms-media-body">
                    <h3>{item.filename || item.id.slice(0, 10)}</h3>
                    {item.alt_text ? <p className="text-muted">{item.alt_text}</p> : null}
                    <a
                      className="cms-media-url text-muted"
                      href={preview}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.url}
                    </a>
                  </div>
                  <div className="cms-card-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => startEdit(item)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleDelete(item)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>
    </>
  )
}
