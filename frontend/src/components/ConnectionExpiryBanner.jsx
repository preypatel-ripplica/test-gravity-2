import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../context/AuthContext'

export function notifyConnectionExpired(message, clientId) {
  const text = String(message || '')
  if (!/expired|reconnect/i.test(text) || !clientId) return
  const platform = /youtube|google/i.test(text)
    ? 'youtube'
    : /facebook/i.test(text)
      ? 'facebook'
      : 'instagram'
  const label = platform === 'youtube' ? 'YouTube' : platform === 'facebook' ? 'Facebook' : 'Instagram'
  window.dispatchEvent(new CustomEvent('connection-expired', {
    detail: {
      platform,
      message: `${label} token expired.`,
      reconnect_path: `/clients/${clientId}/profile/connections/${platform}`,
    },
  }))
}

/** Stays until the user closes it. Comes back on the next load if the token is still expired. */
export default function ConnectionExpiryBanner({ clientId }) {
  const { token } = useAuth()
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(true)

  useEffect(() => {
    function onExpired(event) {
      const item = event.detail
      if (!item?.platform) return
      setItems((prev) => (
        prev.some((row) => row.platform === item.platform) ? prev : [...prev, item]
      ))
      setOpen(true)
    }
    window.addEventListener('connection-expired', onExpired)
    return () => window.removeEventListener('connection-expired', onExpired)
  }, [])

  useEffect(() => {
    setOpen(true)
    if (!token || !clientId) return
    let cancelled = false
    api.connectionHealth(token, clientId)
      .then((data) => {
        if (!cancelled) setItems(data.expired || [])
      })
      .catch(() => {
        if (!cancelled) setItems([])
      })
    return () => {
      cancelled = true
    }
  }, [token, clientId])

  if (!open || !items.length) return null

  return (
    <div className="connection-expiry-banner" role="alert">
      <div className="connection-expiry-copy">
        {items.map((item) => (
          <p key={`${item.platform}-${item.channel_id || ''}`}>
            {item.message}{' '}
            <Link to={item.reconnect_path}>Reconnect</Link>
          </p>
        ))}
      </div>
      <button type="button" className="connection-expiry-close" onClick={() => setOpen(false)} aria-label="Dismiss">
        ×
      </button>
    </div>
  )
}
