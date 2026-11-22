import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpHeader } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientGbpConnection() {
  const { client, clientId, bundle, refreshGbp, connected } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [busy, setBusy] = useState(false)

  async function handleConnect() {
    setBusy(true)
    try {
      const data = await api.gbpLogin(token, clientId)
      window.location.href = data.authorization_url
    } catch (err) {
      toast(err.message, 'error')
      setBusy(false)
    }
  }

  async function handleDisconnect() {
    setBusy(true)
    try {
      await api.gbpDisconnect(token, clientId)
      await refreshGbp()
      toast('Google Business Profile disconnected.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const selected = (bundle?.locations || []).filter((loc) => loc.selected)

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Connection"
        subtitle="Connect the Google account that manages this client's Business Profiles."
        connected={connected}
      />
      <div className="gbp-stack">
        <section className="card profile-form social-card">
          <h2>Google account</h2>
          <p className="profile-section-desc">
            This uses the same Google Cloud OAuth client as YouTube, with a separate Business Profile
            permission. Add the backend callback <code>/gbp.callback</code> on that OAuth client
            (local default: http://localhost:8000/gbp.callback).
          </p>
          {connected ? (
            <div className="connected-account">
              <div className="connected-account-icon" style={{ background: '#1a73e8', color: '#fff' }}>
                <i className="fa-solid fa-store" />
              </div>
              <div>
                <h3>Connected</h3>
                <p>{selected.length} location{selected.length === 1 ? '' : 's'} selected</p>
                {bundle?.connected_at && <p>Since {new Date(bundle.connected_at).toLocaleString()}</p>}
              </div>
            </div>
          ) : (
            <p className="profile-section-desc">Not connected yet.</p>
          )}
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={handleConnect} disabled={busy}>
              <i className={`fa-solid ${busy ? 'fa-spinner fa-spin' : 'fa-store'}`} />
              {connected ? 'Reconnect' : 'Connect Google Business Profile'}
            </button>
            {connected && (
              <button type="button" className="btn btn-danger" onClick={handleDisconnect} disabled={busy}>
                Disconnect
              </button>
            )}
          </div>
        </section>
        {bundle?.status === 'expired' && (
          <p className="gbp-pending">The Google session expired. Reconnect to refresh access.</p>
        )}
      </div>
    </>
  )
}
