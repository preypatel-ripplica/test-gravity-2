import { useEffect, useMemo, useState } from 'react'
import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

function rangeFor(days) {
  const end = new Date()
  end.setDate(end.getDate() - 1)
  const start = new Date(end)
  start.setDate(end.getDate() - (days - 1))
  const fmt = (value) => {
    const month = String(value.getMonth() + 1).padStart(2, '0')
    const day = String(value.getDate()).padStart(2, '0')
    return `${value.getFullYear()}-${month}-${day}`
  }
  return { start: fmt(start), end: fmt(end) }
}

const SERIES = [
  { key: 'BUSINESS_IMPRESSIONS_MOBILE_SEARCH', label: 'Search mobile', color: '#1a73e8' },
  { key: 'BUSINESS_IMPRESSIONS_DESKTOP_SEARCH', label: 'Search desktop', color: '#7c3aed' },
  { key: 'BUSINESS_IMPRESSIONS_MOBILE_MAPS', label: 'Maps mobile', color: '#0f766e' },
  { key: 'BUSINESS_IMPRESSIONS_DESKTOP_MAPS', label: 'Maps desktop', color: '#4f46e5' },
  { key: 'WEBSITE_CLICKS', label: 'Website', color: '#0369a1' },
  { key: 'CALL_CLICKS', label: 'Calls', color: '#be123c' },
  { key: 'BUSINESS_DIRECTION_REQUESTS', label: 'Directions', color: '#b45309' },
  { key: 'MESSAGING_CLICKS', label: 'Chat clicks', color: '#db2777' },
  { key: 'BUSINESS_BOOKINGS', label: 'Bookings', color: '#15803d' },
]

const DEFAULT_ON = new Set([
  'BUSINESS_IMPRESSIONS_MOBILE_SEARCH',
  'BUSINESS_IMPRESSIONS_DESKTOP_SEARCH',
  'BUSINESS_IMPRESSIONS_MOBILE_MAPS',
  'BUSINESS_IMPRESSIONS_DESKTOP_MAPS',
])

export default function ClientGbpPerformance() {
  const { client, clientId, connected, activeLocation, selectedLocations, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [days, setDays] = useState(30)
  const [allLocations, setAllLocations] = useState(false)
  const [data, setData] = useState(null)
  const [keywords, setKeywords] = useState([])
  const [loading, setLoading] = useState(false)
  const [visible, setVisible] = useState(() => new Set(DEFAULT_ON))

  useEffect(() => {
    if (!token || !connected || !activeLocation) return
    let cancelled = false
    const { start, end } = rangeFor(days)
    const locationId = allLocations ? null : activeLocation.location_id
    setLoading(true)
    ;(async () => {
      try {
        const [perf, words] = await Promise.all([
          api.gbpPerformance(token, clientId, start, end, locationId),
          api.gbpKeywords(token, clientId, start, end, locationId),
        ])
        if (cancelled) return
        setData(perf)
        setKeywords(words.keywords || [])
        const errors = [...(perf.current?.errors || []), ...(words.errors || [])]
        if (errors[0]?.detail) toast(errors[0].detail, 'error')
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, connected, activeLocation, allLocations, days, toast])

  const chart = useMemo(() => {
    const series = data?.current?.series || {}
    const chosen = SERIES.filter((item) => visible.has(item.key))
    const dates = []
    const seen = new Set()
    for (const item of chosen) {
      for (const point of series[item.key] || []) {
        if (!seen.has(point.date)) {
          seen.add(point.date)
          dates.push(point.date)
        }
      }
    }
    dates.sort()
    return {
      labels: dates.map((day) => day.slice(5)),
      datasets: chosen.map((item) => {
        const values = Object.fromEntries((series[item.key] || []).map((point) => [point.date, point.value]))
        return {
          label: item.label,
          data: dates.map((day) => values[day] ?? 0),
          borderColor: item.color,
          backgroundColor: item.color,
          tension: 0.2,
          spanGaps: true,
          pointRadius: 3,
          pointHoverRadius: 6,
          pointHitRadius: 12,
        }
      }),
    }
  }, [data, visible])

  function toggleSeries(key) {
    setVisible((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const summary = data?.current?.summary || {}
  const previous = data?.previous?.summary || {}

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Performance"
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : (
        <div className="gbp-stack gbp-stack-wide">
          <div className="gbp-toolbar">
            <div className="gbp-range" role="group" aria-label="Date range">
              {[7, 30, 90].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={days === value ? 'is-active' : ''}
                  onClick={() => setDays(value)}
                >
                  Last {value} days
                </button>
              ))}
            </div>
            {selectedLocations.length > 1 && (
              <label className="gbp-check">
                <input
                  type="checkbox"
                  checked={allLocations}
                  onChange={(event) => setAllLocations(event.target.checked)}
                />
                All selected locations
              </label>
            )}
          </div>
          {loading ? <p>Loading performance…</p> : (
            <>
              <div className="gbp-metric-grid gbp-metric-grid-performance">
                <article className="card gbp-metric tone-search">
                  <span>Search impressions</span>
                  <strong>{Math.round(summary.search_impressions || 0)}</strong>
                  <em>Desktop {Math.round(summary.search_desktop || 0)}</em>
                  <em>Mobile {Math.round(summary.search_mobile || 0)}</em>
                  <em className="gbp-metric-prior">Prior period: {Math.round(previous.search_impressions || 0)}</em>
                </article>
                <article className="card gbp-metric tone-maps">
                  <span>Maps impressions</span>
                  <strong>{Math.round(summary.maps_impressions || 0)}</strong>
                  <em>Desktop {Math.round(summary.maps_desktop || 0)}</em>
                  <em>Mobile {Math.round(summary.maps_mobile || 0)}</em>
                  <em className="gbp-metric-prior">Prior period: {Math.round(previous.maps_impressions || 0)}</em>
                </article>
                {[
                  ['website_clicks', 'Website clicks', 'tone-website'],
                  ['calls', 'Calls', 'tone-calls'],
                  ['direction_requests', 'Direction requests', 'tone-directions'],
                  ['chat_clicks', 'Chat clicks', 'tone-chat'],
                  ['bookings', 'Bookings', 'tone-bookings'],
                ].map(([key, label, tone]) => (
                  <article key={key} className={`card gbp-metric ${tone}`}>
                    <span>{label}</span>
                    <strong>{Math.round(summary[key] || 0)}</strong>
                    <em className="gbp-metric-prior">Prior period: {Math.round(previous[key] || 0)}</em>
                  </article>
                ))}
              </div>
              <section className="card profile-form">
                <div className="gbp-series-toggles">
                  {SERIES.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      className={visible.has(item.key) ? 'is-active' : ''}
                      onClick={() => toggleSeries(item.key)}
                    >
                      <i style={{ background: item.color }} />
                      {item.label}
                    </button>
                  ))}
                </div>
                <Line
                  data={chart}
                  options={{
                    responsive: true,
                    interaction: { mode: 'nearest', intersect: true },
                    plugins: {
                      legend: { display: false },
                      tooltip: {
                        mode: 'nearest',
                        intersect: true,
                        callbacks: {
                          title: (items) => items[0]?.label || '',
                          label: (item) => ` ${item.dataset.label}: ${item.parsed.y}`,
                        },
                      },
                    },
                    scales: {
                      x: { ticks: { maxRotation: 0, autoSkip: true } },
                      y: { beginAtZero: true },
                    },
                  }}
                />
              </section>
              <section className="card profile-form">
                <h2>Search keywords</h2>
                <p className="profile-section-desc">How often people found this profile from these searches. Google reports this by month.</p>
                {keywords.length === 0 ? <p className="text-muted">No keyword data for this range.</p> : (
                  <div className="gbp-keyword-list">
                    {keywords.map((item) => {
                      const max = keywords[0]?.impressions || 1
                      const width = Math.max(4, Math.round((item.impressions / max) * 100))
                      return (
                        <div key={item.keyword} className="gbp-keyword-row">
                          <span>{item.keyword}</span>
                          <div className="gbp-keyword-track"><div style={{ width: `${width}%` }} /></div>
                          <strong>{Math.round(item.impressions)}</strong>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </>
  )
}
