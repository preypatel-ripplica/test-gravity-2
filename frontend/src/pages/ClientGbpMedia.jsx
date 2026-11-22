import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const CATEGORIES = [
  ['ADDITIONAL', 'Additional'],
  ['COVER', 'Cover'],
  ['PROFILE', 'Profile'],
  ['EXTERIOR', 'Exterior'],
  ['INTERIOR', 'Interior'],
  ['AT_WORK', 'At work'],
  ['PRODUCT', 'Product'],
  ['TEAMS', 'Team'],
  ['FOOD_AND_DRINK', 'Food and drink'],
  ['MENU', 'Menu'],
  ['COMMON_AREA', 'Common area'],
  ['ROOMS', 'Rooms'],
]

const CATEGORY_LABEL = Object.fromEntries(CATEGORIES)

export default function ClientGbpMedia() {
  const { client, clientId, connected, activeLocation, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [media, setMedia] = useState([])
  const [category, setCategory] = useState('ADDITIONAL')
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [zoom, setZoom] = useState(null)

  async function load() {
    if (!activeLocation) return
    setLoading(true)
    try {
      const data = await api.gbpMediaList(token, clientId, activeLocation.location_id)
      setMedia(data.media || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (connected && activeLocation) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, activeLocation?.location_id])

  async function upload(event) {
    event.preventDefault()
    if (!file) return
    try {
      await api.gbpMediaUpload(token, clientId, activeLocation.location_id, category, file)
      setFile(null)
      toast('Media uploaded.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function remove(item) {
    try {
      await api.gbpMediaDelete(token, clientId, item.name)
      toast('Media deleted.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Media"
        subtitle="Photos and videos on the active Google Business location."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : (
        <div className="gbp-stack">
          <form className="card profile-form social-card" onSubmit={upload}>
            <h2>Upload</h2>
            <label className="gbp-field">
              <span>Category</span>
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                {CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <input type="file" accept="image/*,video/*" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={!file}>Upload</button>
            </div>
          </form>
          {loading ? <p>Loading media…</p> : (
            <div className="gbp-media-grid">
              {media.map((item) => {
                const full = item.googleUrl || item.thumbnailUrl
                const categoryName = item.locationAssociation?.category
                return (
                  <article key={item.name} className="card gbp-media-card">
                    <button
                      type="button"
                      className="gbp-media-open"
                      onClick={() => full && setZoom({ src: full, label: CATEGORY_LABEL[categoryName] || categoryName || 'Photo' })}
                    >
                      {full ? <img src={item.thumbnailUrl || full} alt="" /> : <div className="text-muted">No preview</div>}
                    </button>
                    <div className="gbp-media-meta">
                      <p>{CATEGORY_LABEL[categoryName] || categoryName || item.mediaFormat}</p>
                      <button type="button" className="gbp-icon-btn" aria-label="Delete photo" onClick={() => remove(item)}>
                        <i className="fa-solid fa-trash" />
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
          {zoom && (
            <div className="gbp-lightbox" role="dialog" aria-modal="true" aria-label={zoom.label}>
              <button type="button" className="gbp-lightbox-close" aria-label="Close" onClick={() => setZoom(null)}>
                <i className="fa-solid fa-xmark" />
              </button>
              <img src={zoom.src} alt={zoom.label} />
            </div>
          )}
        </div>
      )}
    </>
  )
}
