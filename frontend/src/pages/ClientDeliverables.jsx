import { useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import {
  MAX_SLOTS_PER_FAMILY,
  normalizeDeliverables,
  weekOfDate,
  weekRanges,
  weekShareCounts,
} from '../components/tracker/trackerUtils'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const MONTH_OPTIONS = [
  { month: 1, label: 'January', short: 'Jan' },
  { month: 2, label: 'February', short: 'Feb' },
  { month: 3, label: 'March', short: 'Mar' },
  { month: 4, label: 'April', short: 'Apr' },
  { month: 5, label: 'May', short: 'May' },
  { month: 6, label: 'June', short: 'Jun' },
  { month: 7, label: 'July', short: 'Jul' },
  { month: 8, label: 'August', short: 'Aug' },
  { month: 9, label: 'September', short: 'Sep' },
  { month: 10, label: 'October', short: 'Oct' },
  { month: 11, label: 'November', short: 'Nov' },
  { month: 12, label: 'December', short: 'Dec' },
]

function currentMonthValue(today = new Date()) {
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
}

function parseMonthValue(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})$/)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  if (!year || month < 1 || month > 12) return null
  return { year, month }
}

function formatMonthLabel(value) {
  const parsed = parseMonthValue(value)
  if (!parsed) return ''
  return new Date(parsed.year, parsed.month - 1, 1).toLocaleDateString('en-GB', {
    month: 'short',
    year: 'numeric',
  })
}

function MonthPicker({ value, onChange, onClear }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const parsed = parseMonthValue(value)
  const [viewYear, setViewYear] = useState(parsed?.year || new Date().getFullYear())

  useEffect(() => {
    if (open) setViewYear(parsed?.year || new Date().getFullYear())
  }, [open, parsed?.year])

  useEffect(() => {
    function onDoc(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className="month-picker" ref={wrapRef}>
      <button
        type="button"
        className={`month-picker-btn${value ? ' has-value' : ''}`}
        onClick={() => setOpen((current) => !current)}
      >
        <i className="fa-regular fa-calendar" />
        {value ? formatMonthLabel(value) : 'Pick start month'}
      </button>
      {value ? (
        <button type="button" className="month-picker-clear" onClick={onClear} title="Clear start">
          <i className="fa-solid fa-xmark" />
        </button>
      ) : null}
      {open ? (
        <div className="month-picker-pop">
          <div className="month-picker-year">
            <button type="button" onClick={() => setViewYear((year) => year - 1)} aria-label="Previous year">
              <i className="fa-solid fa-chevron-left" />
            </button>
            <strong>{viewYear}</strong>
            <button type="button" onClick={() => setViewYear((year) => year + 1)} aria-label="Next year">
              <i className="fa-solid fa-chevron-right" />
            </button>
          </div>
          <div className="month-picker-grid">
            {MONTH_OPTIONS.map((row) => {
              const selected = parsed?.year === viewYear && parsed?.month === row.month
              return (
                <button
                  key={row.month}
                  type="button"
                  className={selected ? 'is-on' : ''}
                  onClick={() => {
                    onChange(viewYear, row.month)
                    setOpen(false)
                  }}
                >
                  {row.short}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function emptyForm() {
  return { videos: [{ format: 'long' }], static_post: 1, blog: 1, paid_ads: 0 }
}

function formFromSlots(slots) {
  const form = { videos: [], static_post: 0, blog: 0, paid_ads: 0 }
  for (const slot of normalizeDeliverables(slots)) {
    if (slot.type === 'video') form.videos.push({ format: slot.format === 'short' ? 'short' : 'long' })
    else if (slot.type === 'static_post') form.static_post += 1
    else if (slot.type === 'blog') form.blog += 1
    else if (slot.type === 'paid_ads') form.paid_ads += 1
  }
  return form
}

function slotsFromForm(form) {
  const slots = []
  for (const video of form.videos || []) {
    slots.push({ type: 'video', format: video.format === 'short' ? 'short' : 'long' })
  }
  for (let i = 0; i < Number(form.static_post || 0); i += 1) slots.push({ type: 'static_post' })
  for (let i = 0; i < Number(form.blog || 0); i += 1) slots.push({ type: 'blog' })
  for (let i = 0; i < Number(form.paid_ads || 0); i += 1) slots.push({ type: 'paid_ads' })
  return slots
}

function CountRow({ label, hint, value, onChange }) {
  const split = weekShareCounts(value).join('-')
  return (
    <div className={`deliverable-count${value > 0 ? ' is-on' : ''}`}>
      <div>
        <strong>{label}</strong>
        <small>{hint}</small>
        {value > 0 ? <small>This month by week: {split}</small> : null}
      </div>
      <div className="deliverable-stepper">
        <button type="button" className="btn btn-secondary btn-sm" disabled={value <= 0} onClick={() => onChange(value - 1)}>
          −
        </button>
        <span>{value}</span>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={value >= MAX_SLOTS_PER_FAMILY}
          onClick={() => onChange(value + 1)}
        >
          +
        </button>
      </div>
    </div>
  )
}

export default function ClientDeliverables() {
  const { client, clientId } = useOutletContext()
  const { token, patchUser } = useAuth()
  const { toast, confirm } = useUI()

  const [form, setForm] = useState(emptyForm)
  const [onboardingDate, setOnboardingDate] = useState('')
  const [startMonth, setStartMonth] = useState('')
  const [startWeek, setStartWeek] = useState(null)
  const [aiVideosStartedFrom, setAiVideosStartedFrom] = useState(() => currentMonthValue())
  const [saving, setSaving] = useState(false)
  const [marking, setMarking] = useState(false)

  useEffect(() => {
    if (!client || client.id !== clientId) return
    setForm(formFromSlots(client.tracker_deliverables))
    setOnboardingDate(client.onboarding_date || '')
    setAiVideosStartedFrom(client.ai_videos_started_from || currentMonthValue())
    if (client.tracker_start_year && client.tracker_start_month) {
      setStartMonth(
        `${client.tracker_start_year}-${String(client.tracker_start_month).padStart(2, '0')}`,
      )
      setStartWeek(Number(client.tracker_start_week) || 1)
    } else {
      setStartMonth('')
      setStartWeek(null)
    }
  }, [clientId, client?.id])

  const weekOptions = useMemo(() => {
    const parsed = parseMonthValue(startMonth) || parseMonthValue(currentMonthValue())
    return weekRanges(parsed.year, parsed.month)
  }, [startMonth])

  function applyStart(year, month) {
    const value = `${year}-${String(month).padStart(2, '0')}`
    setStartMonth(value)
    if (onboardingDate) {
      const onboard = new Date(`${onboardingDate}T00:00:00`)
      if (
        !Number.isNaN(onboard.getTime())
        && onboard.getFullYear() === year
        && onboard.getMonth() + 1 === month
      ) {
        setStartWeek(weekOfDate(onboard))
        return
      }
    }
    if (!weekRanges(year, month).some((row) => row.week === Number(startWeek))) {
      setStartWeek(1)
    } else if (!startWeek) {
      setStartWeek(1)
    }
  }

  function clearStart() {
    setStartMonth('')
    setStartWeek(null)
  }

  function setCount(key, next) {
    const value = Math.max(0, Math.min(MAX_SLOTS_PER_FAMILY, Number(next) || 0))
    setForm((current) => ({ ...current, [key]: value }))
  }

  function addVideo() {
    setForm((current) => {
      if (current.videos.length >= MAX_SLOTS_PER_FAMILY) return current
      return { ...current, videos: [...current.videos, { format: 'long' }] }
    })
  }

  function removeVideo(index) {
    setForm((current) => ({
      ...current,
      videos: current.videos.filter((_, i) => i !== index),
    }))
  }

  function setVideoFormat(index, format) {
    setForm((current) => ({
      ...current,
      videos: current.videos.map((video, i) => (i === index ? { ...video, format } : video)),
    }))
  }

  async function handleSave(e) {
    e.preventDefault()
    const parsed = parseMonthValue(startMonth)
    if (startMonth && !parsed) {
      toast('Pick a valid tracker start month', 'error')
      return
    }
    if (parsed && !weekOptions.some((row) => row.week === Number(startWeek))) {
      toast('Pick one of the four tracker start weeks', 'error')
      return
    }
    setSaving(true)
    try {
      const payload = {
        onboarding_date: onboardingDate.trim() || '',
        tracker_deliverables: slotsFromForm(form),
        ai_videos_started_from: aiVideosStartedFrom.trim() || null,
      }
      if (parsed) {
        payload.tracker_start_year = parsed.year
        payload.tracker_start_month = parsed.month
        payload.tracker_start_week = Number(startWeek)
      }
      const data = await api.updateClient(token, clientId, payload)
      patchUser({
        clients: data.clients,
        active_client_id: data.active_client_id,
        active_channel_id: data.active_channel_id,
      })
      toast('Deliverables saved. This month’s remaining weeks pick up the difference; next month uses the new monthly set. Past months stay as they were.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleMarkMissed() {
    const isConfirmed = await confirm({
      title: 'Mark past incomplete as did not track?',
      message:
        'This marks unfinished tracker cards in weeks that have already ended as did not track. It does not change the card stage.',
    })
    if (!isConfirmed) return
    setMarking(true)
    try {
      const data = await api.markWeeklyTrackerMissed(token, clientId)
      toast(
        `Marked ${data.marked_cards || 0} card(s) across ${data.marked_weeks || 0} week(s) as did not track`,
        'success',
      )
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setMarking(false)
    }
  }

  return (
    <>
      <ProfileTabs clientId={clientId} />

      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Deliverables' },
            ]}
          />
          <h1>Deliverables</h1>
          <p>
            Set how many tracker cards this client gets each month. Videos (long + short) split
            together across the four weeks (4 → 1-1-1-1, 6 → 1-2-1-2). If tracker start is week 1,
            the whole month applies. If they join in week 3, only the second half of that month
            counts. Past months stay as they were.
          </p>
        </div>
      </header>

      <form className="profile-form card animate-fade-in" onSubmit={handleSave}>
        <section className="profile-section">
          <h2>Videos</h2>
          <p className="profile-section-desc">
            Each video is its own tracker for the month. Choose long or short per video — short is a
            format, not a separate deliverable.
            {form.videos.length
              ? ` This month by week: ${weekShareCounts(form.videos.length).join('-')}.`
              : ''}
          </p>
          <div className="deliverable-slot-list">
            {form.videos.length === 0 ? (
              <p className="text-muted">No videos this month.</p>
            ) : null}
            {form.videos.map((video, index) => (
              <div key={`video-${index}`} className="deliverable-slot">
                <strong>Video {index + 1}</strong>
                <div className="deliverable-format-toggle">
                  <button
                    type="button"
                    className={video.format === 'long' ? 'is-on' : ''}
                    onClick={() => setVideoFormat(index, 'long')}
                  >
                    Long
                  </button>
                  <button
                    type="button"
                    className={video.format === 'short' ? 'is-on' : ''}
                    onClick={() => setVideoFormat(index, 'short')}
                  >
                    Short
                  </button>
                </div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => removeVideo(index)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={addVideo}
            disabled={form.videos.length >= MAX_SLOTS_PER_FAMILY}
          >
            + Add video
          </button>
        </section>

        <section className="profile-section">
          <h2>Other monthly deliverables</h2>
          <p className="profile-section-desc">
            Count is how many separate tracker cards are created for the month, then split across
            the four weeks.
          </p>
          <div className="deliverable-count-list">
            <CountRow
              label="Static posts"
              hint="Image posts for Facebook and Instagram"
              value={form.static_post}
              onChange={(value) => setCount('static_post', value)}
            />
            <CountRow
              label="Blogs"
              hint="Written articles for the website"
              value={form.blog}
              onChange={(value) => setCount('blog', value)}
            />
            <CountRow
              label="Paid ads"
              hint="Creatives, balance, next 2 weeks, and results with the client"
              value={form.paid_ads}
              onChange={(value) => setCount('paid_ads', value)}
            />
          </div>
        </section>

        <section className="profile-section">
          <h2>Onboarding date</h2>
          <p className="profile-section-desc">
            The day this client actually joined. Separate from when tracker work starts.
          </p>
          <div className="input-group">
            <label htmlFor="onboarding-date">Onboarding date</label>
            <input
              id="onboarding-date"
              type="date"
              value={onboardingDate}
              onChange={(e) => setOnboardingDate(e.target.value)}
            />
          </div>
        </section>

        <section className="profile-section">
          <h2>AI videos started from</h2>
          <p className="profile-section-desc">
            Monthly reports treat videos published on or after this month as AI/new content.
          </p>
          <div className="input-group">
            <label htmlFor="client-ai-start">AI videos started from</label>
            <input
              id="client-ai-start"
              type="month"
              value={aiVideosStartedFrom}
              onChange={(e) => setAiVideosStartedFrom(e.target.value)}
            />
          </div>
        </section>

        <section className="profile-section">
          <h2>Tracker start</h2>
          <p className="profile-section-desc">
            Tie a mid-month join to one of the four tracker weeks. Weeks before this start are not
            part of the tracker.
          </p>
          <div className="input-group">
            <label>Start month</label>
            <MonthPicker value={startMonth} onChange={applyStart} onClear={clearStart} />
            <span className="field-hint">
              Optional. Click the calendar to pick a month. Leave empty to keep every existing week
              visible.
            </span>
          </div>
          <div className="tracker-week-options">
            {weekOptions.map((row) => {
              const selected = Number(startWeek) === row.week
              return (
                <label
                  key={row.week}
                  className={`tracker-week-option${selected ? ' is-on' : ''}`}
                >
                  <input
                    type="radio"
                    name="tracker-start-week"
                    checked={selected}
                    disabled={!startMonth}
                    onChange={() => setStartWeek(row.week)}
                  />
                  <span>
                    <strong>Week {row.week}</strong>
                    <small>
                      {row.start}–{row.end}
                    </small>
                  </span>
                </label>
              )
            })}
          </div>
        </section>

        <div className="profile-form-actions" style={{ gap: '12px' }}>
          <button type="submit" className="btn btn-primary" disabled={saving || marking}>
            {saving ? (
              <>
                <i className="fa-solid fa-spinner fa-spin" /> Saving…
              </>
            ) : (
              <>
                <i className="fa-solid fa-floppy-disk" /> Save deliverables
              </>
            )}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleMarkMissed}
            disabled={saving || marking}
          >
            {marking ? (
              <>
                <i className="fa-solid fa-spinner fa-spin" /> Marking…
              </>
            ) : (
              <>
                <i className="fa-solid fa-flag" /> Mark past incomplete as did not track
              </>
            )}
          </button>
        </div>
      </form>
    </>
  )
}
