import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import { GbpConnectPrompt, GbpHeader, GbpPickLocation } from '../components/gbp/GbpChrome'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']

function timeValue(part) {
  if (!part) return '09:00'
  const hours = String(part.hours || 0).padStart(2, '0')
  const minutes = String(part.minutes || 0).padStart(2, '0')
  return `${hours}:${minutes}`
}

function parseTime(value) {
  const [hours, minutes] = (value || '09:00').split(':')
  return { hours: Number(hours) || 0, minutes: Number(minutes) || 0 }
}

function dateValue(part) {
  if (!part?.year) return ''
  const month = String(part.month).padStart(2, '0')
  const day = String(part.day).padStart(2, '0')
  return `${part.year}-${month}-${day}`
}

function parseDate(value) {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  return { year, month, day }
}

function hoursFromLocation(location) {
  const byDay = {}
  for (const period of location?.regularHours?.periods || []) {
    byDay[period.openDay] = period
  }
  return DAYS.map((day) => {
    const period = byDay[day]
    return {
      day,
      closed: !period,
      open: timeValue(period?.openTime),
      close: timeValue(period?.closeTime),
    }
  })
}

function servicesFromLocation(location) {
  return (location?.serviceItems || []).map((item) => {
    const label = item?.freeFormServiceItem?.label || item?.structuredServiceItem?.description || {}
    const display = label.displayName || item?.structuredServiceItem?.serviceTypeId || ''
    return { displayName: display, description: label.description || '' }
  })
}

function snapshot(form) {
  return JSON.stringify(form)
}

export default function ClientGbpProfile() {
  const { client, clientId, connected, activeLocation, loadingBundle } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [pending, setPending] = useState(false)
  const [address, setAddress] = useState('')
  const [baseline, setBaseline] = useState('')
  const [appointmentNote, setAppointmentNote] = useState('')
  const [query, setQuery] = useState('')
  const [categoryHits, setCategoryHits] = useState([])
  const [categoryNote, setCategoryNote] = useState('')
  const [searchingCategories, setSearchingCategories] = useState(false)
  const [form, setForm] = useState(null)

  useEffect(() => {
    if (!token || !connected || !activeLocation) return
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const data = await api.gbpProfileGet(token, clientId, activeLocation.location_id)
        if (cancelled) return
        const location = data.location || {}
        const next = {
          title: location.title || '',
          phone: location.phoneNumbers?.primaryPhone || '',
          website: location.websiteUri || '',
          appointment: data.appointment_uri || '',
          description: location.profile?.description || '',
          primary: location.categories?.primaryCategory
            ? {
                name: location.categories.primaryCategory.name,
                displayName: location.categories.primaryCategory.displayName,
              }
            : null,
          additional: (location.categories?.additionalCategories || []).map((item) => ({
            name: item.name,
            displayName: item.displayName,
          })),
          hours: hoursFromLocation(location),
          special: (location.specialHours?.specialHourPeriods || []).map((period) => ({
            date: dateValue(period.startDate),
            closed: !!period.closed,
            open: timeValue(period.openTime),
            close: timeValue(period.closeTime),
          })),
          services: servicesFromLocation(location),
        }
        setForm(next)
        setBaseline(snapshot(next))
        setAddress(data.address_readonly || '')
        setPending(!!data.pending)
        setAppointmentNote(data.appointment_error || '')
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

  function update(partial) {
    setForm((prev) => ({ ...prev, ...partial }))
  }

  async function searchCategories(event) {
    event.preventDefault()
    const term = query.trim()
    if (!term) {
      setCategoryHits([])
      setCategoryNote('Type a Google category, such as Urologist, then Search.')
      return
    }
    setSearchingCategories(true)
    setCategoryNote('')
    try {
      const data = await api.gbpCategorySearch(token, clientId, term)
      const hits = data.categories || []
      setCategoryHits(hits)
      if (!hits.length) {
        setCategoryNote('No Google categories match that. Try a shorter category name, such as Urologist, not a treatment name.')
      }
    } catch (err) {
      setCategoryHits([])
      setCategoryNote(err.message)
      toast(err.message, 'error')
    } finally {
      setSearchingCategories(false)
    }
  }

  function addCategory(hit, primary) {
    if (primary) {
      update({ primary: { name: hit.name, displayName: hit.display_name } })
      return
    }
    if (form.additional.some((item) => item.name === hit.name)) return
    update({ additional: [...form.additional, { name: hit.name, displayName: hit.display_name }] })
  }

  function locationPayload() {
    const periods = form.hours
      .filter((row) => !row.closed)
      .map((row) => ({
        openDay: row.day,
        closeDay: row.day,
        openTime: parseTime(row.open),
        closeTime: parseTime(row.close),
      }))
    const specialHourPeriods = form.special
      .filter((row) => row.date)
      .map((row) => {
        const date = parseDate(row.date)
        const period = { startDate: date, endDate: date, closed: row.closed }
        if (!row.closed) {
          period.openTime = parseTime(row.open)
          period.closeTime = parseTime(row.close)
        }
        return period
      })
    return {
      title: form.title,
      phoneNumbers: { primaryPhone: form.phone },
      websiteUri: form.website,
      profile: { description: form.description },
      categories: {
        ...(form.primary ? { primaryCategory: { name: form.primary.name } } : {}),
        additionalCategories: form.additional.map((item) => ({ name: item.name })),
      },
      regularHours: { periods },
      specialHours: { specialHourPeriods },
      serviceItems: form.services
        .filter((item) => item.displayName.trim())
        .map((item) => ({
          freeFormServiceItem: {
            category: form.primary?.name || '',
            label: { displayName: item.displayName.trim(), description: item.description || '' },
          },
        })),
    }
  }

  function changedMask() {
    if (!form || !baseline) return []
    const original = JSON.parse(baseline)
    const mask = []
    if (form.title !== original.title) mask.push('title')
    if (form.phone !== original.phone) mask.push('phoneNumbers')
    if (form.website !== original.website) mask.push('websiteUri')
    if (form.description !== original.description) mask.push('profile')
    if (JSON.stringify(form.primary) !== JSON.stringify(original.primary) || JSON.stringify(form.additional) !== JSON.stringify(original.additional)) {
      mask.push('categories')
    }
    if (JSON.stringify(form.hours) !== JSON.stringify(original.hours)) mask.push('regularHours')
    if (JSON.stringify(form.special) !== JSON.stringify(original.special)) mask.push('specialHours')
    if (JSON.stringify(form.services) !== JSON.stringify(original.services)) mask.push('serviceItems')
    return mask
  }

  function appointmentChanged() {
    if (!form || !baseline) return false
    return form.appointment !== JSON.parse(baseline).appointment
  }

  async function save(event) {
    event.preventDefault()
    const updateMask = changedMask()
    const appointmentUpdate = appointmentChanged()
    if (!updateMask.length && !appointmentUpdate) {
      toast('No profile changes to save.', 'info')
      return
    }
    setSaving(true)
    try {
      const data = await api.gbpProfilePatch(
        token,
        clientId,
        activeLocation.location_id,
        updateMask,
        locationPayload(),
        appointmentUpdate ? { update: true, uri: form.appointment } : null,
      )
      setPending(!!data.pending)
      setBaseline(snapshot(form))
      toast(data.pending ? 'Saved. Google is still reviewing some edits.' : 'Profile updated.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <GbpHeader
        client={client}
        clientId={clientId}
        title="Profile"
        subtitle="You can change name, phone, website, hours, and services here. The street address cannot be changed in this app — Google requires that in Google Business Profile."
        connected={connected}
      />
      {!connected ? (
        <GbpConnectPrompt clientId={clientId} />
      ) : !activeLocation && !loadingBundle ? (
        <GbpPickLocation clientId={clientId} />
      ) : loading || !form ? (
        <p className="text-muted">Loading profile…</p>
      ) : (
        <form className="gbp-stack" onSubmit={save}>
          {pending && (
            <p className="gbp-pending">Google has pending edits for this location. Changes may not be live yet.</p>
          )}
          <section className="card profile-form social-card">
            <h2>Business information</h2>
            <label className="gbp-field">
              <span>Name</span>
              <input value={form.title} onChange={(event) => update({ title: event.target.value })} />
            </label>
            <label className="gbp-field">
              <span>Phone</span>
              <input value={form.phone} onChange={(event) => update({ phone: event.target.value })} />
            </label>
            <label className="gbp-field">
              <span>Website</span>
              <input value={form.website} onChange={(event) => update({ website: event.target.value })} />
            </label>
            <label className="gbp-field">
              <span>Appointment link</span>
              <input
                value={form.appointment}
                placeholder="https://"
                onChange={(event) => update({ appointment: event.target.value })}
              />
            </label>
            {appointmentNote && <p className="gbp-pending">{appointmentNote}</p>}
            <label className="gbp-field">
              <span>Address (read only)</span>
              <input value={address} readOnly />
            </label>
            <label className="gbp-field">
              <span>Description</span>
              <textarea rows={5} value={form.description} onChange={(event) => update({ description: event.target.value })} />
            </label>
          </section>

          <section className="card profile-form social-card">
            <h2>Categories</h2>
            <p className="profile-section-desc">
              Google only accepts categories from its own list. Search a category Google uses, such as Urologist, then pick a result.
              Set primary replaces the one main category on the listing. Add keeps that main category and puts another one next to it.
              Press Save profile after you choose. Searching does not change Google until you save.
            </p>
            <p className="gbp-primary-line">Primary: {form.primary?.displayName || 'None'}</p>
            <div className="gbp-chip-list">
              {form.additional.map((item) => (
                <button
                  key={item.name}
                  type="button"
                  className="gbp-chip"
                  onClick={() => update({ additional: form.additional.filter((row) => row.name !== item.name) })}
                >
                  {item.displayName} ×
                </button>
              ))}
            </div>
            <div className="gbp-search-row">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search categories, for example Urologist"
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void searchCategories(event)
                  }
                }}
              />
              <button type="button" className="btn btn-secondary" onClick={searchCategories} disabled={searchingCategories}>
                {searchingCategories ? 'Searching…' : 'Search'}
              </button>
            </div>
            {categoryNote && <p className="profile-section-desc">{categoryNote}</p>}
            {categoryHits.map((hit) => (
              <div key={hit.name} className="gbp-row" style={{ marginTop: 8 }}>
                <span>{hit.display_name}</span>
                <span>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => addCategory(hit, true)}>
                    Set primary
                  </button>{' '}
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => addCategory(hit, false)}>
                    Add
                  </button>
                </span>
              </div>
            ))}
          </section>

          <section className="card profile-form social-card">
            <h2>Hours</h2>
            {form.hours.map((row, index) => (
              <div key={row.day} className="gbp-hours-row">
                <strong>{row.day.slice(0, 3)}</strong>
                <input
                  type="time"
                  value={row.open}
                  disabled={row.closed}
                  onChange={(event) => {
                    const hours = [...form.hours]
                    hours[index] = { ...row, open: event.target.value }
                    update({ hours })
                  }}
                />
                <input
                  type="time"
                  value={row.close}
                  disabled={row.closed}
                  onChange={(event) => {
                    const hours = [...form.hours]
                    hours[index] = { ...row, close: event.target.value }
                    update({ hours })
                  }}
                />
                <label>
                  <input
                    type="checkbox"
                    checked={row.closed}
                    onChange={(event) => {
                      const hours = [...form.hours]
                      hours[index] = { ...row, closed: event.target.checked }
                      update({ hours })
                    }}
                  />{' '}
                  Closed
                </label>
              </div>
            ))}
            <h3>Special hours</h3>
            {form.special.map((row, index) => (
              <div key={`${row.date}-${index}`} className="gbp-hours-row">
                <input
                  type="date"
                  value={row.date}
                  onChange={(event) => {
                    const special = [...form.special]
                    special[index] = { ...row, date: event.target.value }
                    update({ special })
                  }}
                />
                <input
                  type="time"
                  value={row.open}
                  disabled={row.closed}
                  onChange={(event) => {
                    const special = [...form.special]
                    special[index] = { ...row, open: event.target.value }
                    update({ special })
                  }}
                />
                <input
                  type="time"
                  value={row.close}
                  disabled={row.closed}
                  onChange={(event) => {
                    const special = [...form.special]
                    special[index] = { ...row, close: event.target.value }
                    update({ special })
                  }}
                />
                <label>
                  <input
                    type="checkbox"
                    checked={row.closed}
                    onChange={(event) => {
                      const special = [...form.special]
                      special[index] = { ...row, closed: event.target.checked }
                      update({ special })
                    }}
                  />{' '}
                  Closed
                </label>
                <button
                  type="button"
                  className="gbp-icon-btn"
                  aria-label="Delete special date"
                  onClick={() => update({ special: form.special.filter((_, item) => item !== index) })}
                >
                  <i className="fa-solid fa-trash" />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() =>
                update({
                  special: [...form.special, { date: '', closed: true, open: '09:00', close: '17:00' }],
                })
              }
            >
              Add special date
            </button>
          </section>

          <section className="card profile-form social-card">
            <h2>Services</h2>
            <p className="profile-section-desc">
              Each row is a service name plus an optional description. Type in Description, then Save profile. Google stores that text on the service.
            </p>
            {form.services.map((item, index) => (
              <div key={index} className="gbp-service-row">
                <input
                  value={item.displayName}
                  placeholder="Service name"
                  aria-label="Service name"
                  onChange={(event) => {
                    const services = [...form.services]
                    services[index] = { ...item, displayName: event.target.value }
                    update({ services })
                  }}
                />
                <input
                  value={item.description}
                  placeholder="Description"
                  aria-label="Service description"
                  onChange={(event) => {
                    const services = [...form.services]
                    services[index] = { ...item, description: event.target.value }
                    update({ services })
                  }}
                />
                <button
                  type="button"
                  className="gbp-icon-btn"
                  aria-label="Delete service"
                  onClick={() => update({ services: form.services.filter((_, itemIndex) => itemIndex !== index) })}
                >
                  <i className="fa-solid fa-trash" />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => update({ services: [...form.services, { displayName: '', description: '' }] })}
            >
              Add service
            </button>
          </section>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save profile'}
            </button>
          </div>
        </form>
      )}
    </>
  )
}
