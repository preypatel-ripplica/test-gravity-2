import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2)
}

export default function WebsiteEntries() {
  const { client, clientId } = useOutletContext()
  const { collectionId } = useParams()
  const { token } = useAuth()
  const { toast } = useUI()
  const [collection, setCollection] = useState(null)
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [schemaJson, setSchemaJson] = useState('{}')
  const [aiContextJson, setAiContextJson] = useState('{}')
  const [draftJson, setDraftJson] = useState('{\n  "title": ""\n}')
  const [status, setStatus] = useState('draft')
  const [editingId, setEditingId] = useState(null)
  const [promptText, setPromptText] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!token || !clientId || !collectionId) return
    setLoading(true)
    try {
      const [col, list] = await Promise.all([
        api.getWebsiteCollection(token, clientId, collectionId),
        api.listWebsiteEntries(token, clientId, collectionId),
      ])
      setCollection(col)
      setEntries(list.entries || [])
      const schema = col?.schema || col?.entry_schema || {}
      setSchemaJson(pretty(schema))
      setAiContextJson(pretty(col?.ai_context || {}))
      if (!editingId) {
        setDraftJson(pretty(schema))
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, collectionId, toast, editingId])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, clientId, collectionId])

  async function saveSchema() {
    let schema
    let ai_context
    try {
      schema = JSON.parse(schemaJson)
      ai_context = JSON.parse(aiContextJson)
    } catch {
      toast('Schema / AI context JSON is invalid', 'error')
      return
    }
    try {
      const col = await api.updateWebsiteCollection(token, clientId, collectionId, {
        schema,
        ai_context,
      })
      setCollection(col)
      toast('Collection schema saved', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function handleGenerate() {
    setBusy(true)
    try {
      const result = await api.generateWebsiteEntry(token, clientId, collectionId, promptText)
      setDraftJson(pretty(result.entry || {}))
      if (result.notes) toast(result.notes, result.model ? 'success' : 'info')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function handleSave() {
    let entry
    try {
      entry = JSON.parse(draftJson)
    } catch {
      toast('Entry JSON is invalid', 'error')
      return
    }
    setBusy(true)
    try {
      if (editingId) {
        await api.updateWebsiteEntry(token, clientId, editingId, { entry, status })
        toast('Entry updated', 'success')
      } else {
        await api.createWebsiteEntry(token, clientId, collectionId, { entry, status })
        toast('Entry created', 'success')
      }
      setEditingId(null)
      setStatus('draft')
      const schema = collection?.schema || collection?.entry_schema || { title: '' }
      setDraftJson(pretty(schema))
      load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  function startEdit(entryDoc) {
    setEditingId(entryDoc.id)
    setStatus(entryDoc.status || 'draft')
    setDraftJson(pretty(entryDoc.entry || entryDoc.data || {}))
  }

  async function handleDelete(entryDoc) {
    if (!window.confirm('Delete this entry?')) return
    try {
      await api.deleteWebsiteEntry(token, clientId, entryDoc.id)
      toast('Entry deleted', 'success')
      if (editingId === entryDoc.id) setEditingId(null)
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  if (loading) return <p className="text-muted">Loading…</p>

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Website', to: `/clients/${clientId}/website` },
              { label: 'Collections', to: `/clients/${clientId}/website/collections` },
              { label: collection?.name || 'Entries' },
            ]}
          />
          <h1>{collection?.name || 'Entries'}</h1>
          <p>
            Schema-driven entries for <code>/{collection?.slug}</code>
          </p>
        </div>
      </header>

      <section className="card profile-section" style={{ marginBottom: 24 }}>
        <h2>Collection schema</h2>
        <p className="text-muted">Edit the entry template (CMS_NEW <code>schema</code>). Media fields use media_id / src / alt.</p>
        <div className="input-group">
          <label htmlFor="schema-json">Schema JSON</label>
          <textarea
            id="schema-json"
            rows={10}
            value={schemaJson}
            onChange={(e) => setSchemaJson(e.target.value)}
            style={{ fontFamily: 'ui-monospace, monospace', width: '100%' }}
          />
        </div>
        <div className="input-group">
          <label htmlFor="ai-context-json">AI context JSON</label>
          <textarea
            id="ai-context-json"
            rows={4}
            value={aiContextJson}
            onChange={(e) => setAiContextJson(e.target.value)}
            style={{ fontFamily: 'ui-monospace, monospace', width: '100%' }}
          />
        </div>
        <button type="button" className="btn btn-primary" onClick={saveSchema}>
          Save schema
        </button>
      </section>

      <div className="profile-form" style={{ display: 'grid', gap: '1.5rem', gridTemplateColumns: '1fr 1fr' }}>
        <section className="card profile-section">
          <h2>{editingId ? 'Edit entry' : 'New entry'}</h2>
          <div className="input-group">
            <label htmlFor="gen-prompt">Generate prompt</label>
            <input
              id="gen-prompt"
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              placeholder="Optional topic / brief for AI draft"
            />
          </div>
          <button type="button" className="btn btn-secondary" onClick={handleGenerate} disabled={busy} style={{ marginBottom: 12 }}>
            <i className="fa-solid fa-wand-magic-sparkles" /> Generate draft
          </button>
          <div className="input-group">
            <label htmlFor="entry-status">Status</label>
            <select id="entry-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="draft">draft</option>
              <option value="published">published</option>
              <option value="archived">archived</option>
            </select>
          </div>
          <div className="input-group">
            <label htmlFor="entry-json">Entry JSON</label>
            <textarea
              id="entry-json"
              rows={16}
              value={draftJson}
              onChange={(e) => setDraftJson(e.target.value)}
              style={{ fontFamily: 'ui-monospace, monospace', width: '100%' }}
            />
          </div>
          <div className="profile-form-actions">
            <button type="button" className="btn btn-primary" onClick={handleSave} disabled={busy}>
              {editingId ? 'Update entry' : 'Create entry'}
            </button>
            {editingId ? (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setEditingId(null)
                  setStatus('draft')
                  setDraftJson(pretty(collection?.schema || collection?.entry_schema || { title: '' }))
                }}
              >
                Cancel edit
              </button>
            ) : null}
          </div>
        </section>

        <section className="card profile-section">
          <h2>Entries ({entries.length})</h2>
          {entries.length === 0 ? (
            <p className="text-muted">No entries yet.</p>
          ) : (
            <ul className="profile-topics">
              {entries.map((entryDoc) => {
                const payload = entryDoc.entry || entryDoc.data || {}
                const title = payload.title || payload.slug || entryDoc.id.slice(0, 12)
                return (
                  <li key={entryDoc.id}>
                    <strong>{title}</strong>
                    <span className="text-muted"> · {entryDoc.status}</span>
                    <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                      <button type="button" className="btn btn-sm btn-primary" onClick={() => startEdit(entryDoc)}>
                        Edit
                      </button>
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => handleDelete(entryDoc)}>
                        Delete
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          <p style={{ marginTop: 16 }}>
            <Link to={`/clients/${clientId}/website/collections`}>← Back to collections</Link>
          </p>
        </section>
      </div>
    </>
  )
}
