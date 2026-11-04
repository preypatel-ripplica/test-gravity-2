import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientExampleScripts() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()

  const [scripts, setScripts] = useState([''])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await api.getExampleScripts(token, clientId)
        if (cancelled) return
        const rows = Array.isArray(data?.scripts) ? data.scripts.filter((row) => String(row || '').trim()) : []
        setScripts(rows.length ? rows : [''])
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

  function updateScript(index, value) {
    setScripts((prev) => prev.map((row, i) => (i === index ? value : row)))
  }

  function addScript() {
    setScripts((prev) => [...prev, ''])
  }

  function removeScript(index) {
    setScripts((prev) => {
      const next = prev.filter((_, i) => i !== index)
      return next.length ? next : ['']
    })
  }

  async function handleSave(e) {
    e?.preventDefault?.()
    if (!token || !clientId) return
    setSaving(true)
    try {
      const data = await api.saveExampleScripts(token, clientId, scripts)
      const rows = Array.isArray(data?.scripts) ? data.scripts.filter((row) => String(row || '').trim()) : []
      setScripts(rows.length ? rows : [''])
      toast('Script references saved', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <ProfileTabs clientId={clientId} />

      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Generated script references' },
            ]}
          />
          <h1>Generated script references</h1>
          <p>Optional. Paste scripts you like so new ones can follow the same voice. Generate scripts uses these as examples.</p>
        </div>
        <div className="header-actions">
          {saving && <span className="text-muted">Saving…</span>}
          <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving || loading}>
            Save
          </button>
        </div>
      </header>

      {loading ? (
        <p className="text-muted">Loading script references…</p>
      ) : (
        <form className="card example-scripts-card animate-fade-in" onSubmit={handleSave}>
          <div className="example-scripts-list">
            {scripts.map((script, index) => (
              <div key={index} className="example-script-block">
                <div className="example-script-head">
                  <label className="example-script-label" htmlFor={`example-script-${index}`}>
                    Script {index + 1}
                  </label>
                  <button
                    type="button"
                    className="doctor-ref-field-edit danger"
                    title="Delete"
                    onClick={() => removeScript(index)}
                  >
                    <i className="fa-solid fa-trash" />
                  </button>
                </div>
                <textarea
                  id={`example-script-${index}`}
                  className="form-control"
                  rows={8}
                  value={script}
                  onChange={(e) => updateScript(index, e.target.value)}
                  placeholder="Paste a spoken script you already like…"
                />
              </div>
            ))}
          </div>
          <button type="button" className="example-scripts-add" onClick={addScript} title="Add script">
            <i className="fa-solid fa-plus" />
          </button>
        </form>
      )}
    </>
  )
}
