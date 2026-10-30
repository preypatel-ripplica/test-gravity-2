import { useMemo, useState } from 'react'
import { apiFetchProgress } from '../../api'
import VideoUrlAttachField from '../VideoUrlAttachField'
import PublishProgressBusy from '../PublishProgressBusy'
import { LANG_LABELS, localeHasTitle, maybeAdvanceStage } from './trackerUtils'

function languageLabel(key) {
  return LANG_LABELS[key] || key || 'Unassigned'
}

export default function TrackerPublishVideo({ card, weekContext, onChange }) {
  const { token, clientId, toast, channels = [] } = weekContext
  const locales = card.yt_locales || {}
  const hasMeta = localeHasTitle(locales)
  const [postToYT, setPostToYT] = useState(true)
  const [postToIG, setPostToIG] = useState(false)
  const [postToFB, setPostToFB] = useState(false)
  const [selectedChannelIds, setSelectedChannelIds] = useState(channels[0] ? [channels[0].id] : [])
  const [videoUrlsByChannel, setVideoUrlsByChannel] = useState({})
  const [socialVideoLink, setSocialVideoLink] = useState('')
  const [busy, setBusy] = useState(false)
  const [publishStage, setPublishStage] = useState('')

  const selectedYtChannels = useMemo(
    () => channels.filter((c) => selectedChannelIds.includes(c.id)),
    [channels, selectedChannelIds],
  )
  const hinglishUrl = useMemo(() => {
    const hinglishChannel = selectedYtChannels.find((c) => c.language === 'hinglish')
    return (hinglishChannel && videoUrlsByChannel[hinglishChannel.id]) || ''
  }, [selectedYtChannels, videoUrlsByChannel])

  async function handlePublish() {
    if (!card.topic_id) {
      toast('Choose a generated script first.', 'error')
      return
    }
    if (!hasMeta) {
      toast('Generate YouTube metadata first.', 'error')
      return
    }
    if (!postToYT && !postToIG && !postToFB) {
      toast('Select at least one platform.', 'error')
      return
    }
    if (postToYT && selectedChannelIds.length === 0) {
      toast('Select at least one YouTube channel.', 'error')
      return
    }
    if (postToYT) {
      for (const ch of selectedYtChannels) {
        if (!ch.language) {
          toast(`Assign a language in Settings for "${ch.title || ch.id}" first.`, 'error')
          return
        }
        if (!locales[ch.language]?.yt_title) {
          toast(`Generate metadata for ${languageLabel(ch.language)} first.`, 'error')
          return
        }
        if (!(videoUrlsByChannel[ch.id] || '').trim()) {
          toast(`Add a video URL for "${ch.title || ch.id}".`, 'error')
          return
        }
      }
    }
    const socialUrl = (socialVideoLink || hinglishUrl || Object.values(videoUrlsByChannel).find(Boolean) || '').trim()
    if ((postToIG || postToFB) && !postToYT && !socialUrl) {
      toast('Please provide a social video URL.', 'error')
      return
    }

    setBusy(true)
    setPublishStage('Starting publish…')
    try {
      const anchor = selectedYtChannels.find((ch) => ch.language === 'hinglish') || selectedYtChannels[0] || channels[0]
      const socialLang = locales.hinglish?.yt_title
        ? 'hinglish'
        : (Object.keys(locales).find((key) => locales[key]?.yt_title) || anchor?.language || 'hinglish')
      const anchorLocale = (postToYT ? locales[anchor?.language] : locales[socialLang]) || {}
      const socialFile = (postToIG || postToFB)
        ? ((socialVideoLink || hinglishUrl || (!postToYT ? socialUrl : '')).trim() || undefined)
        : undefined
      const data = await apiFetchProgress('/video.upload', {
        token,
        onStage: setPublishStage,
        body: {
          client_id: clientId,
          channel_id: anchor?.id || channels[0]?.id || '',
          drive_link: postToYT ? (videoUrlsByChannel[anchor?.id] || '').trim() : socialUrl,
          title: anchorLocale.yt_title || card.title,
          description: anchorLocale.yt_description || '',
          tags: (anchorLocale.yt_tags || []).map((tag) => String(tag).replace(/#/g, '')),
          thumbnail_url: anchorLocale.yt_thumbnail_url,
          post_to_youtube: postToYT,
          post_to_instagram: postToIG,
          post_to_facebook: postToFB,
          topic_id: card.topic_id,
          language: postToYT ? anchor?.language : socialLang,
          social_source_url: socialFile,
          social_drive_link: socialFile,
          stream_progress: true,
          channels: postToYT ? selectedYtChannels.map((ch) => {
            const locale = locales[ch.language] || {}
            return {
              channel_id: ch.id,
              drive_link: (videoUrlsByChannel[ch.id] || '').trim(),
              title: locale.yt_title || card.title,
              description: locale.yt_description || '',
              tags: (locale.yt_tags || []).map((tag) => String(tag).replace(/#/g, '')),
              thumbnail_url: locale.yt_thumbnail_url,
              language: ch.language,
            }
          }) : [],
        },
      })
      const errors = data?.errors || []
      if (errors.length) {
        toast(errors.join(' '), 'error')
      } else {
        toast('Video posted.', 'success')
        setVideoUrlsByChannel({})
        setSocialVideoLink('')
      }
      let result = null
      try {
        result = await weekContext.reloadWeek?.()
      } catch (reloadErr) {
        toast(`Tracker could not refresh (${reloadErr.message}). Log in again, then reopen this week.`, 'error')
      }
      if (!result && errors.length === 0) {
        onChange(maybeAdvanceStage({ ...card, stage: 'posted' }))
      }
    } catch (err) {
      toast(err.message, 'error')
      try {
        await weekContext.reloadWeek?.()
      } catch {
        // Posted links may already be saved even when the request failed.
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="tracker-script-slot tracker-publish">
      <div className="tracker-script-slot-head">
        <span className="tracker-kicker">Publish video</span>
      </div>
      {!hasMeta ? (
        <p className="tracker-hint">Generate YouTube metadata first, then publish from here.</p>
      ) : (
        <>
          <p className="tracker-publish-label">Where do you want to post?</p>
          <div className="tracker-platform-picks">
            <label className={`tracker-platform-pick${postToYT ? ' is-on' : ''}`}>
              <input type="checkbox" checked={postToYT} onChange={(e) => setPostToYT(e.target.checked)} />
              <i className="fa-brands fa-youtube" style={{ color: '#ff0000' }} />
            </label>
            <label className={`tracker-platform-pick${postToIG ? ' is-on' : ''}`}>
              <input type="checkbox" checked={postToIG} onChange={(e) => setPostToIG(e.target.checked)} />
              <i className="fa-brands fa-instagram" style={{ color: '#E1306C' }} />
            </label>
            <label className={`tracker-platform-pick${postToFB ? ' is-on' : ''}`}>
              <input type="checkbox" checked={postToFB} onChange={(e) => setPostToFB(e.target.checked)} />
              <i className="fa-brands fa-facebook" style={{ color: '#1877F2' }} />
            </label>
          </div>

          {postToYT && (
            <div className="tracker-channel-pick">
              <strong>Select YouTube Channels ({selectedChannelIds.length})</strong>
              <div className="tracker-channel-list">
                {channels.map((ch) => {
                  const isSel = selectedChannelIds.includes(ch.id)
                  return (
                    <button
                      type="button"
                      key={ch.id}
                      className={`tracker-channel-row${isSel ? ' is-on' : ''}`}
                      onClick={() => setSelectedChannelIds((prev) => (
                        prev.includes(ch.id) ? prev.filter((id) => id !== ch.id) : [...prev, ch.id]
                      ))}
                    >
                      <input type="checkbox" checked={isSel} readOnly />
                      <span>
                        {ch.title || ch.id}
                        <small>{ch.language ? languageLabel(ch.language) : 'No language in Settings'}</small>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {postToYT && selectedYtChannels.length > 0 && (
            <div className="tracker-drive-list">
              <strong>Video URL for each channel</strong>
              <p className="tracker-hint">Each selected channel gets its own Drive link. Metadata follows the language assigned in Settings.</p>
              {selectedYtChannels.map((ch) => (
                <div key={ch.id} className="tracker-drive-row">
                  <span>
                    <em>{languageLabel(ch.language)}</em>
                    {ch.title || ch.id}
                  </span>
                  <VideoUrlAttachField
                    token={token}
                    clientId={clientId}
                    toast={toast}
                    value={videoUrlsByChannel[ch.id] || ''}
                    onChange={(url) => setVideoUrlsByChannel((prev) => ({ ...prev, [ch.id]: url }))}
                  />
                </div>
              ))}
            </div>
          )}

          {(postToIG || postToFB) && (
            <div className="tracker-drive-row">
              <span>Social video URL</span>
              <VideoUrlAttachField
                token={token}
                clientId={clientId}
                toast={toast}
                placeholder={hinglishUrl ? 'Optional — uses Hinglish channel URL if blank' : 'https://drive.google.com/...'}
                value={socialVideoLink}
                onChange={setSocialVideoLink}
              />
            </div>
          )}

          <button type="button" className="btn btn-primary" disabled={busy} onClick={handlePublish}>
            {busy ? (
              <PublishProgressBusy active={busy} stage={publishStage} />
            ) : (
              <>
                <i className="fa-solid fa-paper-plane" /> Publish Video
              </>
            )}
          </button>
        </>
      )}
    </section>
  )
}
