import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import CustomSelect from '../components/CustomSelect'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import {
  applyMediaFieldValue,
  detectMediaFields,
  formatMediaFieldLabel,
  getValueAtPath,
  setValueAtPath,
} from '../utils/websiteMediaFields'

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2)
}

function safeJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function resolveMediaItem(mediaItems, mediaId, fieldValue) {
  if (mediaId) {
    const hit = mediaItems.find((m) => m.id === mediaId || m.media_id === mediaId)
    if (hit) return hit
  }
  const fallbackUrl =
    (fieldValue && typeof fieldValue === 'object' && (fieldValue.src || fieldValue.url)) || ''
  if (fallbackUrl) {
    return {
      id: mediaId || '',
      url: fallbackUrl,
      preview_url: fallbackUrl,
      filename: fieldValue.filename || fieldValue.file_name || fieldValue.name || '',
      alt_text: fieldValue.alt_text || fieldValue.alt || '',
    }
  }
  return null
}

export default function WebsiteEntries() {
  const { client, clientId } = useOutletContext()
  const [searchParams, setSearchParams] = useSearchParams()
  const { token } = useAuth()
  const { toast } = useUI()
  const mediaUploadInputRef = useRef(null)

  const [collections, setCollections] = useState([])
  const [collectionId, setCollectionId] = useState(searchParams.get('collection') || '')
  const [collection, setCollection] = useState(null)
  const [entries, setEntries] = useState([])
  const [mediaItems, setMediaItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [schemaJson, setSchemaJson] = useState('{}')
  const [aiContextJson, setAiContextJson] = useState('{}')
  const [draftJson, setDraftJson] = useState('{\n  "title": ""\n}')
  const [status, setStatus] = useState('draft')
  const [editingId, setEditingId] = useState(null)
  const [promptText, setPromptText] = useState('')
  const [busy, setBusy] = useState(false)
  const [mediaPickerPath, setMediaPickerPath] = useState('')
  const [mediaUploadPath, setMediaUploadPath] = useState('')
  const [uploadingPath, setUploadingPath] = useState('')
  const [showSchema, setShowSchema] = useState(false)

  const mediaFields = useMemo(() => {
    const schema = collection?.schema || collection?.entry_schema || {}
    return detectMediaFields(schema)
  }, [collection])

  const loadCollections = useCallback(async () => {
    if (!token || !clientId) return []
    const list = await api.listWebsiteCollections(token, clientId)
    const rows = list.collections || []
    setCollections(rows)
    return rows
  }, [token, clientId])

  const loadCollectionData = useCallback(
    async (colId, { preserveDraft = false } = {}) => {
      if (!token || !clientId || !colId) {
        setCollection(null)
        setEntries([])
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        const [col, list, media] = await Promise.all([
          api.getWebsiteCollection(token, clientId, colId),
          api.listWebsiteEntries(token, clientId, colId),
          api.listWebsiteMedia(token, clientId),
        ])
        setCollection(col)
        setEntries(list.entries || [])
        setMediaItems(media.media || [])
        const schema = col?.schema || col?.entry_schema || {}
        setSchemaJson(pretty(schema))
        setAiContextJson(pretty(col?.ai_context || {}))
        if (!preserveDraft && !editingId) {
          setDraftJson(pretty(schema))
        }
      } catch (err) {
        toast(err.message, 'error')
      } finally {
        setLoading(false)
      }
    },
    [token, clientId, toast, editingId],
  )

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const rows = await loadCollections()
        if (cancelled) return
        const fromQuery = searchParams.get('collection') || ''

        let preferredId = ''
        if (!fromQuery && rows.length) {
          const ranked = [...rows].sort(
            (a, b) => (b.entry_count || 0) - (a.entry_count || 0),
          )
          preferredId = ranked[0]?.id || rows[0].id
        }

        const nextId =
          (fromQuery && rows.some((c) => c.id === fromQuery) && fromQuery) ||
          preferredId ||
          rows[0]?.id ||
          ''
        setCollectionId(nextId)
        if (nextId && fromQuery !== nextId) {
          setSearchParams({ collection: nextId }, { replace: true })
        }
        if (!rows.length) setLoading(false)
      } catch (err) {
        if (!cancelled) {
          toast(err.message, 'error')
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, clientId])

  useEffect(() => {
    if (!collectionId) {
      setLoading(false)
      setCollection(null)
      setEntries([])
      return
    }
    setEditingId(null)
    setMediaPickerPath('')
    loadCollectionData(collectionId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionId])

  function selectCollection(nextId) {
    setCollectionId(nextId)
    if (nextId) setSearchParams({ collection: nextId })
    else setSearchParams({})
  }

  function resetEditor() {
    setEditingId(null)
    setStatus('draft')
    setMediaPickerPath('')
    setMediaUploadPath('')
    setDraftJson(pretty(collection?.schema || collection?.entry_schema || { title: '' }))
  }

  async function saveSchema() {
    const schema = safeJson(schemaJson)
    const ai_context = safeJson(aiContextJson)
    if (!schema || Array.isArray(schema) || !ai_context || Array.isArray(ai_context)) {
      toast('Schema / AI context JSON must be objects', 'error')
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
    const entry = safeJson(draftJson)
    if (!entry || Array.isArray(entry)) {
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
      resetEditor()
      loadCollectionData(collectionId, { preserveDraft: false })
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
    setMediaPickerPath('')
    setMediaUploadPath('')
  }

  function assignMedia(path, media) {
    const entry = safeJson(draftJson)
    if (!entry) {
      toast('Entry JSON must be valid before assigning media', 'error')
      return
    }
    const currentValue = getValueAtPath(entry, path)
    const nextValue = applyMediaFieldValue(currentValue, media)
    setDraftJson(pretty(setValueAtPath(entry, path, nextValue)))
    setMediaPickerPath('')
    setMediaUploadPath('')
    toast('Media assigned', 'success')
  }

  function openMediaUploader(path) {
    setMediaUploadPath(path)
    setMediaPickerPath('')
    if (mediaUploadInputRef.current) {
      mediaUploadInputRef.current.value = ''
      mediaUploadInputRef.current.click()
    }
  }

  async function handleEntryMediaUpload(event) {
    const file = event.target.files?.[0]
    const targetPath = mediaUploadPath
    event.target.value = ''
    if (!file || !targetPath) return

    setUploadingPath(targetPath)
    try {
      const media = await api.uploadWebsiteMediaFile(token, clientId, file)
      setMediaItems((prev) => [media, ...prev.filter((m) => m.id !== media.id)])
      assignMedia(targetPath, media)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setUploadingPath('')
      setMediaUploadPath('')
    }
  }

  if (!loading && !collections.length) {
    return (
      <>
        <header className="content-header">
          <div className="greeting">
            <Breadcrumbs
              items={[
                { label: 'Clients', to: '/clients' },
                { label: client?.name || 'Client', to: `/clients/${clientId}` },
                { label: 'Website', to: `/clients/${clientId}/website` },
                { label: 'Entries' },
              ]}
            />
            <h1>Entries</h1>
            <p>Create and edit content for a collection.</p>
          </div>
        </header>
        <section className="access-panel card animate-fade-in">
          <div className="access-empty-state">
            <i className="fa-solid fa-book-open" />
            <h3>No collections yet</h3>
            <p>Create a collection first, then come back to add entries.</p>
            <Link className="btn btn-primary" to={`/clients/${clientId}/website/collections`}>
              Go to Collections
            </Link>
          </div>
        </section>
      </>
    )
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
              { label: 'Entries' },
            ]}
          />
          <h1>Entries</h1>
          <p>Edit drafts and published content for the selected collection.</p>
        </div>
        <div className="header-actions">
          <label className="cms-header-select">
            <span>Collection</span>
            <CustomSelect
              value={collectionId}
              ariaLabel="Collection"
              onChange={selectCollection}
              options={collections.map((col) => ({ value: col.id, label: col.name }))}
            />
          </label>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setShowSchema((v) => !v)}
          >
            <i className="fa-solid fa-code" /> {showSchema ? 'Hide schema' : 'Edit schema'}
          </button>
          {editingId ? (
            <button type="button" className="btn btn-ghost" onClick={resetEditor}>
              New entry
            </button>
          ) : null}
        </div>
      </header>

      {collection ? (
        <div className="plan-toolbar card" style={{ marginBottom: 18 }}>
          <div className="plan-toolbar-grid" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginBottom: 0 }}>
            <div>
              <span className="plan-rule-label">Collection</span>
              <strong>{collection.name}</strong>
            </div>
            <div>
              <span className="plan-rule-label">Slug</span>
              <strong>/{collection.slug || '—'}</strong>
            </div>
            <div>
              <span className="plan-rule-label">Entries</span>
              <strong>{loading ? '—' : entries.length}</strong>
            </div>
            <div>
              <span className="plan-rule-label">Media fields</span>
              <strong>{mediaFields.length}</strong>
            </div>
          </div>
        </div>
      ) : null}

      {showSchema ? (
        <section className="profile-form card animate-fade-in" style={{ maxWidth: 'none', marginBottom: 18 }}>
          <div className="profile-section">
            <h2>Collection schema</h2>
            <p className="profile-section-desc">
              Template for new entries. Media objects should include a <code>media_id</code> field.
            </p>
            <div className="cms-two-col">
              <div className="input-group">
                <label htmlFor="schema-json">Schema JSON</label>
                <textarea
                  id="schema-json"
                  rows={12}
                  value={schemaJson}
                  onChange={(e) => setSchemaJson(e.target.value)}
                  spellCheck={false}
                />
              </div>
              <div className="input-group">
                <label htmlFor="ai-context-json">AI context JSON</label>
                <textarea
                  id="ai-context-json"
                  rows={12}
                  value={aiContextJson}
                  onChange={(e) => setAiContextJson(e.target.value)}
                  spellCheck={false}
                />
              </div>
            </div>
          </div>
          <div className="profile-form-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setShowSchema(false)}>
              Close
            </button>
            <button type="button" className="btn btn-primary" onClick={saveSchema}>
              Save schema
            </button>
          </div>
        </section>
      ) : null}

      {loading ? (
        <div className="inline-loading">
          <i className="fa-solid fa-spinner fa-spin" /> Loading entries…
        </div>
      ) : (
        <div className="cms-split">
          <section className="profile-form card animate-fade-in" style={{ maxWidth: 'none' }}>
            <div className="profile-section">
              <h2>{editingId ? 'Edit entry' : 'New entry'}</h2>
              <p className="profile-section-desc">
                {editingId
                  ? 'Update the JSON payload and status, then save.'
                  : 'Generate a draft or paste entry JSON, then create.'}
              </p>

              <div className="cms-two-col">
                <div className="input-group">
                  <label htmlFor="gen-prompt">Generate prompt</label>
                  <input
                    id="gen-prompt"
                    value={promptText}
                    onChange={(e) => setPromptText(e.target.value)}
                    placeholder="Optional topic / brief"
                  />
                </div>
                <div className="input-group">
                  <label htmlFor="entry-status">Status</label>
                  <CustomSelect
                    id="entry-status"
                    value={status}
                    ariaLabel="Status"
                    onChange={setStatus}
                    options={[
                      { value: 'draft', label: 'draft' },
                      { value: 'published', label: 'published' },
                      { value: 'archived', label: 'archived' },
                    ]}
                  />
                </div>
              </div>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleGenerate}
                disabled={busy}
                style={{ marginBottom: 14, alignSelf: 'flex-start' }}
              >
                <i className="fa-solid fa-wand-magic-sparkles" /> Generate draft
              </button>

              <div className="input-group">
                <label htmlFor="entry-json">Entry JSON</label>
                <textarea
                  id="entry-json"
                  rows={16}
                  value={draftJson}
                  onChange={(e) => setDraftJson(e.target.value)}
                  spellCheck={false}
                />
              </div>

              <input
                ref={mediaUploadInputRef}
                type="file"
                accept="image/*,.png,.jpg,.jpeg,.webp,.gif,.svg"
                hidden
                onChange={handleEntryMediaUpload}
              />

              {mediaFields.length > 0 ? (
                <div className="cms-media-fields">
                  <h3>Media fields</h3>
                  <p className="text-muted">Preview, upload a new image, or pick from the library.</p>
                  {mediaFields.map((field) => {
                    const entry = safeJson(draftJson)
                    const current = entry ? getValueAtPath(entry, field.path) : null
                    const assignedId =
                      current && typeof current === 'object' ? current.media_id : null
                    const assigned = resolveMediaItem(mediaItems, assignedId, current)
                    const previewUrl = assigned?.preview_url || assigned?.url || ''
                    const isUploading = uploadingPath === field.path
                    return (
                      <div key={field.path} className="cms-media-field">
                        <div className="cms-media-field-head">
                          <strong>{formatMediaFieldLabel(field.path)}</strong>
                          <code className="text-muted">{field.path}</code>
                        </div>

                        <div className="cms-media-preview-row">
                          <div className="cms-media-preview">
                            {previewUrl ? (
                              <img src={previewUrl} alt={assigned?.alt_text || field.path} />
                            ) : (
                              <span className="cms-media-fallback">
                                <i className="fa-solid fa-image" />
                              </span>
                            )}
                          </div>
                          <div className="cms-media-preview-meta">
                            <strong>{assigned?.filename || (assignedId ? 'Assigned image' : 'No image')}</strong>
                            <p className="text-muted">
                              {assigned?.alt_text || (assignedId ? 'Ready to change' : 'Upload or pick from library')}
                            </p>
                            <div className="cms-card-actions">
                              <button
                                type="button"
                                className="btn btn-sm btn-primary"
                                disabled={isUploading || busy}
                                onClick={() => openMediaUploader(field.path)}
                              >
                                <i className="fa-solid fa-upload" />{' '}
                                {isUploading ? 'Uploading…' : 'Upload'}
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-secondary"
                                disabled={isUploading}
                                onClick={() =>
                                  setMediaPickerPath((prev) =>
                                    prev === field.path ? '' : field.path,
                                  )
                                }
                              >
                                <i className="fa-solid fa-images" />{' '}
                                {mediaPickerPath === field.path ? 'Close library' : 'Library'}
                              </button>
                            </div>
                          </div>
                        </div>

                        {mediaPickerPath === field.path ? (
                          <div className="cms-media-picker">
                            {mediaItems.length === 0 ? (
                              <p className="text-muted">
                                No media yet.{' '}
                                <Link to={`/clients/${clientId}/website/media`}>Open media page</Link>
                              </p>
                            ) : (
                              mediaItems.map((item) => {
                                const selected = item.id === assignedId
                                return (
                                  <button
                                    key={item.id}
                                    type="button"
                                    className={`cms-media-picker-item ${selected ? 'is-selected' : ''}`}
                                    onClick={() => assignMedia(field.path, item)}
                                  >
                                    {item.preview_url || item.url ? (
                                      <img
                                        src={item.preview_url || item.url}
                                        alt={item.alt_text || ''}
                                      />
                                    ) : (
                                      <span className="cms-media-fallback">
                                        <i className="fa-solid fa-file" />
                                      </span>
                                    )}
                                    <span>{item.filename || item.id.slice(0, 10)}</span>
                                  </button>
                                )
                              })
                            )}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </div>

            <div className="profile-form-actions">
              {editingId ? (
                <button type="button" className="btn btn-ghost" onClick={resetEditor}>
                  Cancel edit
                </button>
              ) : null}
              <button type="button" className="btn btn-primary" onClick={handleSave} disabled={busy}>
                {busy ? 'Saving…' : editingId ? 'Update entry' : 'Create entry'}
              </button>
            </div>
          </section>

          <section className="access-panel card animate-fade-in">
            <div className="access-panel-head">
              <div>
                <h2>Entries</h2>
                <p className="text-muted">
                  {entries.length} in {collection?.name || 'collection'}
                </p>
              </div>
            </div>

            {entries.length === 0 ? (
              <div className="access-empty-state">
                <i className="fa-solid fa-file-lines" />
                <h3>No entries yet</h3>
                <p>Create the first entry with the editor on the left.</p>
              </div>
            ) : (
              <div className="cms-entry-list">
                {entries.map((entryDoc) => {
                  const payload = entryDoc.entry || entryDoc.data || {}
                  const title = payload.title || payload.slug || entryDoc.id.slice(0, 12)
                  const selected = editingId === entryDoc.id
                  return (
                    <article
                      key={entryDoc.id}
                      className={`cms-entry-row ${selected ? 'is-selected' : ''}`}
                    >
                      <div className="cms-entry-main">
                        <strong>{title}</strong>
                        <span className={`access-pill access-pill-muted`}>{entryDoc.status}</span>
                      </div>
                      <div className="cms-card-actions">
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => startEdit(entryDoc)}
                        >
                          Edit
                        </button>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  )
}
