import { useCallback, useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { newProfileId } from '../components/client-profile/profileUtils'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const EMPTY_FORM = { id: '', service: '', username: '', password: '', notes: '' }

export default function ClientCredentials() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()

  const [credentials, setCredentials] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [visibleIds, setVisibleIds] = useState({})
  const [form, setForm] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  const serviceRef = useRef(null)

  const persist = useCallback(
    async (next) => {
      if (!token || !clientId) return
      setSaving(true)
      try {
        const data = await api.saveClientCredentials(token, clientId, next)
        const saved = data?.credentials?.credentials || next
        setCredentials(saved)
        return saved
      } catch (err) {
        toast(err.message, 'error')
        return null
      } finally {
        setSaving(false)
      }
    },
    [token, clientId, toast],
  )

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await api.getClientCredentials(token, clientId)
        if (cancelled) return
        setCredentials(data?.credentials?.credentials || [])
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, toast])

  useEffect(() => {
    if (form) serviceRef.current?.focus()
  }, [form])

  function toggleVisible(id) {
    setVisibleIds((current) => ({ ...current, [id]: !current[id] }))
  }

  async function copyCredential(item) {
    const text = [
      item.service && `Service: ${item.service}`,
      item.username && `Username: ${item.username}`,
      item.password && `Password: ${item.password}`,
      item.notes && `Notes: ${item.notes}`,
    ]
      .filter(Boolean)
      .join('\n')
    try {
      await navigator.clipboard.writeText(text)
      toast('Copied to clipboard', 'success')
    } catch {
      toast('Could not copy to clipboard', 'error')
    }
  }

  function openCreate() {
    setConfirmId(null)
    setForm({ ...EMPTY_FORM, id: newProfileId('cred') })
  }

  function handleFormChange(event) {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  async function handleSaveCredential(event) {
    event.preventDefault()
    const service = (form.service || '').trim()
    if (!service) return
    const payload = {
      id: form.id || newProfileId('cred'),
      service,
      username: (form.username || '').trim(),
      password: form.password || '',
      notes: (form.notes || '').trim(),
    }
    const exists = credentials.some((item) => item.id === payload.id)
    const next = exists
      ? credentials.map((item) => (item.id === payload.id ? payload : item))
      : [...credentials, payload]
    setForm(null)
    await persist(next)
  }

  async function handleDelete(id) {
    const next = credentials.filter((item) => item.id !== id)
    setConfirmId(null)
    if (form?.id === id) setForm(null)
    await persist(next)
  }

  const isNew = form && !credentials.some((item) => item.id === form.id)

  return (
    <>
      <ProfileTabs clientId={clientId} />

      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Credentials' },
            ]}
          />
          <h1>Credentials</h1>
          <p>Account access details, grouped by service.</p>
        </div>
        <div className="header-actions">
          {saving && <span className="text-muted">Saving…</span>}
          <button type="button" className="btn btn-primary" onClick={openCreate} disabled={Boolean(form) && isNew}>
            <i className="fa-solid fa-plus" /> Add credential
          </button>
        </div>
      </header>

      {loading ? (
        <p className="text-muted">Loading credentials…</p>
      ) : (
        <section className="credentials-card card">
          {isNew && (
            <form className="credentials-inline-form" onSubmit={handleSaveCredential}>
              <div className="credentials-form-grid">
                <label>
                  Service
                  <input
                    ref={serviceRef}
                    name="service"
                    type="text"
                    value={form.service}
                    onChange={handleFormChange}
                    placeholder="YouTube, Instagram, Drive…"
                    required
                  />
                </label>
                <label>
                  Username / Email
                  <input
                    name="username"
                    type="text"
                    value={form.username}
                    onChange={handleFormChange}
                    placeholder="account@example.com"
                  />
                </label>
                <label>
                  Password
                  <input
                    name="password"
                    type="text"
                    value={form.password}
                    onChange={handleFormChange}
                    placeholder="Password"
                  />
                </label>
                <label>
                  Notes
                  <input
                    name="notes"
                    type="text"
                    value={form.notes}
                    onChange={handleFormChange}
                    placeholder="Optional notes"
                  />
                </label>
              </div>
              <div className="doctor-ref-inline-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setForm(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary btn-sm">
                  Save
                </button>
              </div>
            </form>
          )}

          {credentials.length === 0 && !isNew ? (
            <p className="text-muted credentials-empty">No credentials yet. Add a service login for this client.</p>
          ) : (
            <div className="credentials-table-wrap">
              <table className="credentials-table">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Username / Email</th>
                    <th>Password</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {credentials.map((item) => {
                    const shown = Boolean(visibleIds[item.id])
                    if (form?.id === item.id) {
                      return (
                        <tr key={item.id} className="credentials-edit-row">
                          <td colSpan={4}>
                            <form className="credentials-inline-form nested" onSubmit={handleSaveCredential}>
                              <div className="credentials-form-grid">
                                <label>
                                  Service
                                  <input
                                    ref={serviceRef}
                                    name="service"
                                    type="text"
                                    value={form.service}
                                    onChange={handleFormChange}
                                    required
                                  />
                                </label>
                                <label>
                                  Username / Email
                                  <input
                                    name="username"
                                    type="text"
                                    value={form.username}
                                    onChange={handleFormChange}
                                  />
                                </label>
                                <label>
                                  Password
                                  <input
                                    name="password"
                                    type="text"
                                    value={form.password}
                                    onChange={handleFormChange}
                                  />
                                </label>
                                <label>
                                  Notes
                                  <input
                                    name="notes"
                                    type="text"
                                    value={form.notes}
                                    onChange={handleFormChange}
                                  />
                                </label>
                              </div>
                              <div className="doctor-ref-inline-actions">
                                <button type="button" className="btn btn-secondary btn-xs" onClick={() => setForm(null)}>
                                  Cancel
                                </button>
                                <button type="submit" className="btn btn-primary btn-xs">
                                  Save
                                </button>
                              </div>
                            </form>
                          </td>
                        </tr>
                      )
                    }
                    return (
                      <tr key={item.id}>
                        <td>
                          <strong>{item.service}</strong>
                          {item.notes ? <p className="credentials-notes">{item.notes}</p> : null}
                        </td>
                        <td>{item.username || <span className="text-muted">Not added yet</span>}</td>
                        <td>
                          <div className="credential-password-cell">
                            <span>{shown ? item.password || '—' : '••••••••'}</span>
                            <button
                              type="button"
                              className="doctor-ref-field-edit"
                              title={shown ? 'Hide password' : 'Show password'}
                              onClick={() => toggleVisible(item.id)}
                            >
                              <i className={`fa-solid ${shown ? 'fa-eye-slash' : 'fa-eye'}`} />
                            </button>
                          </div>
                        </td>
                        <td>
                          {confirmId === item.id ? (
                            <div className="doctor-ref-inline-actions">
                              <span className="text-muted">Delete?</span>
                              <button type="button" className="btn btn-danger btn-xs" onClick={() => handleDelete(item.id)}>
                                Yes
                              </button>
                              <button type="button" className="btn btn-secondary btn-xs" onClick={() => setConfirmId(null)}>
                                No
                              </button>
                            </div>
                          ) : (
                            <div className="credential-actions">
                              <button
                                type="button"
                                className="doctor-ref-field-edit"
                                title="Edit"
                                onClick={() => {
                                  setConfirmId(null)
                                  setForm({ ...item })
                                }}
                              >
                                <i className="fa-solid fa-pen" />
                              </button>
                              <button
                                type="button"
                                className="doctor-ref-field-edit"
                                title="Copy"
                                onClick={() => copyCredential(item)}
                              >
                                <i className="fa-solid fa-copy" />
                              </button>
                              <button
                                type="button"
                                className="doctor-ref-field-edit danger"
                                title="Delete"
                                onClick={() => setConfirmId(item.id)}
                              >
                                <i className="fa-solid fa-trash" />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  )
}
