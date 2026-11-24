import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ConnectionTabs from '../components/client-profile/ConnectionTabs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import { includeFromFlags, previewColumns } from '../utils/postingMix'
import { languageKey, languageLabel } from '../utils/youtubeLanguages'

export default function ClientPostingMix() {
  const { client, clientId } = useOutletContext()
  const { token, patchUser } = useAuth()
  const { toast } = useUI()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [languages, setLanguages] = useState([])
  const [flags, setFlags] = useState({ instagram_connected: false, facebook_connected: false, youtube_ready: false })
  const [include, setInclude] = useState({ youtube: false, instagram: false, facebook: false })
  const [extras, setExtras] = useState([])
  const [extraName, setExtraName] = useState('')

  const load = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const data = await api.getPostingMix(token, clientId)
      setLanguages(data.youtube_languages || [])
      const nextFlags = {
        instagram_connected: Boolean(data.instagram_connected),
        facebook_connected: Boolean(data.facebook_connected),
        youtube_ready: Boolean(data.youtube_ready),
      }
      setFlags(nextFlags)
      const mix = data.posting_mix
      const wanted = mix?.saved
        ? mix.include
        : { youtube: true, instagram: true, facebook: true }
      setInclude(includeFromFlags(nextFlags, wanted))
      setExtras(mix?.saved ? mix.extra_platforms || [] : [])
    } catch (err) {
      toast(err.message || 'Failed to load posting mix', 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast])

  useEffect(() => { void load() }, [load])

  const canInclude = includeFromFlags(flags, include)
  const columns = useMemo(() => previewColumns(canInclude, extras), [canInclude, extras])

  function addExtra() {
    const key = languageKey(extraName, extraName)
    if (!key || ['youtube', 'instagram', 'facebook'].includes(key)) {
      toast('Enter a column name that is not YouTube, Instagram, or Facebook.', 'error')
      return
    }
    if (extras.some((row) => row.key === key)) return
    setExtras((prev) => [...prev, { key, label: languageLabel(key, extraName) }])
    setExtraName('')
  }

  async function handleSave() {
    setSaving(true)
    try {
      const data = await api.savePostingMix(token, clientId, {
        include: includeFromFlags(flags, include),
        extra_platforms: extras,
      })
      if (data.clients) {
        patchUser({
          clients: data.clients,
          active_client_id: data.active_client_id,
          active_channel_id: data.active_channel_id,
        })
      }
      toast('Posting mix saved. Every week uses this grid.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to save posting mix', 'error')
    } finally {
      setSaving(false)
    }
  }

  const rows = canInclude.youtube
    ? (languages.length ? languages : [{ key: 'all', label: '—' }])
    : [{ key: 'all', label: '—' }]

  return (
    <>
      <ProfileTabs clientId={clientId} />
      <ConnectionTabs clientId={clientId} />
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Connections' },
              { label: 'Posting mix' },
            ]}
          />
          <h1>Posting mix</h1>
          <p>This grid is what “Where it went out” shows on every week. The tracker only fills links.</p>
        </div>
      </header>
      {loading ? (
        <p className="text-muted">Loading posting mix…</p>
      ) : (
        <section className="card profile-form">
          <div className="profile-section">
            <h2>Include</h2>
            <p className="profile-section-desc">
              Turning a platform off hides its column and its posting checkbox. Saved links stay in the database and come back when you include it again.
            </p>
            <label className="choice-row">
              <input
                type="checkbox"
                checked={canInclude.youtube}
                disabled={!flags.youtube_ready}
                onChange={(e) => setInclude((prev) => ({ ...prev, youtube: e.target.checked }))}
              />
              <span>
                <strong>YouTube</strong>
                <small>{flags.youtube_ready ? ' Uses the languages saved on the YouTube tab.' : ' Add languages and channels on the YouTube tab first.'}</small>
              </span>
            </label>
            <label className="choice-row">
              <input
                type="checkbox"
                checked={canInclude.instagram}
                disabled={!flags.instagram_connected}
                onChange={(e) => setInclude((prev) => ({ ...prev, instagram: e.target.checked }))}
              />
              <span>
                <strong>Instagram</strong>
                <small>{flags.instagram_connected ? ' One cell for the whole video, not per language.' : ' Connect Instagram first.'}</small>
              </span>
            </label>
            <label className="choice-row">
              <input
                type="checkbox"
                checked={canInclude.facebook}
                disabled={!flags.facebook_connected}
                onChange={(e) => setInclude((prev) => ({ ...prev, facebook: e.target.checked }))}
              />
              <span>
                <strong>Facebook</strong>
                <small>{flags.facebook_connected ? ' One cell for the whole video, not per language.' : ' Connect Facebook first.'}</small>
              </span>
            </label>

            <h2 style={{ marginTop: 24 }}>Extra columns</h2>
            <p className="profile-section-desc">Paste-only. No login and no auto-post. You cannot remove YouTube, Instagram, or Facebook here while they are included.</p>
            <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
              <input value={extraName} onChange={(e) => setExtraName(e.target.value)} placeholder="LinkedIn" aria-label="Extra column" />
              <button type="button" className="btn btn-secondary" onClick={addExtra}>Add column</button>
            </div>
            {extras.length ? (
              <div className="connection-channel-list">
                {extras.map((row) => (
                  <div key={row.key} className="connected-account">
                    <div>
                      <strong>{row.label}</strong>
                    </div>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setExtras((prev) => prev.filter((item) => item.key !== row.key))}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            <h2 style={{ marginTop: 24 }}>Preview</h2>
            {!columns.length ? (
              <p className="text-muted">Include a platform or add a column to see the grid.</p>
            ) : (
              <div className="tracker-dest-table-wrap">
                <table className="tracker-dest-table">
                  <thead>
                    <tr>
                      <th>Language</th>
                      {columns.map((label) => <th key={label}>{label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(rows.length ? rows : [{ key: 'all', label: '—' }]).map((row, index) => (
                      <tr key={row.key}>
                        <th>{canInclude.youtube ? row.label : '—'}</th>
                        {columns.map((label) => {
                          if (index > 0 && label !== 'YouTube') return null
                          const span = index === 0 && label !== 'YouTube' && rows.length > 1 ? rows.length : undefined
                          return <td key={label} rowSpan={span}>Link</td>
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="form-actions">
              <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Save posting mix'}
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  )
}
