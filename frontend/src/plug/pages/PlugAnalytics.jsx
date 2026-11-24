import { useEffect, useState } from 'react'
import { useUI } from '../../context/UIContext'
import plugApi from '../api'
import { usePlugAuth } from '../AuthContext'
import PlugPageHeader from '../components/PlugPageHeader'
import InstagramAnalyticsDashboard from '../../components/InstagramAnalyticsDashboard'

export default function PlugAnalytics() {
  const { token, creator, patchCreator } = usePlugAuth()
  const { toast } = useUI()
  const [connecting, setConnecting] = useState(false)

  const [appId, setAppId] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [redirectUri, setRedirectUri] = useState('')
  const [savingConfig, setSavingConfig] = useState(false)
  const [configSaved, setConfigSaved] = useState(false)
  const [connectError, setConnectError] = useState('')

  const connected = Boolean(creator?.instagram_connected)

  useEffect(() => {
    if (!token || connected) return
    let cancelled = false
    ;(async () => {
      try {
        const conf = await plugApi.getInstagramConfig(token)
        if (!cancelled && conf.app_id) {
          setAppId(conf.app_id)
          setAppSecret(conf.app_secret)
          if (conf.redirect_uri) setRedirectUri(conf.redirect_uri)
          setConfigSaved(true)
        } else if (!cancelled && conf.redirect_uri) {
          setRedirectUri(conf.redirect_uri)
        }
      } catch {
        // Ignore
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, connected])

  async function handleSaveConfig(e) {
    e.preventDefault()
    setSavingConfig(true)
    setConnectError('')
    try {
      const res = await plugApi.saveInstagramConfig(token, { app_id: appId, app_secret: appSecret })
      if (res.redirect_uri) setRedirectUri(res.redirect_uri)
      setConfigSaved(true)
      toast('Instagram app configuration saved!', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingConfig(false)
    }
  }

  async function handleConnect() {
    if (!configSaved) {
      setConnectError('Please save configuration first')
      return
    }
    setConnectError('')
    setConnecting(true)
    try {
      const resp = await plugApi.getInstagramConnectUrl(token)
      window.location.href = resp.authorization_url
    } catch (err) {
      toast(err.message, 'error')
      setConnecting(false)
    }
  }

  async function handleDisconnect() {
    setConnecting(true)
    try {
      const updated = await plugApi.disconnectInstagram(token)
      patchCreator(updated)
      toast('Instagram disconnected', 'info')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setConnecting(false)
    }
  }

  if (!connected) {
    return (
      <div className="plug-page animate-fade-in">
        <PlugPageHeader
          kicker="Discovery"
          title="Analytics"
          subtitle="Only Instagram is required here. Charts stay empty until that connection exists."
        />

        <div className="connect-prompt-container card plug-panel">
          <div className="prompt-illustration">
            <i className="fa-brands fa-instagram illustration-icon" />
          </div>
          <h2>Connect Instagram</h2>
          <p>
            Analytics for this workspace requires <strong>Instagram Login for Business</strong>.
            Create a Meta App, add the product, and enter the details below.
          </p>

          <form onSubmit={handleSaveConfig} className="form-group" style={{ textAlign: 'left', marginTop: 24 }}>
            <div className="input-grid">
              <label className="input-group">
                <span>Instagram App ID</span>
                <input
                  type="text"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value)}
                  required
                />
              </label>
              <label className="input-group">
                <span>Instagram App Secret</span>
                <input
                  type="password"
                  value={appSecret}
                  onChange={(e) => setAppSecret(e.target.value)}
                  required
                />
              </label>
            </div>

            <div className="callback-box" style={{ marginTop: 24, marginBottom: 24 }}>
              <div>
                <span>OAUTH CALLBACK URL</span>
                <strong>{redirectUri}</strong>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  navigator.clipboard.writeText(redirectUri)
                  toast('Redirect URI copied!', 'success')
                }}
              >
                <i className="fa-solid fa-copy" /> Copy
              </button>
            </div>

            <div className="form-actions" style={{ justifyContent: 'flex-start', alignItems: 'center', gap: '16px' }}>
              <button type="submit" className="btn btn-primary" disabled={savingConfig}>
                <i className={`fa-solid ${savingConfig ? 'fa-spinner fa-spin' : 'fa-floppy-disk'}`} />
                {savingConfig ? ' Saving...' : ' Save Configuration'}
              </button>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleConnect}
                disabled={connecting}
              >
                {connecting ? 'Redirecting...' : 'Connect Instagram'}
              </button>

              {connectError && (
                <span style={{ color: '#ef4444', fontSize: '0.85rem', fontWeight: 500 }}>
                  <i className="fa-solid fa-circle-exclamation" style={{ marginRight: '6px' }} />
                  {connectError}
                </span>
              )}
            </div>
          </form>
        </div>
      </div>
    )
  }

  return (
    <InstagramAnalyticsDashboard
      fetchAnalytics={(range) => plugApi.analytics(token, range)}
      onDisconnect={handleDisconnect}
      disconnecting={connecting}
      onLoaded={(data) => {
        patchCreator({
          instagram_connected: data.instagram_connected,
          instagram: data.instagram || creator?.instagram,
        })
      }}
    />
  )
}
