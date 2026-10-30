import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ConnectionTabs from '../components/client-profile/ConnectionTabs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const YT_LANGUAGE_OPTIONS = [
  { key: 'hinglish', label: 'Hinglish' },
  { key: 'arabic', label: 'Arabic' },
  { key: 'russian', label: 'Russian' },
]

function emptyLangAssignments() {
  return { hinglish: [], arabic: [], russian: [] }
}

function assignmentsFromChannels(list) {
  const next = emptyLangAssignments()
  for (const ch of list || []) {
    if (next[ch.language]) next[ch.language].push(ch.id)
  }
  return next
}

function languageLabel(key) {
  return YT_LANGUAGE_OPTIONS.find((lang) => lang.key === key)?.label || ''
}

export default function ClientYoutubeConnection() {
  const { client, clientId } = useOutletContext()
  const { token, patchUser } = useAuth()
  const { toast, confirm } = useUI()

  const [channels, setChannels] = useState([])
  const [loading, setLoading] = useState(true)
  const [linking, setLinking] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [langAssignments, setLangAssignments] = useState(emptyLangAssignments)
  const [savingLanguages, setSavingLanguages] = useState(false)

  const loadChannels = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const data = await api.listChannels(token, clientId)
      const list = data.channels || []
      setChannels(list)
      patchUser({
        channels: list.map((c) => ({ id: c.id, title: c.title })),
        active_client_id: clientId,
        active_channel_id: data.active_channel_id,
      })
    } catch (err) {
      toast(`Failed to load YouTube channels: ${err.message}`, 'error')
      setChannels([])
    } finally {
      setLoading(false)
    }
  }, [token, clientId, patchUser, toast])

  useEffect(() => {
    void loadChannels()
  }, [loadChannels])

  useEffect(() => {
    setLangAssignments(assignmentsFromChannels(channels))
  }, [clientId, channels])

  async function handleLinkChannel() {
    setLinking(true)
    try {
      const data = await api.googleLogin(token, clientId)
      toast('Redirecting to Google OAuth…', 'info')
      window.location.href = data.authorization_url
    } catch (err) {
      toast(err.message, 'error')
      setLinking(false)
    }
  }

  async function handleSyncChannels() {
    if (!channels.length) {
      toast('Link a YouTube channel first, then sync to discover more channels under that account.', 'info')
      return
    }
    setSyncing(true)
    try {
      toast('Discovering channels from the linked Google account…', 'info')
      const data = await api.syncChannels(token, clientId)
      const list = data.channels || []
      setChannels(list)
      patchUser({
        channels: list.map((c) => ({ id: c.id, title: c.title })),
        active_channel_id: data.active_channel_id,
      })
      toast(`Discovered and synced ${list.length} channel(s).`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSyncing(false)
    }
  }

  async function handleDisconnectChannel(channelId) {
    const channel = channels.find((c) => c.id === channelId)
    const label = channel?.title || channelId
    const isConfirmed = await confirm({
      title: 'Unlink YouTube Channel',
      message: `Are you sure you want to unlink YouTube channel "${label}" from this client? Stats stay in the database.`,
      isDanger: true,
    })
    if (!isConfirmed) return

    try {
      const data = await api.deleteChannel(token, channelId, clientId)
      const list = data.channels || []
      setChannels(list)
      patchUser({
        channels: list.map((c) => ({ id: c.id, title: c.title })),
        active_channel_id: data.active_channel_id,
      })
      toast(`YouTube channel "${label}" unlinked.`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  function toggleChannelLanguage(langKey, channelId) {
    setLangAssignments((prev) => {
      const next = {
        hinglish: [...prev.hinglish],
        arabic: [...prev.arabic],
        russian: [...prev.russian],
      }
      if (next[langKey].includes(channelId)) {
        next[langKey] = next[langKey].filter((id) => id !== channelId)
      } else {
        for (const key of Object.keys(next)) {
          next[key] = next[key].filter((id) => id !== channelId)
        }
        next[langKey] = [...next[langKey], channelId]
      }
      return next
    })
  }

  async function handleSaveChannelLanguages() {
    setSavingLanguages(true)
    try {
      await api.setChannelLanguages(token, clientId, langAssignments)
      await loadChannels()
      toast('YouTube channel languages saved.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to save channel languages', 'error')
    } finally {
      setSavingLanguages(false)
    }
  }

  const connected = channels.length > 0

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
              { label: 'YouTube' },
            ]}
          />
          <h1>YouTube</h1>
          <p>Link this client&apos;s YouTube channels with Google sign-in.</p>
        </div>
        <div className="connection-status-pill">
          <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected
            ? `${channels.length} channel${channels.length === 1 ? '' : 's'} linked`
            : 'Not connected'}
        </div>
      </header>

      {loading ? (
        <div className="loading-overlay inline-loading">
          <div className="spinner-loader">
            <i className="fa-solid fa-spinner fa-spin" />
            <span>Loading YouTube channels…</span>
          </div>
        </div>
      ) : (
        <div className="social-settings-grid">
          <section className="card profile-form social-card">
            <div className="profile-section">
              <h2>YouTube channels</h2>
              {connected ? (
                <div className="connection-channel-list">
                  {channels.map((channel) => (
                    <div key={channel.id} className="connected-account">
                      <div className="connected-account-icon youtube">
                        <i className="fa-brands fa-youtube" />
                      </div>
                      <div className="connection-channel-meta">
                        <h3>{channel.title || channel.id}</h3>
                        <p>
                          {[
                            languageLabel(channel.language),
                            channel.subscriber_count != null && `${Number(channel.subscriber_count).toLocaleString()} subscribers`,
                            channel.video_count != null && `${Number(channel.video_count).toLocaleString()} videos`,
                          ].filter(Boolean).join(' · ') || channel.id}
                        </p>
                      </div>
                      <div className="connection-channel-actions">
                        <Link
                          to={`/clients/${clientId}/videos/channels/${channel.id}`}
                          className="btn btn-secondary btn-sm"
                        >
                          Open
                        </Link>
                        <button
                          type="button"
                          className="btn btn-danger btn-sm"
                          onClick={() => handleDisconnectChannel(channel.id)}
                        >
                          Unlink
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="profile-section-desc">
                  Link a YouTube channel with Google to populate analytics, posting, and language mapping.
                </p>
              )}
              <div className="form-actions connection-form-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleLinkChannel}
                  disabled={linking}
                >
                  <i className={`${linking ? 'fa-solid fa-spinner fa-spin' : 'fa-brands fa-youtube'}`} />
                  {connected ? 'Link another channel' : 'Link YouTube Channel'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleSyncChannels}
                  disabled={syncing || !connected}
                >
                  <i className={`fa-solid ${syncing ? 'fa-spinner fa-spin' : 'fa-arrows-rotate'}`} />
                  {syncing ? 'Syncing…' : 'Sync channels'}
                </button>
              </div>
            </div>
          </section>

          <section className="card profile-form social-card">
            <div className="profile-section">
              <h2>YouTube channels by language</h2>
              <p className="profile-section-desc">
                Tag each linked YouTube channel as Hinglish, Arabic, or Russian. A language can have
                multiple channels. Post Video uses this mapping to pick the matching metadata, thumbnail,
                and video URL.
              </p>
              {!channels.length ? (
                <p className="text-muted">Link a YouTube channel first, then assign languages here.</p>
              ) : (
                <div className="yt-lang-assign-grid">
                  {YT_LANGUAGE_OPTIONS.map((lang) => {
                    const selectedIds = langAssignments[lang.key] || []
                    const selectedCount = selectedIds.length
                    const selectedTitles = selectedIds
                      .map((id) => channels.find((ch) => ch.id === id)?.title || id)
                      .filter(Boolean)
                    return (
                      <details key={lang.key} className="yt-lang-assign-card">
                        <summary>
                          <span className="yt-lang-assign-summary-text">
                            <strong>{lang.label}</strong>
                            <small>
                              {selectedCount
                                ? `${selectedCount} selected${selectedTitles.length ? ` · ${selectedTitles.join(', ')}` : ''}`
                                : 'None selected'}
                            </small>
                          </span>
                          <i className="fa-solid fa-chevron-down yt-lang-chevron" />
                        </summary>
                        <div
                          className={`choice-list yt-lang-assign-list${channels.length > 5 ? ' is-scrollable' : ''}`}
                        >
                          {channels.map((ch) => {
                            const checked = selectedIds.includes(ch.id)
                            return (
                              <label
                                key={ch.id}
                                className={`choice-row${checked ? ' selected' : ''}`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleChannelLanguage(lang.key, ch.id)}
                                />
                                <span>
                                  <strong>{ch.title || ch.id}</strong>
                                </span>
                              </label>
                            )
                          })}
                        </div>
                      </details>
                    )
                  })}
                </div>
              )}
              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveChannelLanguages}
                  disabled={savingLanguages || !channels.length}
                >
                  {savingLanguages ? (
                    <>
                      <i className="fa-solid fa-spinner fa-spin" /> Saving…
                    </>
                  ) : (
                    <>
                      <i className="fa-solid fa-floppy-disk" /> Save channel languages
                    </>
                  )}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  )
}
