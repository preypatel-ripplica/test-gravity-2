import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import { notifyConnectionExpired } from '../components/ConnectionExpiryBanner'
import SourceSwitcher from '../components/SourceSwitcher'
import VideosPanel from '../components/VideosPanel'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientVideos() {
  const { token } = useAuth()
  const { toast } = useUI()
  const { client, clientId, channels, loadingChannels } = useOutletContext()

  const [videos, setVideos] = useState([])
  const [loading, setLoading] = useState(false)
  const [source, setSource] = useState('youtube')

  const loadVideos = useCallback(async () => {
    if (!token || !clientId) return
    if (source === 'instagram') {
      setLoading(true)
      try {
        const [data, config] = await Promise.all([
          api.listInstagramVideos(token, clientId),
          api.getInstagramConfig(token, clientId).catch(() => null),
        ])
        const connection = config?.connection || {}
        const accountId = connection.instagram_user_id || ''
        const accountTitle = connection.instagram_username
          ? `@${connection.instagram_username}`
          : accountId
        setVideos(
          (data.videos || []).map((video) => {
            const id = video.channel_id || video.channelId || accountId
            return {
              ...video,
              channelId: id,
              channelTitle: id === accountId && accountTitle ? accountTitle : id ? `@${id}` : accountTitle,
            }
          }),
        )
      } catch (err) {
        toast(`Failed to load Instagram videos: ${err.message}`, 'error')
        setVideos([])
      } finally {
        setLoading(false)
      }
      return
    }
    if (!channels?.length) {
      setVideos([])
      return
    }
    setLoading(true)
    try {
      const videosPromises = channels.map((ch) =>
        api.listVideos(token, clientId, ch.id).catch(() => ({ videos: [] })),
      )
      const allVideosResponses = await Promise.all(videosPromises)
      const combinedVideos = []
      allVideosResponses.forEach((res, index) => {
        const ch = channels[index]
        ;(res.videos || []).forEach((v) => {
          combinedVideos.push({
            ...v,
            channelId: ch.id,
            channelTitle: ch.title,
          })
        })
      })
      setVideos(combinedVideos)
    } catch (err) {
      toast(`Failed to load videos: ${err.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, channels, toast, source])

  useEffect(() => {
    if (!loadingChannels) loadVideos()
  }, [loadingChannels, loadVideos])

  async function handleSync() {
    if (source === 'instagram') {
      toast('Syncing Instagram reels…', 'info')
      try {
        const [data, config] = await Promise.all([
          api.syncInstagramVideos(token, clientId),
          api.getInstagramConfig(token, clientId).catch(() => null),
        ])
        const connection = config?.connection || {}
        const accountId = connection.instagram_user_id || ''
        const accountTitle = connection.instagram_username
          ? `@${connection.instagram_username}`
          : accountId
        const next = (data.videos || []).map((video) => {
          const id = video.channel_id || video.channelId || accountId
          return {
            ...video,
            channelId: id,
            channelTitle: id === accountId && accountTitle ? accountTitle : id ? `@${id}` : accountTitle,
          }
        })
        setVideos(next)
        return next.length
      } catch (err) {
        notifyConnectionExpired(err.message, clientId)
        throw err
      }
    }
    toast('Syncing all channels in parallel...', 'info')
    const syncPromises = channels.map((ch) =>
      api.syncVideos(token, clientId, ch.id).catch((err) => {
        console.error(`Error syncing ${ch.title}:`, err)
        return { videos: [] }
      }),
    )
    const syncResponses = await Promise.all(syncPromises)
    const combinedVideos = []
    syncResponses.forEach((res, index) => {
      const ch = channels[index]
      ;(res.videos || []).forEach((v) => {
        combinedVideos.push({
          ...v,
          channelId: ch.id,
          channelTitle: ch.title,
        })
      })
    })
    setVideos(combinedVideos)
    return combinedVideos.length
  }

  async function handleUpdate(videoId, videoChannelId, notes, metadataFields) {
    try {
      const updatedVideo = await api.updateVideo(
        token,
        videoId,
        clientId,
        videoChannelId,
        notes,
        metadataFields,
      )
      setVideos((prev) =>
        prev.map((v) =>
          v.id === videoId
            ? {
                ...v,
                notes: updatedVideo.notes,
                metadata_fields: updatedVideo.metadata_fields,
              }
            : v,
        ),
      )
      toast('Video updated successfully!', 'success')
      return updatedVideo
    } catch (err) {
      toast(`Error updating video: ${err.message}`, 'error')
      throw err
    }
  }

  const hasChannels = channels?.length > 0

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Videos' },
            ]}
          />
          <h1>Videos Database</h1>
          <p>{source === 'youtube' ? 'Consolidated videos across all channels' : 'Published Instagram reels'}</p>
        </div>
      </header>

      <div style={{ marginBottom: 16 }}>
        <SourceSwitcher value={source} onChange={setSource} ariaLabel="Video library source" />
      </div>

      {(loading || loadingChannels) && (
        <div className="loading-overlay inline-loading">
          <div className="spinner-loader">
            <i className="fa-solid fa-spinner fa-spin" />
            <span>Loading videos...</span>
          </div>
        </div>
      )}

      {!loading && !loadingChannels && source === 'youtube' && !hasChannels && (
        <div className="connect-prompt-container card animate-fade-in">
          <div className="prompt-illustration">
            <i className="fa-brands fa-youtube illustration-icon red-icon" />
          </div>
          <h2>No channels linked yet</h2>
          <p>Link a YouTube channel in Client Profile → Connections to start syncing videos.</p>
          <Link to={`/clients/${clientId}/profile/connections/youtube`} className="btn btn-primary btn-lg">
            <i className="fa-brands fa-youtube" /> Open Connections
          </Link>
        </div>
      )}

      {!loading && !loadingChannels && (source === 'instagram' || hasChannels) && (
        <VideosPanel
          videos={videos}
          onSync={handleSync}
          onUpdate={handleUpdate}
          isClientLevel
          libraryPlatform={source}
          libraryHint={source === 'instagram' ? 'Instagram reels saved for this client' : ''}
          emptyHint={
            source === 'instagram'
              ? 'Click Sync video stats to pull reels from Instagram.'
              : 'Click Sync video stats to fetch videos from YouTube.'
          }
        />
      )}
    </>
  )
}
