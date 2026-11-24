import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api'
import AnalyticsPanel from '../components/AnalyticsPanel'
import Breadcrumbs from '../components/Breadcrumbs'
import CustomSelect from '../components/CustomSelect'
import InstagramAnalyticsDashboard from '../components/InstagramAnalyticsDashboard'
import SourceSwitcher from '../components/SourceSwitcher'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import { useClientPresentation } from '../hooks/useClientPresentation'

function allYoutubeMeta(channels) {
  return {
    id: 'all',
    title: 'All Channels Consolidated',
    description: `Aggregated data for ${channels.length} YouTube channel(s).`,
    subscriber_count: channels.reduce((sum, ch) => sum + Number(ch.subscriber_count || 0), 0),
    view_count: channels.reduce((sum, ch) => sum + Number(ch.view_count || 0), 0),
    video_count: channels.reduce((sum, ch) => sum + Number(ch.video_count || 0), 0),
  }
}

export default function ClientOverview() {
  const { token } = useAuth()
  const { toast } = useUI()
  const { client, clientId, channels, loadingChannels } = useOutletContext()
  const presentation = useClientPresentation(client)
  const [source, setSource] = useState('youtube')
  const [instagramConnected, setInstagramConnected] = useState(null)
  const [instagramAccount, setInstagramAccount] = useState(null)
  const [selectedYoutubeId, setSelectedYoutubeId] = useState('all')
  const [selectedInstagramId, setSelectedInstagramId] = useState('all')

  const [channelMeta, setChannelMeta] = useState(null)
  const [loading, setLoading] = useState(false)

  const buildMeta = useCallback(async () => {
    if (!token || !clientId) return
    if (!channels?.length) {
      setChannelMeta(null)
      return
    }
    setLoading(true)
    try {
      if (selectedYoutubeId === 'all') {
        setChannelMeta(allYoutubeMeta(channels))
      } else {
        const ch = channels.find((row) => row.id === selectedYoutubeId)
        setChannelMeta(
          ch
            ? {
                id: ch.id,
                title: ch.title,
                description: ch.description || '',
                subscriber_count: Number(ch.subscriber_count || 0),
                view_count: Number(ch.view_count || 0),
                video_count: Number(ch.video_count || 0),
              }
            : allYoutubeMeta(channels),
        )
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, channels, selectedYoutubeId, toast])

  useEffect(() => {
    if (!loadingChannels) buildMeta()
  }, [loadingChannels, buildMeta])

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await api.getInstagramConfig(token, clientId)
        if (cancelled) return
        const connection = data?.connection || {}
        if (connection.connected && connection.instagram_user_id) {
          setInstagramAccount({
            id: connection.instagram_user_id,
            username: connection.instagram_username || connection.instagram_user_id,
          })
          setInstagramConnected(true)
        } else {
          setInstagramAccount(null)
          setInstagramConnected(false)
        }
      } catch {
        if (!cancelled) {
          setInstagramAccount(null)
          setInstagramConnected(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId])

  const youtubeOptions = useMemo(
    () => [
      { value: 'all', label: 'All channels' },
      ...(channels || []).map((ch) => ({ value: ch.id, label: ch.title || ch.id })),
    ],
    [channels],
  )
  const instagramOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All accounts' }]
    if (instagramAccount) {
      options.push({
        value: instagramAccount.id,
        label: `@${instagramAccount.username}`,
      })
    }
    return options
  }, [instagramAccount])

  const hasChannels = channels?.length > 0
  const hasProfile =
    client?.specialty ||
    client?.description ||
    client?.website_url

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client' },
            ]}
          />
          <h1>Analytics</h1>
          <p>
            {source === 'youtube'
              ? selectedYoutubeId === 'all'
                ? 'All channels (client-level consolidated view)'
                : channelMeta?.title || 'YouTube analytics'
              : selectedInstagramId === 'all'
                ? 'Instagram performance for this client'
                : `@${instagramAccount?.username || 'instagram'}`}
          </p>
        </div>
        <div className="header-actions">
          <div className="connection-status-pill card">
            <span className={`status-dot ${hasChannels ? 'connected' : 'disconnected'}`} />
            <span>
              {channels?.length || 0} channel{(channels?.length || 0) === 1 ? '' : 's'}
            </span>
          </div>
        </div>
      </header>

      {hasProfile ? (
        <section className="client-profile-card card animate-fade-in">
          <div className="client-profile-header">
            <div>
              <h2>{presentation.profileLabel}</h2>
              {client.specialty && <span className="specialty-badge">{client.specialty}</span>}
            </div>
            <Link to={`/clients/${clientId}/profile/practice`} className="btn btn-secondary btn-sm">
              <i className="fa-solid fa-pen" /> Edit
            </Link>
          </div>
          {client.website_url && (
            <p className="profile-website">
              <i className="fa-solid fa-globe" />{' '}
              <a href={client.website_url} target="_blank" rel="noreferrer">
                {client.website_url.replace(/^https?:\/\//, '')}
              </a>
            </p>
          )}
          {client.description && <p className="profile-description">{client.description}</p>}
        </section>
      ) : (
        <section className="client-profile-empty card animate-fade-in">
          <div>
            <h2>Add a {presentation.profileLabel.toLowerCase()}</h2>
            <p>
              Add the practice website, specialty, and description so you can plan content for this
              client. Topic keywords live in Keywords and topics.
            </p>
          </div>
          <Link to={`/clients/${clientId}/profile/practice`} className="btn btn-primary">
            <i className="fa-solid fa-user-doctor" /> Set up profile
          </Link>
        </section>
      )}

      <div className="source-switcher-row">
        <SourceSwitcher value={source} onChange={setSource} ariaLabel="Analytics source" />
        {source === 'youtube' && hasChannels ? (
          <div className="filter-group">
            <label htmlFor="analytics-channel-filter">Channel</label>
            <CustomSelect
              id="analytics-channel-filter"
              className="filter-select"
              value={selectedYoutubeId}
              ariaLabel="YouTube channel"
              onChange={setSelectedYoutubeId}
              options={youtubeOptions}
            />
          </div>
        ) : null}
        {source === 'instagram' && instagramConnected !== false ? (
          <div className="filter-group">
            <label htmlFor="analytics-instagram-filter">Account</label>
            <CustomSelect
              id="analytics-instagram-filter"
              className="filter-select"
              value={selectedInstagramId}
              ariaLabel="Instagram account"
              onChange={setSelectedInstagramId}
              options={instagramOptions}
            />
          </div>
        ) : null}
      </div>

      {source === 'instagram' ? (
        instagramConnected === false ? (
          <div className="connect-prompt-container card animate-fade-in">
            <div className="prompt-illustration">
              <i className="fa-brands fa-instagram illustration-icon" />
            </div>
            <h2>Connect Instagram</h2>
            <p>Instagram analytics uses the account linked in Connections.</p>
            <Link to={`/clients/${clientId}/profile/connections/instagram`} className="btn btn-primary btn-lg">
              <i className="fa-brands fa-instagram" /> Open Connections
            </Link>
          </div>
        ) : (
        <InstagramAnalyticsDashboard
          showDisconnect={false}
          fetchAnalytics={(range) => api.instagramAnalytics(token, clientId, range)}
          onLoaded={(data) => {
            setInstagramConnected(Boolean(data?.instagram_connected || data?.token_expired))
            if (data?.token_expired) {
              window.dispatchEvent(new CustomEvent('connection-expired', {
                detail: {
                  platform: 'instagram',
                  message: 'Instagram token expired.',
                  reconnect_path: `/clients/${clientId}/profile/connections/instagram`,
                },
              }))
            }
          }}
        />
        )
      ) : (
        <>
      {(loading || loadingChannels) && (
        <div className="loading-overlay inline-loading">
          <div className="spinner-loader">
            <i className="fa-solid fa-spinner fa-spin" />
            <span>Analyzing channel stats...</span>
          </div>
        </div>
      )}

      {!loading && !loadingChannels && !hasChannels && (
        <div className="connect-prompt-container card animate-fade-in">
          <div className="prompt-illustration">
            <i className="fa-brands fa-youtube illustration-icon red-icon" />
          </div>
          <h2>No channels linked yet</h2>
          <p>
            Link YouTube channels for <strong>&quot;{client?.name}&quot;</strong> in Client Profile →
            Connections.
          </p>
          <Link to={`/clients/${clientId}/profile/connections/youtube`} className="btn btn-primary btn-lg">
            <i className="fa-brands fa-youtube" /> Open Connections
          </Link>
        </div>
      )}

      {!loading && !loadingChannels && hasChannels && channelMeta && (
        <AnalyticsPanel
          token={token}
          clientId={clientId}
          channelId={selectedYoutubeId === 'all' ? 'all' : selectedYoutubeId}
          channelMeta={channelMeta}
        />
      )}
        </>
      )}
    </>
  )
}
