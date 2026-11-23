import { useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function iso(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseIso(value) {
  const [year, month, day] = String(value || '').split('-').map(Number)
  if (!year || !month || !day) return null
  return new Date(year, month - 1, day)
}

function formatDay(value) {
  const date = typeof value === 'string' ? parseIso(value) : value
  if (!date) return ''
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function lastDays(count) {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - (count - 1))
  return { start: iso(start), end: iso(end) }
}

function monthCells(cursor) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const pad = (first.getDay() + 6) % 7
  const count = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate()
  const cells = Array(pad).fill(null)
  for (let day = 1; day <= count; day += 1) {
    cells.push(new Date(cursor.getFullYear(), cursor.getMonth(), day))
  }
  return cells
}

function rangeLabel(range) {
  if (!range?.start) return 'No dates yet'
  if (!range.end) return `${formatDay(range.start)} · pick an end date`
  const start = parseIso(range.start)
  const end = parseIso(range.end)
  const days = Math.round((end - start) / 86400000) + 1
  return `${formatDay(range.start)} – ${formatDay(range.end)} · ${days} days`
}

function percentText(row) {
  if (row.percent == null) return '—'
  if (row.percent > 0) return `+${row.percent}%`
  return `${row.percent}%`
}

function valueText(row, side) {
  const value = side === 'a' ? row.a : row.b
  if (row.unit === 'percent') return `${value}%`
  return Number(value || 0).toLocaleString('en-IN')
}

export default function ClientGbpResults() {
  const { clientId, connected, activeLocation } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [cursor, setCursor] = useState(() => new Date())
  const [active, setActive] = useState('a')
  const [ranges, setRanges] = useState({ a: { start: '', end: '' }, b: { start: '', end: '' } })
  const [history, setHistory] = useState([])
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [openDay, setOpenDay] = useState('')
  const [hoverDay, setHoverDay] = useState('')
  const [calOpen, setCalOpen] = useState(false)
  const calRef = useRef(null)
  const today = iso(new Date())

  const ready = Boolean(ranges.a.start && ranges.a.end && ranges.b.start && ranges.b.end)
  const byDay = useMemo(() => {
    const grouped = {}
    for (const item of history) {
      const day = item.applied_on
      if (!day) continue
      grouped[day] = grouped[day] || []
      grouped[day].push(item)
    }
    return grouped
  }, [history])

  useEffect(() => {
    if (!token || !connected || !activeLocation) return undefined
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const data = await api.gbpResults(token, clientId, activeLocation.location_id, ready ? ranges : { a: {}, b: {} })
        if (cancelled) return
        setHistory(data.apply_history || [])
        setRows(ready ? (data.rows || []) : [])
        if (data.error) toast(data.error, 'error')
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, connected, activeLocation?.location_id, ranges, ready, toast])

  function fillShortcut(count) {
    setRanges((prev) => ({ ...prev, [active]: lastDays(count) }))
  }

  useEffect(() => {
    if (!calOpen) return undefined
    function onPointer(event) {
      if (calRef.current && !calRef.current.contains(event.target)) setCalOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    return () => document.removeEventListener('mousedown', onPointer)
  }, [calOpen])

  function pickDay(day) {
    const picked = iso(day)
    if (picked > today) return
    setRanges((prev) => {
      const current = prev[active]
      if (!current.start || current.end) return { ...prev, [active]: { start: picked, end: '' } }
      if (picked < current.start) return { ...prev, [active]: { start: picked, end: current.start } }
      return { ...prev, [active]: { start: current.start, end: picked } }
    })
  }

  function toggleChange(dayKey) {
    setOpenDay((current) => (current === dayKey ? '' : dayKey))
  }

  const viewingCurrentMonth = cursor.getFullYear() === new Date().getFullYear() && cursor.getMonth() === new Date().getMonth()

  const cells = monthCells(cursor)
  const openChanges = byDay[openDay] || []

  if (!connected || !activeLocation) return null

  return (
    <section className="card profile-form social-card">
      <h2>Compare GMB performance between time periods</h2>
      <div className="gbp-compare-tools">
        <div className="gbp-results-ranges">
          {['a', 'b'].map((key) => (
            <button
              key={key}
              type="button"
              className={`gbp-results-range${active === key ? ' is-selected' : ''}`}
              onClick={() => setActive(key)}
            >
              <span>Range {key.toUpperCase()}</span>
              <strong>{rangeLabel(ranges[key])}</strong>
            </button>
          ))}
        </div>
        <div className="gbp-cal-anchor" ref={calRef}>
          <button
            type="button"
            className={`gbp-cal-btn${calOpen ? ' is-open' : ''}`}
            aria-label="Choose dates"
            onClick={() => setCalOpen((open) => !open)}
          >
            <i className="fa-solid fa-calendar-days" />
          </button>
          {calOpen && (
            <div className="gbp-cal-pop">
              <div className="gbp-results-cal-head">
                <strong>{cursor.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</strong>
                <div className="gbp-results-nav">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>Prev</button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={viewingCurrentMonth} onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>Next</button>
                </div>
              </div>
              <p className="profile-section-desc">Orange marks a day you applied an optimisation recommendation. Dates fill Range {active.toUpperCase()}.</p>
              <div className="gbp-results-week">
                {WEEKDAYS.map((day) => <span key={day}>{day}</span>)}
              </div>
              <div className="gbp-results-grid">
                {cells.map((day, index) => {
                  if (!day) return <span key={`empty-${index}`} />
                  const key = iso(day)
                  const marked = byDay[key]
                  const future = key > today
                  return (
                    <button
                      key={key}
                      type="button"
                      disabled={future}
                      className={`gbp-results-day${marked ? ' is-apply' : ''}${future ? ' is-future' : ''}${openDay === key ? ' is-open' : ''}`}
                      onMouseEnter={() => marked && setHoverDay(key)}
                      onMouseLeave={() => setHoverDay('')}
                      onClick={() => (marked ? toggleChange(key) : pickDay(day))}
                    >
                      {day.getDate()}
                      {hoverDay === key && <span className="gbp-results-tip">Click to see what you optimised</span>}
                    </button>
                  )
                })}
              </div>
              {openDay && (
                <div className="gbp-results-changes">
                  <div className="gbp-results-cal-head">
                    <h3>Changes on {formatDay(openDay)}</h3>
                    <button type="button" className="gbp-cal-close" aria-label="Close changes" onClick={() => setOpenDay('')}>
                      <i className="fa-solid fa-xmark" />
                    </button>
                  </div>
                  {openChanges.map((item, index) => (
                    <article key={`${item.applied_at || index}`}>
                      <strong>{item.summary}</strong>
                      <p><span>Before.</span> {item.before || 'Empty'}</p>
                      <p><span>After.</span> {item.after || 'Empty'}</p>
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="gbp-results-shortcuts">
        {[30, 60, 90].map((count) => (
          <button key={count} type="button" className="btn btn-secondary btn-sm" onClick={() => fillShortcut(count)}>
            Last {count} days
          </button>
        ))}
      </div>
      <p className="profile-section-desc">
        Shortcuts and calendar dates fill the selected range, up to today.
        {loading ? ' Loading numbers…' : ''}
      </p>
            {!ready ? (
              <p className="text-muted">Choose both ranges to load the comparison.</p>
            ) : (
              <div className="gbp-results-table">
                <div className="gbp-results-row is-head">
                  <span>Metric</span>
                  <span>Range A</span>
                  <span>Range B</span>
                  <span>Change</span>
                </div>
                {rows.map((row) => (
                  <div key={row.id} className="gbp-results-row">
                    <span>{row.label}</span>
                    <strong>{valueText(row, 'a')}</strong>
                    <strong>{valueText(row, 'b')}</strong>
                    <span className={row.percent > 0 ? 'is-up' : row.percent < 0 ? 'is-down' : ''}>
                      {percentText(row)}
                      <small>
                        {row.days_a} days vs {row.days_b} days
                        {row.basis === 'per_day' ? ' · per day' : ''}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
            )}
    </section>
  )
}
