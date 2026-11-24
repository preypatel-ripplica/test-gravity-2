import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const EMPTY_SCHEDULE = {
  frequency: 'off',
  selected_days: [],
  posts_per_day: 1,
  autopublish: false,
}

function FoldCard({ title, hint, items, empty, renderItem, action, panel }) {
  const [open, setOpen] = useState(true)
  const [page, setPage] = useState(0)
  const pageSize = 5
  const pages = Math.max(1, Math.ceil(items.length / pageSize))
  const safePage = Math.min(page, pages - 1)
  const visible = items.slice(safePage * pageSize, safePage * pageSize + pageSize)
  return (
    <section className="card profile-form social-card">
      <button type="button" className="gbp-fold-head" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span>
          <h2>{title}</h2>
          {hint && <p className="profile-section-desc">{hint}</p>}
        </span>
        <span className="gbp-fold-meta">
          {items.length}
          <i className={`fa-solid ${open ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
        </span>
      </button>
      {action && <div className="form-actions">{action}</div>}
      {panel}
      {open && (
        <div className="gbp-fold-body">
          {items.length === 0 ? empty : visible.map(renderItem)}
          {items.length > pageSize && (
            <div className="gbp-pager">
              <button type="button" className="btn btn-secondary btn-sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>Previous</button>
              <span>{safePage + 1} of {pages}</span>
              <button type="button" className="btn btn-secondary btn-sm" disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)}>Next</button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

const EMPTY = {
  summary: '',
  topic_type: 'STANDARD',
  cta_type: '',
  cta_url: '',
  event_title: '',
  event_start: '',
  event_end: '',
  coupon_code: '',
}

const POST_KINDS = [
  { id: 'STANDARD', label: 'Update', help: 'A normal post on the listing. No dates.' },
  { id: 'EVENT', label: 'Event', help: 'Something happening on set days, such as a camp or a talk.' },
  { id: 'OFFER', label: 'Offer', help: 'A deal or coupon, with a start and end date.' },
  { id: 'ALERT', label: 'Alert', help: 'A short notice, such as a closure or a change in hours.' },
]

function postKindLabel(kind) {
  return POST_KINDS.find((item) => item.id === kind)?.label || 'Update'
}

const GBP_SUMMARY_MAX = 500

function DraftSummaryEditor({
  draft,
  editing,
  editingText,
  saving,
  onEdit,
  onChange,
  onSave,
  onCancel,
}) {
  const saved = draft.summary || ''
  const count = editing ? editingText.length : saved.length
  const over = count > GBP_SUMMARY_MAX
  return (
    <>
      {editing ? (
        <>
          <textarea
            className="gbp-reply"
            rows={4}
            value={editingText}
            onChange={(event) => onChange(event.target.value)}
          />
          <div className={`gbp-char-count${over ? ' is-over' : ''}`}>
            {count}/{GBP_SUMMARY_MAX}
          </div>
          {over && (
            <p className="gbp-over-limit-note">
              This is over 500 characters. You can still save it. Google will receive a compressed version if you publish.
            </p>
          )}
        </>
      ) : (
        <p className="gbp-draft-summary">{saved || 'No text yet.'}</p>
      )}
      <div className="gbp-draft-edit-actions">
        {editing ? (
          <>
            <button type="button" className="btn btn-primary btn-sm" onClick={onSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onCancel} disabled={saving}>
              Cancel
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onEdit}>
            Edit
          </button>
        )}
      </div>
    </>
  )
}

export default function ClientGbpPosts() {
  const { client, clientId, connected, activeLocation, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [posts, setPosts] = useState([])
  const [drafts, setDrafts] = useState([])
  const [queue, setQueue] = useState([])
  const [draggedIdx, setDraggedIdx] = useState(null)
  const [editingDraftId, setEditingDraftId] = useState(null)
  const [editingText, setEditingText] = useState('')
  const [savingDraftId, setSavingDraftId] = useState(null)
  const [schedule, setSchedule] = useState(EMPTY_SCHEDULE)
  const [form, setForm] = useState(EMPTY)
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [drafting, setDrafting] = useState(false)
  const [draftKind, setDraftKind] = useState('STANDARD')
  const [draftEvent, setDraftEvent] = useState({ title: '', start: '', end: '', coupon: '' })
  const [zoom, setZoom] = useState(null)
  const [showRefs, setShowRefs] = useState(false)
  const [selectedRefs, setSelectedRefs] = useState([])
  const [edits, setEdits] = useState({})

  async function load() {
    if (!activeLocation) return
    setLoading(true)
    try {
      const [data, scheduleData, draftData] = await Promise.all([
        api.gbpPostsList(token, clientId, activeLocation.location_id),
        api.gbpPostSchedule(token, clientId, activeLocation.location_id),
        api.gbpPostDrafts(token, clientId, activeLocation.location_id),
      ])
      setPosts(data.posts || [])
      setSchedule({ ...EMPTY_SCHEDULE, ...(scheduleData.schedule || {}) })
      setDrafts(draftData.drafts || [])
      setQueue(draftData.queue || [])
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

  async function createPost(event) {
    event.preventDefault()
    try {
      let sourceUrl = null
      if (file) {
        const uploaded = await api.gbpPostImage(token, clientId, file)
        sourceUrl = uploaded.source_url
      }
      await api.gbpPostCreate(token, clientId, {
        location_id: activeLocation.location_id,
        ...form,
        cta_type: form.cta_type || null,
        cta_url: form.cta_url || null,
        source_url: sourceUrl,
      })
      setForm(EMPTY)
      setFile(null)
      toast('Post published to Google.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function saveSummary(post) {
    try {
      await api.gbpPostPatch(token, clientId, post.name, edits[post.name] ?? post.summary)
      toast('Post updated.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  function toggleDay(day) {
    setSchedule((prev) => {
      if (prev.selected_days.includes(day)) {
        return { ...prev, selected_days: prev.selected_days.filter((item) => item !== day) }
      }
      const limit = prev.frequency === 'once_a_week' ? 1 : 2
      const next = [...prev.selected_days, day].slice(-limit)
      return { ...prev, selected_days: DAYS.filter((item) => next.includes(item)) }
    })
  }

  async function saveSchedule(event) {
    event.preventDefault()
    try {
      const saved = await api.gbpSavePostSchedule(token, clientId, activeLocation.location_id, schedule)
      setSchedule({ ...EMPTY_SCHEDULE, ...(saved.schedule || {}) })
      toast('Post schedule saved.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function draftNow() {
    if ((draftKind === 'EVENT' || draftKind === 'OFFER') && !draftEvent.start) {
      toast('Add a start date for an event or an offer.', 'error')
      return
    }
    setDrafting(true)
    try {
      await api.gbpGeneratePostDrafts(token, clientId, activeLocation.location_id, 1, selectedRefs, {
        topic_type: draftKind,
        event_title: draftEvent.title,
        event_start: draftEvent.start,
        event_end: draftEvent.end,
        coupon_code: draftEvent.coupon,
      })
      toast('Drafts are ready to review.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setDrafting(false)
    }
  }

  function currentDraftSummary(draft) {
    if (editingDraftId === draft.id) return editingText
    return draft.summary || ''
  }

  function startEditDraft(draft) {
    setEditingDraftId(draft.id)
    setEditingText(draft.summary || '')
  }

  function cancelEditDraft() {
    setEditingDraftId(null)
    setEditingText('')
  }

  async function saveDraft(draft) {
    setSavingDraftId(draft.id)
    try {
      const result = await api.gbpSavePostDraft(token, clientId, draft.id, editingText)
      const saved = result.draft || { ...draft, summary: editingText }
      setDrafts((prev) => prev.map((row) => (row.id === draft.id ? saved : row)))
      setEditingDraftId(null)
      setEditingText('')
      if (result.over_limit) {
        toast('Draft saved. It is over 500 characters; Google will receive a compressed version if you publish.', 'error')
      } else {
        toast('Draft saved.', 'success')
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingDraftId(null)
    }
  }

  async function addToQueue(draft) {
    try {
      await api.gbpQueuePostDraft(token, clientId, draft.id, currentDraftSummary(draft))
      toast('Added to the publishing queue.', 'success')
      cancelEditDraft()
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function removeFromQueue(draft) {
    try {
      await api.gbpUnqueuePostDraft(token, clientId, draft.id)
      toast('Moved back to generated drafts.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function dropQueueItem(index) {
    if (draggedIdx === null || draggedIdx === index) {
      setDraggedIdx(null)
      return
    }
    const next = [...queue]
    const [moved] = next.splice(draggedIdx, 1)
    next.splice(index, 0, moved)
    setQueue(next)
    setDraggedIdx(null)
    try {
      const saved = await api.gbpReorderPostQueue(
        token,
        clientId,
        activeLocation.location_id,
        next.map((item) => item.id),
      )
      setQueue(saved.queue || next)
    } catch (err) {
      toast(err.message, 'error')
      await load()
    }
  }

  async function publishDraft(draft) {
    try {
      await api.gbpPublishPostDraft(token, clientId, draft.id, currentDraftSummary(draft))
      toast('Draft published to Google.', 'success')
      cancelEditDraft()
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function discardDraft(draft) {
    try {
      await api.gbpDiscardPostDraft(token, clientId, draft.id)
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function retryImage(draft) {
    try {
      await api.gbpRetryPostImage(token, clientId, draft.id)
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function remove(post) {
    try {
      await api.gbpPostDelete(token, clientId, post.name)
      toast('Post deleted.', 'success')
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
        title="Posts"
        subtitle="Publish timeline updates, events, and offers for the active location."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : (
        <div className="gbp-stack">
          <form className="card profile-form social-card" onSubmit={saveSchedule}>
            <h2>Post schedule</h2>
            <p className="profile-section-desc">
              On the days you choose, the daily job publishes the next posts in the queue. It does not write new posts.
              If the queue is empty and the switch below is on, it publishes the newest generated draft instead.
            </p>
            <label className="gbp-field">
              <span>Frequency</span>
              <select
                value={schedule.frequency}
                onChange={(event) => setSchedule((prev) => ({
                  ...prev,
                  frequency: event.target.value,
                  selected_days: event.target.value === 'once_a_week' || event.target.value === 'twice_a_week' ? prev.selected_days : [],
                }))}
              >
                <option value="off">Off</option>
                <option value="daily">Daily</option>
                <option value="weekdays">Weekdays</option>
                <option value="once_a_week">Once a week</option>
                <option value="twice_a_week">Twice a week</option>
              </select>
            </label>
            <label className="gbp-field">
              <span>Posts per day</span>
              <div className="gbp-stepper">
                <button
                  type="button"
                  onClick={() => setSchedule((prev) => ({ ...prev, posts_per_day: Math.max(1, Number(prev.posts_per_day || 1) - 1) }))}
                  disabled={Number(schedule.posts_per_day || 1) <= 1}
                  aria-label="Fewer posts per day"
                >
                  −
                </button>
                <span>{schedule.posts_per_day || 1}</span>
                <button
                  type="button"
                  onClick={() => setSchedule((prev) => ({ ...prev, posts_per_day: Math.min(10, Number(prev.posts_per_day || 1) + 1) }))}
                  disabled={Number(schedule.posts_per_day || 1) >= 10}
                  aria-label="More posts per day"
                >
                  +
                </button>
              </div>
              <small className="text-muted">Use minus and plus. The most on one day is 10.</small>
            </label>
            {(schedule.frequency === 'once_a_week' || schedule.frequency === 'twice_a_week') && (
              <div className="gbp-field">
                <span>{schedule.frequency === 'once_a_week' ? 'Day' : 'Days'}</span>
                <div className="gbp-day-picks">
                  {DAYS.map((day) => (
                    <button
                      key={day}
                      type="button"
                      className={schedule.selected_days.includes(day) ? 'is-active' : ''}
                      onClick={() => toggleDay(day)}
                    >
                      {day.slice(0, 3)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <label className="gbp-switch">
              <input
                type="checkbox"
                checked={!!schedule.autopublish}
                onChange={(event) => setSchedule((prev) => ({ ...prev, autopublish: event.target.checked }))}
              />
              <span className="gbp-switch-track" />
              <span className="gbp-switch-copy">
                <strong>When the queue is empty, publish the most recent generated draft</strong>
                <small className="text-muted">Queued posts always go first. This only runs if nothing is waiting in the queue.</small>
              </span>
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary btn-sm">Save schedule</button>
            </div>
          </form>

          <section className="card profile-form social-card">
            <div className="gbp-queue-head">
              <div>
                <h2>Publishing queue</h2>
                <p className="profile-section-desc">
                  Drag to change the order. The daily job publishes from the front of this list, up to the posts-per-day number.
                </p>
              </div>
              <span className="gbp-queue-count">{queue.length} scheduled</span>
            </div>
            {queue.length === 0 ? (
              <div className="gbp-queue-empty">
                <i className="fa-solid fa-list-check" />
                <p>Your queue is empty.</p>
                <p>Generate a post below, then add it to the queue.</p>
              </div>
            ) : (
              <div className="gbp-queue-grid">
                {queue.map((draft, index) => (
                  <article
                    key={draft.id}
                    className={`gbp-queue-card${draggedIdx === index ? ' is-dragging' : ''}`}
                    draggable
                    onDragStart={() => setDraggedIdx(index)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => dropQueueItem(index)}
                    onDragEnd={() => setDraggedIdx(null)}
                  >
                    <header>
                      <span><i className="fa-solid fa-grip-vertical" /> #{index + 1} in queue</span>
                      <span>{postKindLabel(draft.topic_type)}</span>
                    </header>
                    {draft.source_url ? (
                      <button
                        type="button"
                        className="gbp-draft-tile"
                        onClick={() => setZoom({ src: draft.source_url, label: postKindLabel(draft.topic_type) })}
                      >
                        <img src={draft.source_url} alt="" />
                      </button>
                    ) : (
                      <div className="gbp-draft-tile gbp-queue-missing"><i className="fa-regular fa-image" /></div>
                    )}
                    <p>{draft.summary || 'No text'}</p>
                    <div className="gbp-post-actions">
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => publishDraft(draft)}>Publish now</button>
                      <button type="button" className="gbp-icon-btn" aria-label="Remove from queue" onClick={() => removeFromQueue(draft)}>
                        <i className="fa-solid fa-trash" />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <FoldCard
            title="Generated drafts"
            hint="Generate a post here, then add it to the queue. Publish now sends it to Google immediately. Nothing is on Google until you publish it or the daily job reaches it."
            action={(
              <>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowRefs((value) => !value)}>
                  Choose references ({selectedRefs.length})
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={draftNow} disabled={drafting}>
                  {drafting ? 'Generating a post…' : 'generate one post'}
                </button>
              </>
            )}
            panel={(
              <div className="gbp-draft-setup">
                <label className="gbp-field">
                  <span>Post type</span>
                  <select value={draftKind} onChange={(event) => setDraftKind(event.target.value)}>
                    {POST_KINDS.map((item) => (
                      <option key={item.id} value={item.id}>{item.label}</option>
                    ))}
                  </select>
                  <small className="text-muted">{POST_KINDS.find((item) => item.id === draftKind)?.help}</small>
                </label>
                {(draftKind === 'EVENT' || draftKind === 'OFFER') && (
                  <div className="gbp-draft-dates">
                    <label className="gbp-field">
                      <span>{draftKind === 'OFFER' ? 'Offer name' : 'Event name'}</span>
                      <input
                        value={draftEvent.title}
                        placeholder={draftKind === 'OFFER' ? 'Kidney stone camp' : 'Free consultation camp'}
                        onChange={(event) => setDraftEvent((prev) => ({ ...prev, title: event.target.value }))}
                      />
                    </label>
                    <label className="gbp-field">
                      <span>Starts</span>
                      <input type="date" value={draftEvent.start} onChange={(event) => setDraftEvent((prev) => ({ ...prev, start: event.target.value }))} />
                    </label>
                    <label className="gbp-field">
                      <span>Ends</span>
                      <input type="date" value={draftEvent.end} onChange={(event) => setDraftEvent((prev) => ({ ...prev, end: event.target.value }))} />
                    </label>
                  </div>
                )}
                {draftKind === 'OFFER' && (
                  <label className="gbp-field">
                    <span>Coupon code</span>
                    <input value={draftEvent.coupon} onChange={(event) => setDraftEvent((prev) => ({ ...prev, coupon: event.target.value }))} />
                  </label>
                )}
                {showRefs ? (
              <div className="gbp-ref-grid">
                {posts.filter((post) => post.media?.[0]?.googleUrl || post.media?.[0]?.sourceUrl).length === 0 ? (
                  <div className="gbp-ref-empty">
                    <i className="fa-regular fa-image" />
                    <p>No posts with photos on Google yet.</p>
                  </div>
                ) : posts.filter((post) => post.media?.[0]?.googleUrl || post.media?.[0]?.sourceUrl).map((post) => {
                  const url = post.media?.[0]?.googleUrl || post.media?.[0]?.sourceUrl
                  const selected = selectedRefs.includes(url)
                  return (
                    <button
                      key={post.name}
                      type="button"
                      className={`gbp-ref-tile${selected ? ' is-selected' : ''}`}
                      onClick={() => setSelectedRefs((prev) => (
                        selected ? prev.filter((item) => item !== url) : [...prev, url]
                      ))}
                    >
                      <img src={url} alt="" />
                    </button>
                  )
                })}
              </div>
                ) : null}
              </div>
            )}
            items={drafts}
            empty={<p className="text-muted">No generated drafts yet.</p>}
            renderItem={(draft) => (
              <article key={draft.id} className="gbp-post gbp-fold-item">
                <div className="gbp-review-head">
                  <strong>{postKindLabel(draft.topic_type)} draft</strong>
                  <span className="gbp-post-state">Not on Google yet</span>
                </div>
                {draft.source_url && (
                  <button
                    type="button"
                    className="gbp-draft-tile"
                    onClick={() => setZoom({ src: draft.source_url, label: postKindLabel(draft.topic_type) })}
                  >
                    <img src={draft.source_url} alt="" />
                  </button>
                )}
                {draft.image_error && (
                  <p className="gbp-pending">
                    {draft.image_error}{' '}
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => retryImage(draft)}>Retry photo</button>
                  </p>
                )}
                <DraftSummaryEditor
                  draft={draft}
                  editing={editingDraftId === draft.id}
                  editingText={editingText}
                  saving={savingDraftId === draft.id}
                  onEdit={() => startEditDraft(draft)}
                  onChange={setEditingText}
                  onSave={() => saveDraft(draft)}
                  onCancel={cancelEditDraft}
                />
                <div className="gbp-post-actions">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => addToQueue(draft)}>Add to queue</button>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => publishDraft(draft)}>Publish now</button>
                  <button type="button" className="gbp-icon-btn" aria-label="Discard draft" onClick={() => discardDraft(draft)}>
                    <i className="fa-solid fa-trash" />
                  </button>
                </div>
              </article>
            )}
          />

          <form className="card profile-form social-card" onSubmit={createPost}>
            <h2>New post</h2>
            <label className="gbp-field">
              <span>Type</span>
              <select value={form.topic_type} onChange={(event) => setForm((prev) => ({ ...prev, topic_type: event.target.value }))}>
                <option value="STANDARD">Update</option>
                <option value="EVENT">Event</option>
                <option value="OFFER">Offer</option>
                <option value="ALERT">Alert</option>
              </select>
              <small className="text-muted">Update is a normal post. Choose Event or Offer only when the post has dates.</small>
            </label>
            <label className="gbp-field">
              <span>Text</span>
              <textarea rows={4} value={form.summary} onChange={(event) => setForm((prev) => ({ ...prev, summary: event.target.value }))} required />
            </label>
            {(form.topic_type === 'EVENT' || form.topic_type === 'OFFER') && (
              <>
                <label className="gbp-field">
                  <span>Event title</span>
                  <input value={form.event_title} onChange={(event) => setForm((prev) => ({ ...prev, event_title: event.target.value }))} />
                </label>
                <label className="gbp-field">
                  <span>Start</span>
                  <input type="date" value={form.event_start} onChange={(event) => setForm((prev) => ({ ...prev, event_start: event.target.value }))} required />
                </label>
                <label className="gbp-field">
                  <span>End</span>
                  <input type="date" value={form.event_end} onChange={(event) => setForm((prev) => ({ ...prev, event_end: event.target.value }))} />
                </label>
              </>
            )}
            {form.topic_type === 'OFFER' && (
              <label className="gbp-field">
                <span>Coupon code</span>
                <input value={form.coupon_code} onChange={(event) => setForm((prev) => ({ ...prev, coupon_code: event.target.value }))} />
              </label>
            )}
            <label className="gbp-field">
              <span>Button</span>
              <select value={form.cta_type} onChange={(event) => setForm((prev) => ({ ...prev, cta_type: event.target.value }))}>
                <option value="">None</option>
                <option value="BOOK">Book</option>
                <option value="ORDER">Order</option>
                <option value="LEARN_MORE">Learn more</option>
                <option value="SIGN_UP">Sign up</option>
                <option value="CALL">Call</option>
              </select>
            </label>
            {form.cta_type && (
              <label className="gbp-field">
                <span>Button URL</span>
                <input value={form.cta_url} onChange={(event) => setForm((prev) => ({ ...prev, cta_url: event.target.value }))} />
              </label>
            )}
            <label className="gbp-field">
              <span>Photo (optional, stored as a public URL)</span>
              <input type="file" accept="image/*" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            </label>
            <button type="submit" className="btn btn-primary">Publish post</button>
          </form>
          {zoom && (
            <div className="gbp-lightbox" role="dialog" aria-modal="true" aria-label={zoom.label}>
              <button type="button" className="gbp-lightbox-close" aria-label="Close" onClick={() => setZoom(null)}>
                <i className="fa-solid fa-xmark" />
              </button>
              <img src={zoom.src} alt={zoom.label} />
            </div>
          )}

          <FoldCard
            title="Posts on Google"
            hint="Updates already published on this location."
            items={loading ? [] : posts}
            empty={<p className="text-muted">{loading ? 'Loading posts…' : 'No posts on this location yet. A post you publish here will show in this list.'}</p>}
            renderItem={(post) => {
              const photo = post.media?.[0]?.googleUrl || post.media?.[0]?.sourceUrl
              const kind = { STANDARD: 'Update', EVENT: 'Event', OFFER: 'Offer', ALERT: 'Alert' }[post.topicType] || post.topicType || 'Post'
              return (
                <article key={post.name} className="gbp-post gbp-fold-item">
                  <div className="gbp-review-head">
                    <strong>{kind}</strong>
                    <span className="gbp-post-state">{post.state || 'Posted'}</span>
                  </div>
                  {photo && (
                    <button
                      type="button"
                      className="gbp-draft-tile"
                      onClick={() => setZoom({ src: photo, label: kind })}
                    >
                      <img src={photo} alt="" />
                    </button>
                  )}
                  <textarea
                    className="gbp-reply"
                    rows={3}
                    value={edits[post.name] ?? post.summary ?? ''}
                    onChange={(event) => setEdits((prev) => ({ ...prev, [post.name]: event.target.value }))}
                  />
                  <div className="gbp-post-actions">
                    {post.searchUrl && (
                      <a href={post.searchUrl} target="_blank" rel="noreferrer">View on Google</a>
                    )}
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => saveSummary(post)}>Save text</button>
                    <button type="button" className="gbp-icon-btn" aria-label="Delete post" onClick={() => remove(post)}>
                      <i className="fa-solid fa-trash" />
                    </button>
                  </div>
                </article>
              )
            }}
          />
        </div>
      )}
    </>
  )
}
