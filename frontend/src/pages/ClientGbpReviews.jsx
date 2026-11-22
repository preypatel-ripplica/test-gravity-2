import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const STARS = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5 }
const LEAN = {
  positive: 'Mostly positive',
  mixed: 'Mixed',
  needs_attention: 'Needs attention',
}

function unansweredStats(reviews) {
  const unanswered = reviews.filter((review) => !review.reviewReply)
  let oldest = null
  for (const review of unanswered) {
    const time = new Date(review.createTime || review.updateTime || '')
    if (!Number.isNaN(time.getTime()) && (!oldest || time < oldest)) oldest = time
  }
  const oldestDays = oldest ? Math.max(0, Math.floor((Date.now() - oldest.getTime()) / 86400000)) : 0
  return { count: unanswered.length, oldest_days: oldestDays, loaded: reviews.length }
}

function formatWhen(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function starCount(review) {
  return STARS[review.starRating] || 0
}

export default function ClientGbpReviews() {
  const { client, clientId, connected, activeLocation, bundle, refreshGbp, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [reviews, setReviews] = useState([])
  const [pageToken, setPageToken] = useState(null)
  const [loading, setLoading] = useState(false)
  const [rating, setRating] = useState('')
  const [unansweredOnly, setUnansweredOnly] = useState(false)
  const [drafts, setDrafts] = useState([])
  const [waiting, setWaiting] = useState(null)
  const [themes, setThemes] = useState([])
  const [themeSummary, setThemeSummary] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [grouping, setGrouping] = useState(false)
  const [readingAll, setReadingAll] = useState(false)
  const [readProgress, setReadProgress] = useState(null)
  const [totalReviews, setTotalReviews] = useState(null)
  const [replies, setReplies] = useState({})
  const [settings, setSettings] = useState({
    auto_reply_mode: 'off',
    skip_one_star: true,
    skip_angry: true,
    agent_instructions: '',
  })

  const load = useCallback(async (tokenPage = null, append = false) => {
    if (!token || !activeLocation) return
    setLoading(true)
    let nextReviews = []
    try {
      const [data, draftData] = await Promise.all([
        api.gbpReviewsList(token, clientId, activeLocation.location_id, {
          rating: rating ? Number(rating) : null,
          unanswered_only: unansweredOnly,
          page_token: tokenPage,
        }),
        api.gbpReviewDrafts(token, clientId),
      ])
      setReviews((prev) => {
        nextReviews = append ? [...prev, ...(data.reviews || [])] : data.reviews || []
        return nextReviews
      })
      setTotalReviews(data.total_review_count ?? null)
      setPageToken(data.next_page_token || null)
      setDrafts(draftData.drafts || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, activeLocation, rating, unansweredOnly, toast])

  const groupThemes = useCallback(async (items) => {
    setGrouping(true)
    try {
      const grouped = await api.gbpReviewThemes(token, clientId, items)
      setThemes(grouped.themes || [])
      setThemeSummary(grouped.summary || '')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setGrouping(false)
    }
  }, [token, clientId, toast])

  const readAllReviews = useCallback(async () => {
    if (!token || !activeLocation) return
    setReadingAll(true)
    setReviewNote('')
    try {
      const data = await api.gbpReviewsAll(token, clientId, activeLocation.location_id)
      const all = data.reviews || []
      const total = data.total_review_count || all.length
      setWaiting(unansweredStats(all))
      setTotalReviews(total)
      setReadProgress({ loaded: all.length, total })
      if (!data.complete && total > all.length) {
        setReviewNote(`Google's review API sent ${all.length} of ${total}. The other reviews stay on Google and are not included in this response.`)
      }
      await groupThemes(all)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setReadingAll(false)
    }
  }, [token, clientId, activeLocation, toast, groupThemes])

  useEffect(() => {
    if (bundle) {
      setSettings({
        auto_reply_mode: bundle.auto_reply_mode || 'off',
        skip_one_star: bundle.skip_one_star !== false,
        skip_angry: bundle.skip_angry !== false,
        agent_instructions: bundle.agent_instructions || '',
      })
    }
  }, [bundle])

  useEffect(() => {
    if (connected && activeLocation) void load()
  }, [connected, activeLocation, load])

  useEffect(() => {
    if (connected && activeLocation) void readAllReviews()
    // Full read runs when the page opens, not when the star filter changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, activeLocation?.location_id])

  async function saveSettings(event) {
    event.preventDefault()
    try {
      await api.gbpSaveSettings(token, clientId, settings)
      await refreshGbp()
      toast('Auto-reply settings saved.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function publish(reviewName, text) {
    const comment = (text || '').trim()
    if (!comment) return
    try {
      await api.gbpReviewReply(token, clientId, reviewName, comment)
      toast('Reply published.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function removeReply(reviewName) {
    try {
      await api.gbpReviewReplyDelete(token, clientId, reviewName)
      toast('Reply deleted.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function publishDraft(draft) {
    try {
      await api.gbpPublishDraft(token, clientId, draft.id, replies[draft.id] ?? draft.reply)
      toast('Draft published to Google.', 'success')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const pending = drafts.filter((draft) => draft.status === 'pending_approval')

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Reviews"
        subtitle="Reply by hand, or let the app draft and publish replies."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : (
        <div className="gbp-stack">
          <form className="card profile-form social-card" onSubmit={saveSettings}>
            <h2 className="gbp-section-title">Automatic replies</h2>
            <p className="profile-section-desc">
              Google does not auto-reply. A scheduled job checks unanswered reviews and follows this setting.
            </p>
            <label className="gbp-field">
              <span>Agent instructions</span>
              <textarea
                className="gbp-reply"
                rows={4}
                value={settings.agent_instructions}
                placeholder="You can tell the agent how to respond. For example: mention the doctor by name, thank patients for specific details, and invite them to book a follow-up."
                onChange={(event) => setSettings((prev) => ({ ...prev, agent_instructions: event.target.value }))}
              />
              <small className="text-muted">Leave this empty to use the standard reply style.</small>
            </label>
            {['off', 'human_review', 'fully_automatic'].map((mode) => (
              <label key={mode} style={{ display: 'block', marginBottom: 6 }}>
                <input
                  type="radio"
                  name="auto_reply_mode"
                  checked={settings.auto_reply_mode === mode}
                  onChange={() => setSettings((prev) => ({ ...prev, auto_reply_mode: mode }))}
                />{' '}
                {mode === 'off' && 'Off'}
                {mode === 'human_review' && 'Automatic reply with human review'}
                {mode === 'fully_automatic' && 'Fully automatic'}
              </label>
            ))}
            <label style={{ display: 'block' }}>
              <input
                type="checkbox"
                checked={settings.skip_one_star}
                onChange={(event) => setSettings((prev) => ({ ...prev, skip_one_star: event.target.checked }))}
              />{' '}
              Skip 1-star reviews
            </label>
            <label style={{ display: 'block' }}>
              <input
                type="checkbox"
                checked={settings.skip_angry}
                onChange={(event) => setSettings((prev) => ({ ...prev, skip_angry: event.target.checked }))}
              />{' '}
              Skip angry reviews
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary btn-sm">Save settings</button>
            </div>
          </form>

          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={() => readAllReviews()} disabled={loading || readingAll}>
              {readingAll ? 'Summarising…' : 'Summarise all reviews'}
            </button>
          </div>
          {(readingAll || grouping) && (
            <div className="gbp-read-bar">
              <p>
                {grouping && !readingAll
                  ? 'Summarising all reviews…'
                  : `Summarising… ${readProgress?.loaded || 0} of ${readProgress?.total || totalReviews || 0}`}
              </p>
              <div className="gbp-read-track">
                <div style={{ width: `${Math.min(100, Math.round(((readProgress?.loaded || 0) / Math.max(readProgress?.total || totalReviews || 1, 1)) * 100))}%` }} />
              </div>
            </div>
          )}
          {(waiting || readingAll) && (
            <div className="gbp-insight-grid">
              <section className="card profile-form">
                <h2 className="gbp-section-title">What reviews keep saying</h2>
                {reviewNote && <p className="gbp-pending">{reviewNote}</p>}
                {themeSummary && <p>{themeSummary}</p>}
                {readingAll || grouping ? (
                  <p className="text-muted">Summarising every review Google will send.</p>
                ) : themes.length === 0 ? (
                  <p className="text-muted">No written comments to group yet.</p>
                ) : (
                  <div className="gbp-theme-list">
                    {themes.map((theme) => (
                      <div key={theme.id || theme.label} className="gbp-theme">
                        <span>
                          <strong>{theme.label}</strong>
                          {theme.advice && <em>{theme.advice}</em>}
                        </span>
                        <span>{theme.count} · {LEAN[theme.lean] || theme.lean}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
              <section className="card profile-form gbp-waiting-stat">
                <h2 className="gbp-section-title">Unanswered</h2>
                <strong>{readingAll ? '…' : waiting?.count ?? 0}</strong>
                <em>
                  {readingAll
                    ? `Summarising. ${readProgress?.loaded || 0} of ${readProgress?.total || totalReviews || 0} so far.`
                    : `Unanswered among ${waiting?.loaded ?? 0} reviews Google sent${totalReviews ? `. Google lists ${totalReviews} reviews in total.` : '.'}`}
                </em>
                <em>
                  {waiting?.count
                    ? waiting.oldest_days
                      ? `Oldest review has been waiting ${waiting.oldest_days} days`
                      : 'Oldest review was posted today'
                    : readingAll
                      ? 'Counting unanswered reviews…'
                      : 'Nothing in this list is waiting'}
                </em>
              </section>
            </div>
          )}

          {pending.length > 0 && (
            <section className="card profile-form">
              <h2>Waiting for approval</h2>
              {pending.map((draft) => (
                <article key={draft.id} className="gbp-review">
                  <p>{draft.comment}</p>
                  <textarea
                    rows={3}
                    value={replies[draft.id] ?? draft.reply ?? ''}
                    onChange={(event) => setReplies((prev) => ({ ...prev, [draft.id]: event.target.value }))}
                  />
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => publishDraft(draft)}>
                    Publish
                  </button>
                </article>
              ))}
            </section>
          )}

          <section className="card profile-form">
            <div className="gbp-review-toolbar">
              <label className="gbp-field">
                <span>Rating</span>
                <select value={rating} onChange={(event) => setRating(event.target.value)}>
                  <option value="">All ratings</option>
                  {[5, 4, 3, 2, 1].map((value) => (
                    <option key={value} value={value}>{value} stars</option>
                  ))}
                </select>
              </label>
              <label className="gbp-check">
                <input
                  type="checkbox"
                  checked={unansweredOnly}
                  onChange={(event) => setUnansweredOnly(event.target.checked)}
                />
                Unanswered only
              </label>
            </div>
            {loading && <p>Loading reviews…</p>}
            {reviews.map((review) => {
              const name = review.name
              const existing = review.reviewReply?.comment || ''
              return (
                <article key={name} className="gbp-review" style={{ marginTop: 12 }}>
                  <div className="gbp-review-head">
                    <strong>{review.reviewer?.displayName || 'Reviewer'}</strong>
                    <span>{'★'.repeat(starCount(review))}{'☆'.repeat(Math.max(0, 5 - starCount(review)))}</span>
                  </div>
                  <p>{review.comment || 'No written comment.'}</p>
                  <p className="text-muted">{formatWhen(review.updateTime || review.createTime)}</p>
                  {existing && <p className="gbp-existing-reply"><strong>Reply:</strong> {existing}</p>}
                  <textarea
                    className="gbp-reply"
                    rows={3}
                    placeholder="Write a reply"
                    value={replies[name] ?? existing}
                    onChange={(event) => setReplies((prev) => ({ ...prev, [name]: event.target.value }))}
                  />
                  <div className="form-actions">
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => publish(name, replies[name] ?? existing)}>
                      {existing ? 'Update reply' : 'Publish reply'}
                    </button>
                    {existing && (
                      <button type="button" className="btn btn-danger btn-sm" onClick={() => removeReply(name)}>
                        Delete reply
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
            {pageToken && (
              <button type="button" className="btn btn-secondary" onClick={() => load(pageToken, true)}>
                Load more
              </button>
            )}
          </section>
        </div>
      )}
    </>
  )
}
