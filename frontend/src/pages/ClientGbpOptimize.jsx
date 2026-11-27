import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

function actionLabel(action) {
  if (action === 'REPLACE') return 'IMPROVE'
  return action || ''
}

function actionTone(action) {
  if (action === 'REPLACE') return 'improve'
  return String(action || '').toLowerCase()
}

function ScoreShift({ current, next }) {
  const from = Number(current)
  const to = Number(next)
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return null
  return (
    <div className="gbp-score-shift is-up">
      <span>Gravity completeness</span>
      <div>
        <strong className="is-from">{from}</strong>
        <i className="fa-solid fa-arrow-right" />
        <strong className="is-to">{to}</strong>
        <em>+{to - from}</em>
      </div>
    </div>
  )
}

function ScoreDial({ score }) {
  const value = Math.max(0, Math.min(100, Number(score) || 0))
  return (
    <div
      className="gbp-score-dial"
      style={{ background: `conic-gradient(var(--primary) ${value * 3.6}deg, var(--border-light) 0deg)` }}
      aria-label={`Completeness ${value} out of 100`}
    >
      <div>
        <strong>{value}</strong>
        <span>/100</span>
      </div>
    </div>
  )
}

export default function ClientGbpOptimize() {
  const { client, clientId, connected, activeLocation, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)
  const [description, setDescription] = useState('')
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')
  const [pickedServices, setPickedServices] = useState([])
  const [gaps, setGaps] = useState({ phone: '', website: '', appointment: '' })
  const [saving, setSaving] = useState('')
  const [pin, setPin] = useState({ latitude: '', longitude: '' })
  const [downloading, setDownloading] = useState(false)
  const notedError = useRef('')

  function toastOptimizeError(data) {
    if (data?.gaps_status === 'running') {
      notedError.current = ''
      return
    }
    const message = data?.last_error || ''
    if (!message || message === notedError.current) return
    notedError.current = message
    toast(message, 'error')
  }

  const audit = snapshot?.listing || null
  const running = snapshot?.gaps_status === 'running'
  const canDownload = Boolean(
    snapshot?.gaps_checked_at &&
      ((snapshot.service_recommendations || []).some((item) => item.action === 'ADD' || item.action === 'REPLACE') ||
        (snapshot.suggested_title || '').trim() ||
        (snapshot.suggested_description || '').trim()),
  )

  async function downloadProposal() {
    if (!activeLocation) return
    setDownloading(true)
    try {
      const blob = await api.gbpOptimizePdfBlob(token, clientId, activeLocation.location_id)
      const objectUrl = URL.createObjectURL(blob)
      const slug =
        String(activeLocation.title || client?.name || 'listing')
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '') || 'listing'
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `${slug}-gbp-recommendations.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      toast(err.message || 'PDF is not ready yet', 'error')
    } finally {
      setDownloading(false)
    }
  }

  function applySnapshot(data) {
    setSnapshot(data)
    setDescription(data?.suggested_description || '')
    setTitle(data?.suggested_title || '')
    setNote(data?.instruction || '')
    setGaps({
      phone: data?.listing?.fields?.phone || '',
      website: data?.listing?.fields?.website || '',
      appointment: data?.listing?.fields?.appointment || '',
    })
    setPickedServices((data?.listing?.services?.suggested || []).map((item) => item.name))
  }

  async function refreshListing({ force = true, includeSearchKeywords = true } = {}) {
    setLoading(true)
    try {
      const data = await api.gbpOptimizeRefresh(token, clientId, activeLocation.location_id, {
        force,
        include_search_keywords: includeSearchKeywords,
      })
      applySnapshot(data)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  async function runOptimize(instruction = note) {
    setLoading(true)
    try {
      const latitude = pin.latitude === '' ? null : Number(pin.latitude)
      const longitude = pin.longitude === '' ? null : Number(pin.longitude)
      const data = await api.gbpOptimizeRun(
        token,
        clientId,
        activeLocation.location_id,
        instruction,
        Number.isFinite(latitude) ? latitude : null,
        Number.isFinite(longitude) ? longitude : null,
      )
      applySnapshot(data)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!token || !connected || !activeLocation) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        let data = await api.gbpOptimizeGet(token, clientId, activeLocation.location_id)
        if (cancelled) return
        if (data?.gaps_status !== 'running') {
          try {
            data = await api.gbpOptimizeRefresh(token, clientId, activeLocation.location_id, {
              force: false,
              include_search_keywords: false,
            })
          } catch (err) {
            if (!data?.listing) throw err
            toast(err.message, 'error')
          }
        }
        if (cancelled) return
        applySnapshot(data)
        toastOptimizeError(data)
        const needsGaps = !data?.gaps_checked_at && data?.gaps_status !== 'running'
        if (needsGaps) await runOptimize(data?.instruction || '')
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
    // First open refreshes completeness from Google when the saved listing is older than 30s.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, connected, activeLocation?.location_id])

  useEffect(() => {
    if (!running || !token || !activeLocation) return undefined
    const timer = setInterval(async () => {
      try {
        const data = await api.gbpOptimizeGet(token, clientId, activeLocation.location_id)
        applySnapshot(data)
        toastOptimizeError(data)
      } catch {
        /* keep the last snapshot while the job is still marked running */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [running, token, clientId, activeLocation])

  const servicePayload = useMemo(() => {
    const current = audit?.services?.current || []
    const chosen = (audit?.services?.suggested || []).filter((item) => pickedServices.includes(item.name))
    const category = audit?.services?.primary_category || audit?.categories?.primary?.name || ''
    return [...current, ...chosen.map((item) => ({ displayName: item.name, description: '' }))]
      .filter((item) => item.displayName)
      .map((item) => ({
        freeFormServiceItem: {
          category,
          label: { displayName: item.displayName, description: item.description || '' },
        },
      }))
  }, [audit, pickedServices])

  async function logApply(entry) {
    try {
      await api.gbpLogApply(token, clientId, activeLocation.location_id, entry)
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function approve(kind) {
    if (!audit) return
    setSaving(kind)
    try {
      let updateMask = []
      let location = {}
      if (kind === 'phone') {
        updateMask = ['phoneNumbers']
        location = { phoneNumbers: { primaryPhone: gaps.phone } }
      } else if (kind === 'website') {
        updateMask = ['websiteUri']
        location = { websiteUri: gaps.website }
      } else if (kind === 'description') {
        const nextTitle = title.trim()
        const currentTitle = (audit?.title || activeLocation?.title || '').trim()
        updateMask = []
        location = {}
        if (nextTitle && nextTitle !== currentTitle) {
          updateMask.push('title')
          location.title = nextTitle
        }
        if (description.trim()) {
          updateMask.push('profile')
          location.profile = { description: description.trim() }
        }
        if (!updateMask.length) return
      } else if (kind === 'services') {
        updateMask = ['serviceItems']
        location = { serviceItems: servicePayload }
      } else if (kind === 'categories') {
        const suggestion = audit.categories?.suggestion
        if (!suggestion?.name) return
        updateMask = ['categories']
        location = {
          categories: {
            primaryCategory: { name: suggestion.name },
            additionalCategories: (audit.categories.additional || []).map((item) => ({ name: item.name })),
          },
        }
      }
      const saved = await api.gbpProfilePatch(
        token,
        clientId,
        activeLocation.location_id,
        updateMask,
        location,
        kind === 'appointment' ? { update: true, uri: gaps.appointment } : null,
      )
      if (kind === 'description') {
        const scored = await api.gbpOptimizeApplyScore(token, clientId, activeLocation.location_id, description, [])
        applySnapshot(scored)
        const currentTitle = (audit?.title || activeLocation?.title || '').trim()
        if (title.trim() && title.trim() !== currentTitle) {
          await logApply({ kind: 'title', before: currentTitle, after: title.trim(), summary: 'Updated the title' })
        }
        if (description.trim()) {
          await logApply({
            kind: 'description',
            before: audit?.description?.current || '',
            after: description.trim(),
            summary: 'Updated the description',
          })
        }
      }
      if (kind === 'categories') {
        await logApply({
          kind: 'category',
          before: audit?.categories?.primary?.displayName || '',
          after: audit?.categories?.suggestion?.displayName || '',
          summary: `Changed the category to ${audit?.categories?.suggestion?.displayName || 'a new category'}`,
        })
      }
      toast(saved.pending ? 'Saved. Google is still reviewing some edits.' : 'Updated on Google.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving('')
    }
  }

  function failed(sectionId, checkId) {
    const section = (audit?.sections || []).find((item) => item.id === sectionId)
    const check = (section?.checks || []).find((item) => item.id === checkId)
    return !!check && !check.ok
  }

  function searchLine(item) {
    const names = [item.proposed_name, item.current_name, ...(item.keywords || [])]
      .map((name) => String(name || '').trim().toLowerCase())
      .filter(Boolean)
    const row = (snapshot?.keywords || []).find((keyword) => names.includes(String(keyword.phrase || '').trim().toLowerCase()))
    const status = item.demand_status || row?.demand_status || ''
    const place = item.demand_location || row?.demand_location || ''
    const volume = item.volume ?? row?.volume
    const broader = item.broader_volume ?? row?.broader_volume
    let demand = 'monthly searches were not measured for this keyword'
    if (status === 'measured' && volume != null) {
      demand = `${volume} monthly searches in ${place || 'this city'} for this keyword`
    } else if (broader != null) {
      demand = `${broader} monthly searches in India for this keyword`
    } else if (volume != null) {
      demand = `${volume} monthly searches for this keyword`
    }
    const lead = item.action === 'ADD'
      ? 'This is not on the Google service list currently'
      : item.action === 'REPLACE'
        ? 'This is on the Google service list under another name'
        : 'This is already on the Google service list'
    const why = String(item.why || '').trim()
    return `${lead}, and ${demand}.${why ? ` ${why}` : ''}`
  }

  async function applyRecommendation(item) {
    if (!audit || !item) return
    const current = (audit.services?.current || []).map((service) => ({
      displayName: service.displayName,
      description: service.description || '',
    }))
    let next = current
    if (item.action === 'ADD') {
      next = [...current, { displayName: item.proposed_name, description: item.proposed_description || '' }]
    } else if (item.action === 'KEEP' || item.action === 'REPLACE' || item.action === 'IMPROVE') {
      next = current.map((service) => (
        service.displayName === item.current_name
          ? {
              displayName: item.proposed_name || service.displayName,
              description: item.proposed_description || service.description,
            }
          : service
      ))
      if (item.action === 'ADD' || (item.proposed_name && !current.some((service) => service.displayName === item.proposed_name) && item.rename)) {
        /* rename stays inside the map above */
      }
    }
    const category = audit?.services?.primary_category || audit?.categories?.primary?.name || ''
    const serviceItems = next.filter((service) => service.displayName).map((service) => ({
      freeFormServiceItem: {
        category,
        label: { displayName: service.displayName, description: service.description || '' },
      },
    }))
    setSaving(item.proposed_name || item.current_name || item.action)
    try {
      const saved = await api.gbpProfilePatch(
        token,
        clientId,
        activeLocation.location_id,
        ['serviceItems'],
        { serviceItems },
        null,
      )
      const added = item.action === 'ADD' && item.proposed_name ? [item.proposed_name] : []
      const scored = await api.gbpOptimizeApplyScore(token, clientId, activeLocation.location_id, '', added)
      applySnapshot(scored)
      const afterName = item.proposed_name || item.current_name || ''
      const beforeName = item.current_name || ''
      const existing = (audit.services?.current || []).find((service) => service.displayName === beforeName)
      await logApply({
        kind: 'service',
        before: [beforeName, existing?.description || ''].filter(Boolean).join(' — '),
        after: [afterName, item.proposed_description || ''].filter(Boolean).join(' — '),
        summary: item.action === 'ADD' ? `Added service: ${afterName}` : `Updated service: ${afterName}`,
      })
      toast(saved.pending ? 'Saved. Google is still reviewing some edits.' : 'Updated on Google.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving('')
    }
  }

  const potential = snapshot?.potential_score
  const currentTitle = (audit?.title || activeLocation?.title || '').trim()
  const titleUnchanged = title.trim().toLowerCase() === currentTitle.toLowerCase()

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Optimize"
        subtitle="A completeness check for this location, plus local searches this clinic is missing."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : (
        <div className="gbp-stack">
          {audit?.pending && (
            <p className="gbp-pending">Google has pending edits for this location. Changes may not be live yet.</p>
          )}

          <section className="gbp-panel">
            <div className="gbp-panel-head">
              <div>
                <h2>Listing completeness</h2>
                <p>The score and photos come from the saved Google listing.</p>
              </div>
              <button type="button" className="btn btn-secondary" onClick={refreshListing} disabled={loading || running}>
                <i className={`fa-solid ${loading && !running ? 'fa-spinner fa-spin' : 'fa-rotate'}`} />
                Refresh listing
              </button>
            </div>
          {!audit ? (
            <p className="text-muted">{loading ? 'Reading the listing…' : 'Refresh listing to score this clinic.'}</p>
          ) : (
          <>
          <section className="card gbp-score-card">
            <ScoreDial score={audit.score} />
            <div>
              <h2>{audit.score_label || 'Gravity completeness'}</h2>
              <p className="profile-section-desc">
                This score checks whether the listing is complete. It is not a Google ranking.
                {snapshot?.listing_checked_at ? ` Saved ${new Date(snapshot.listing_checked_at).toLocaleString()}.` : ''}
              </p>
            </div>
          </section>

          <div className="gbp-score-grid">
            {(audit.sections || []).map((section) => (
              <article key={section.id} className="card gbp-score-section">
                <div className="gbp-score-section-head">
                  <h3>{section.label}</h3>
                  <strong>{section.score}%</strong>
                </div>
                <div className="gbp-score-track" aria-hidden="true">
                  <div style={{ width: `${section.score}%` }} />
                </div>
                <ul>
                  {(section.checks || []).map((check) => (
                    <li key={check.id} className={check.ok ? 'is-ok' : ''}>
                      <i className={`fa-solid ${check.ok ? 'fa-circle-check' : 'fa-circle-exclamation'}`} />
                      <span>
                        <strong>{check.title}</strong>
                        {check.detail}
                      </span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>

          {failed('business', 'phone') && (
            <section className="card profile-form social-card">
              <h2>Phone</h2>
              <label className="gbp-field">
                <span>Current suggestion</span>
                <input value={gaps.phone} onChange={(event) => setGaps((prev) => ({ ...prev, phone: event.target.value }))} />
              </label>
              <div className="form-actions">
                <button type="button" className="btn btn-primary" disabled={saving === 'phone' || !gaps.phone.trim()} onClick={() => approve('phone')}>
                  {saving === 'phone' ? 'Updating…' : 'Approve and update on Google'}
                </button>
              </div>
            </section>
          )}

          {failed('business', 'website') && (
            <section className="card profile-form social-card">
              <h2>Website</h2>
              <label className="gbp-field">
                <span>Current suggestion</span>
                <input value={gaps.website} onChange={(event) => setGaps((prev) => ({ ...prev, website: event.target.value }))} />
              </label>
              <div className="form-actions">
                <button type="button" className="btn btn-primary" disabled={saving === 'website' || !gaps.website.trim()} onClick={() => approve('website')}>
                  {saving === 'website' ? 'Updating…' : 'Approve and update on Google'}
                </button>
              </div>
            </section>
          )}

          {failed('business', 'appointment') && (
            <section className="card profile-form social-card">
              <h2>Appointment link</h2>
              <label className="gbp-field">
                <span>Current suggestion</span>
                <input value={gaps.appointment} placeholder="https://" onChange={(event) => setGaps((prev) => ({ ...prev, appointment: event.target.value }))} />
              </label>
              <div className="form-actions">
                <button type="button" className="btn btn-primary" disabled={saving === 'appointment'} onClick={() => approve('appointment')}>
                  {saving === 'appointment' ? 'Updating…' : 'Approve and update on Google'}
                </button>
              </div>
            </section>
          )}

          {failed('business', 'hours') && (
            <section className="card profile-form social-card">
              <h2>Opening hours</h2>
              <p className="profile-section-desc">Hours are missing. Set them on the Profile page, then refresh the listing.</p>
              <Link className="btn btn-secondary" to={`/clients/${clientId}/gbp/profile`}>Edit hours</Link>
            </section>
          )}

          <section className="card profile-form social-card">
            <h2>Photos</h2>
            <p className="profile-section-desc">
              The photos on the Media page are real. This check only looks at four Google labels: Cover, Interior, Team, and At work.
              A photo saved as Additional, Exterior, or Profile stays on the listing, and it does not fill those four labels.
            </p>
            {(audit.photos?.present || []).length > 0 && (
              <p className="gbp-primary-line">
                On the listing: {(audit.photos.present || []).map((item) => item.label || item).join(', ')}
              </p>
            )}
            {(audit.photos?.missing || []).length === 0 ? (
              <p>Cover, interior, team, and at-work photos are on the listing.</p>
            ) : (
              <div className="gbp-chip-list">
                {audit.photos.missing.map((item) => (
                  <Link key={item.id} className="gbp-chip" to={`/clients/${clientId}/gbp/media`}>
                    Add {item.label}
                  </Link>
                ))}
              </div>
            )}
          </section>

          </>
          )}
          </section>

          <section className="gbp-panel">
            <div className="gbp-panel-head">
              <div>
                <h2>Search recommendations</h2>
                <p>Optimize looks up local searches, then suggests services and profile text.</p>
              </div>
              <div className="gbp-panel-actions">
                <button type="button" className="btn btn-primary" onClick={() => runOptimize(note)} disabled={loading || running || !activeLocation}>
                  <i className={`fa-solid ${running ? 'fa-spinner fa-spin' : 'fa-wand-magic-sparkles'}`} />
                  {running ? 'Optimizing…' : 'Optimize'}
                </button>
                {canDownload && (
                  <button type="button" className="btn btn-secondary" onClick={downloadProposal} disabled={downloading || running}>
                    <i className={`fa-solid ${downloading ? 'fa-spinner fa-spin' : 'fa-download'}`} />
                    {downloading ? 'Preparing…' : 'Download PDF'}
                  </button>
                )}
              </div>
            </div>
            <label className="gbp-field gbp-note">
              <span>Optional note for Optimize</span>
              <textarea
                rows={2}
                value={note}
                placeholder="Example: focus on kidney stones. We do not do implants."
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
          {audit && (
          <>
          <section className="card profile-form social-card">
            <h2>Recommendation for services</h2>
            <p className="profile-section-desc">Current services</p>
            <div className="gbp-chip-list">
              {(audit.services?.current || []).map((item) => (
                <span key={item.displayName} className="gbp-chip is-static">{item.displayName}</span>
              ))}
              {(audit.services?.current || []).length === 0 && <p className="text-muted">No services listed yet.</p>}
            </div>
            {(snapshot?.service_recommendations || []).filter((item) => item.action === 'ADD' || item.action === 'REPLACE').length === 0 ? (
              <p className="text-muted">{running ? 'Checking which services to add or improve…' : 'Optimize to see which services to add or improve.'}</p>
            ) : (
              <div className="gbp-service-table">
                {snapshot.service_recommendations.filter((item) => item.action === 'ADD' || item.action === 'REPLACE').map((item) => {
                  const tone = actionTone(item.action)
                  return (
                    <article key={`${item.action}-${item.current_name}-${item.proposed_name}`} className={`gbp-service-decision is-${tone}`}>
                      <div className={`gbp-service-action is-${tone}`}>{actionLabel(item.action)}</div>
                      <div className="gbp-rec-body">
                        {item.action === 'ADD' ? (
                          <p className="gbp-rec-name is-add"><strong>{item.proposed_name}</strong></p>
                        ) : (
                          <div className="gbp-rec-names">
                            <div className="gbp-rec-name is-current">
                              <small>On Google</small>
                              <strong>{item.current_name || 'Current service'}</strong>
                            </div>
                            <i className="fa-solid fa-arrow-right gbp-rec-arrow" />
                            <div className={`gbp-rec-name is-next is-${tone}`}>
                              <small>Improve to</small>
                              <strong>{item.proposed_name || item.current_name}</strong>
                            </div>
                          </div>
                        )}
                        <p className="gbp-rec-search">{searchLine(item)}</p>
                        {item.proposed_description && (
                          <p className="gbp-rec-search"><strong>Description.</strong> {item.proposed_description}</p>
                        )}
                        <ScoreShift current={item.current_score ?? audit.score} next={item.potential_score} />
                        {item.action === 'ADD' && (
                          <button type="button" className="btn btn-primary" disabled={saving === item.proposed_name} onClick={() => applyRecommendation(item)}>
                            {saving === item.proposed_name ? 'Updating…' : 'Add'}
                          </button>
                        )}
                        {item.action === 'REPLACE' && (
                          <button type="button" className="btn btn-primary" disabled={saving === (item.proposed_name || item.current_name)} onClick={() => applyRecommendation(item)}>
                            {saving === (item.proposed_name || item.current_name) ? 'Updating…' : 'Improve'}
                          </button>
                        )}
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>

          {(failed('categories', 'primary') || audit.categories?.suggestion) && (
          <section className="card profile-form social-card">
            <h2>Category</h2>
            <p className="gbp-primary-line">Primary: {audit.categories?.primary?.displayName || 'None'}</p>
            {audit.categories?.suggestion ? (
              <>
                <p>
                  Suggested primary: <strong>{audit.categories.suggestion.displayName}</strong>
                </p>
                {audit.categories.suggestion.reason && <p className="profile-section-desc">{audit.categories.suggestion.reason}</p>}
                <div className="form-actions">
                  <button type="button" className="btn btn-primary" disabled={saving === 'categories'} onClick={() => approve('categories')}>
                    {saving === 'categories' ? 'Updating…' : 'Use this category'}
                  </button>
                </div>
              </>
            ) : (
              <p className="text-muted">No category change suggested. You can still edit categories on the Profile page.</p>
            )}
          </section>
          )}

          <section className="card profile-form social-card">
            <h2>Suggested profile Details</h2>
            {running && <p className="text-muted">Checking searches around this clinic. This can take a few minutes.</p>}
            {snapshot?.last_error && <p className="gbp-pending">{snapshot.last_error}</p>}
            {(snapshot?.not_used || []).length > 0 && (
              <p className="text-muted">Not used: {snapshot.not_used.join(', ')} is not a confirmed service.</p>
            )}
            {snapshot?.last_error?.toLowerCase().includes('pin') && (
              <div className="gbp-search-row">
                <input
                  value={pin.latitude}
                  placeholder="Latitude"
                  onChange={(event) => setPin((prev) => ({ ...prev, latitude: event.target.value }))}
                />
                <input
                  value={pin.longitude}
                  placeholder="Longitude"
                  onChange={(event) => setPin((prev) => ({ ...prev, longitude: event.target.value }))}
                />
              </div>
            )}
            <div className="gbp-copy-compare">
              <label className="gbp-field">
                <span>Current title</span>
                <textarea rows={2} value={currentTitle} readOnly />
              </label>
              <i className="fa-solid fa-arrow-right gbp-copy-arrow" aria-hidden="true" />
              <label className="gbp-field">
                <span>Suggested title</span>
                <textarea
                  rows={2}
                  value={title}
                  readOnly={titleUnchanged}
                  onChange={(event) => setTitle(event.target.value)}
                />
                <small className="text-muted">
                  {titleUnchanged
                    ? 'Your title looks good. No change needed. Apply still saves the description.'
                    : 'Apply saves this name and the description.'}
                </small>
              </label>
            </div>
            <div className="gbp-copy-compare">
              <label className="gbp-field">
                <span>Current description</span>
                <textarea rows={6} value={audit.description?.current || ''} readOnly />
              </label>
              <i className="fa-solid fa-arrow-right gbp-copy-arrow" aria-hidden="true" />
              <label className="gbp-field">
                <span>Suggested description</span>
                <textarea rows={6} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
            </div>
            <ScoreShift current={potential?.current ?? audit.score} next={potential?.potential} />
            <div className="form-actions">
              <button type="button" className="btn btn-primary" disabled={saving === 'description' || (!description.trim() && title.trim() === currentTitle)} onClick={() => approve('description')}>
                {saving === 'description' ? 'Updating…' : 'Apply'}
              </button>
            </div>
          </section>

          </>
          )}
          </section>
        </div>
      )}
    </>
  )
}
