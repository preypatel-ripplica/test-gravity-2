import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const METRICS = [
  ['search_impressions', 'Search impressions'],
  ['maps_impressions', 'Maps impressions'],
  ['website_clicks', 'Website clicks'],
  ['calls', 'Calls'],
  ['direction_requests', 'Direction requests'],
]

function formatRating(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number.toFixed(2)
}

export default function ClientGbpOverview() {
  const { client, clientId, connected, activeLocation, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!token || !clientId || !connected || !activeLocation) return
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const overview = await api.gbpOverview(token, clientId, activeLocation.location_id)
        if (!cancelled) setData(overview)
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, connected, activeLocation, toast])

  const current = data?.performance?.current || {}
  const previous = data?.performance?.previous || {}

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Overview"
        subtitle={activeLocation ? activeLocation.title : 'Google Business Profile for this client.'}
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : loading || !data ? (
        <p className="text-muted">Loading overview…</p>
      ) : (
        <div className="gbp-stack">
          {data.reviews_error && <p className="gbp-pending">{data.reviews_error}</p>}
          {data.performance?.error && <p className="gbp-pending">{data.performance.error}</p>}
          <div className="gbp-overview-grid">
            <article className="card gbp-metric gbp-tilt">
              <span>Rating</span>
              <strong>{formatRating(data.average_rating)}</strong>
              <em>{data.total_review_count ?? 0} reviews</em>
            </article>
            {METRICS.map(([key, label]) => (
              <article key={key} className="card gbp-metric gbp-tilt">
                <span>{label}</span>
                <strong>{Math.round(current[key] || 0)}</strong>
                <em>Prior 30 days: {Math.round(previous[key] || 0)}</em>
              </article>
            ))}
          </div>
          <p className="text-muted">
            Each activity number is the last 30 days. “Prior 30 days” is the 30 days immediately before that.
            Open Performance for a chart, a different date range, and search keywords.
          </p>
        </div>
      )}
    </>
  )
}
