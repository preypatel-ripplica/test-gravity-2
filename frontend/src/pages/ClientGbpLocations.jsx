import { useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientGbpLocations() {
  const { client, clientId, bundle, refreshGbp, connected, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState(null)

  const locations = bundle?.locations || []
  const selectedIds = useMemo(() => {
    if (picked) return picked
    return new Set(locations.filter((loc) => loc.selected).map((loc) => loc.location_id))
  }, [picked, locations])

  const groups = useMemo(() => {
    const map = new Map()
    for (const loc of locations) {
      const key = loc.account_title || loc.account_name || 'Account'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(loc)
    }
    return [...map.entries()]
  }, [locations])

  function toggle(id) {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setPicked(next)
  }

  async function refreshFromGoogle() {
    setBusy(true)
    try {
      await api.gbpLocationsAvailable(token, clientId)
      setPicked(null)
      await refreshGbp()
      toast('Locations refreshed from Google.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    setBusy(true)
    try {
      await api.gbpSelectLocations(token, clientId, [...selectedIds])
      setPicked(null)
      await refreshGbp()
      toast('Locations saved.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Locations"
        subtitle="Choose every clinic location this client wants managed in the app."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : loadingBundle ? (
        <p className="text-muted">Loading locations…</p>
      ) : (
        <div className="gbp-stack">
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={refreshFromGoogle} disabled={busy}>
              Refresh from Google
            </button>
            <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
              Save selection
            </button>
          </div>
          {groups.length === 0 ? (
            <section className="card profile-form">
              <p>No locations yet. Refresh from Google after the account is connected.</p>
            </section>
          ) : (
            groups.map(([account, rows]) => (
              <section key={account} className="card profile-form social-card">
                <h2>{account}</h2>
                {rows.map((loc) => (
                  <label key={loc.location_id} className="gbp-row" style={{ marginTop: 10 }}>
                    <span>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(loc.location_id)}
                        onChange={() => toggle(loc.location_id)}
                      />{' '}
                      <strong>{loc.title || loc.location_id}</strong>
                      {loc.available === false && ' (no longer on this Google account)'}
                      <div className="text-muted">{loc.address || 'No address on file'}</div>
                    </span>
                  </label>
                ))}
              </section>
            ))
          )}
        </div>
      )}
    </>
  )
}
