import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ConnectionTabs from '../components/client-profile/ConnectionTabs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import CustomSelect from '../components/CustomSelect'
import { YOUTUBE_LANGUAGE_OPTIONS, languageKey, languageLabel } from '../utils/youtubeLanguages'

function chipsFromClient(client, list) {
  const grouped = {}
  for (const ch of list || []) {
    if (!ch.language) continue
    grouped[ch.language] = grouped[ch.language] || []
    grouped[ch.language].push(ch.id)
  }
  const saved = Array.isArray(client?.youtube_languages) ? client.youtube_languages : []
  const keys = []
  for (const row of saved) {
    if (grouped[row.key] && !keys.includes(row.key)) keys.push(row.key)
  }
  for (const key of Object.keys(grouped)) {
    if (!keys.includes(key)) keys.push(key)
  }
  return keys.map((key) => ({
    key,
    label: saved.find((row) => row.key === key)?.label || languageLabel(key),
    channelIds: grouped[key],
  }))
}

export default function ClientYoutubeConnection() {
  const { client, clientId } = useOutletContext()
  const { token, patchUser } = useAuth()
  const { toast, confirm } = useUI()

  const [channels, setChannels] = useState([])
  const [loading, setLoading] = useState(true)
  const [linking, setLinking] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [chips, setChips] = useState([])
  const [picker, setPicker] = useState('')
  const [customLanguage, setCustomLanguage] = useState('')
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
    setChips(chipsFromClient(client, channels))
  }, [clientId, channels, client?.youtube_languages])

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

  function addChip(key, label) {
    const nextKey = languageKey(key, label)
    if (!nextKey) {
      toast('Enter a language name', 'error')
      return
    }
    setChips((prev) => (
      prev.some((row) => row.key === nextKey)
        ? prev
        : [...prev, { key: nextKey, label: languageLabel(nextKey, label), channelIds: [] }]
    ))
    setPicker('')
    setCustomLanguage('')
  }

  function toggleChipChannel(key, channelId) {
    setChips((prev) => prev.map((row) => {
      const without = row.channelIds.filter((id) => id !== channelId)
      if (row.key !== key) return { ...row, channelIds: without }
      const has = row.channelIds.includes(channelId)
      return { ...row, channelIds: has ? without : [...without, channelId] }
    }))
  }

  function removeChip(key) {
    setChips((prev) => prev.filter((row) => row.key !== key))
  }

  async function handleSaveChannelLanguages() {
    const missing = chips.find((row) => !row.channelIds.length)
    if (missing) {
      toast(`Assign at least one YouTube channel to ${missing.label}.`, 'error')
      return
    }
    setSavingLanguages(true)
    try {
      const data = await api.setChannelLanguages(token, clientId, {
        languages: chips.map((row) => ({
          key: row.key,
          label: row.label,
          channel_ids: row.channelIds,
        })),
      })
      setChannels(data.channels || [])
      toast('YouTube channel languages saved.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to save channel languages', 'error')
    } finally {
      setSavingLanguages(false)
    }
  }

  const connected = channels.length > 0

  const languageOptions = useMemo(
    () =>
      YOUTUBE_LANGUAGE_OPTIONS.filter((row) => !chips.some((chip) => chip.key === row.key)).map(
        (row) => ({ value: row.key, label: row.label }),
      ),
    [chips],
  )

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
                Pick a language, assign linked channels, then save. Hindi is stored as hinglish for posting.
              </p>
              <div className="input-group" style={{ marginBottom: 12 }}>
                <div className="topic-add-row yt-lang-add-row">
                  <CustomSelect
                    className="yt-lang-pick-select"
                    value={picker}
                    onChange={(val) => {
                      setPicker(val)
                      if (val) addChip(val, languageLabel(val))
                    }}
                    placeholder="Language"
                    ariaLabel="Language"
                    disabled={!languageOptions.length}
                    options={languageOptions}
                  />
                  <input
                    type="text"
                    value={customLanguage}
                    onChange={(e) => setCustomLanguage(e.target.value)}
                    placeholder="Custom language"
                    aria-label="Custom language"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addChip(customLanguage, customLanguage)
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => addChip(customLanguage, customLanguage)}
                    disabled={!customLanguage.trim()}
                  >
                    <i className="fa-solid fa-plus" /> Add
                  </button>
                </div>
              </div>
              {!channels.length ? (
                <p className="text-muted field-hint">Link a YouTube channel first.</p>
              ) : !chips.length ? (
                <p className="text-muted field-hint">Choose a language above, then assign channels.</p>
              ) : (
                <div className="yt-lang-assign-grid">
                  {chips.map((lang) => {
                    const selectedTitles = lang.channelIds
                      .map((id) => channels.find((ch) => ch.id === id)?.title || id)
                    return (
                      <details key={lang.key} className="yt-lang-assign-card" open>
                        <summary>
                          <span className="yt-lang-assign-summary-text">
                            <strong>{lang.label}</strong>
                            <small>
                              {lang.channelIds.length
                                ? `${lang.channelIds.length} selected · ${selectedTitles.join(', ')}`
                                : 'None selected'}
                            </small>
                          </span>
                          <button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.preventDefault(); removeChip(lang.key) }}>
                            Remove
                          </button>
                        </summary>
                        <div className={`choice-list yt-lang-assign-list${channels.length > 5 ? ' is-scrollable' : ''}`}>
                          {channels.map((ch) => {
                            const checked = lang.channelIds.includes(ch.id)
                            return (
                              <label key={ch.id} className={`choice-row${checked ? ' selected' : ''}`}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleChipChannel(lang.key, ch.id)}
                                />
                                <span><strong>{ch.title || ch.id}</strong></span>
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
