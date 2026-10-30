import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientPracticeDetails() {
  const { client, clientId } = useOutletContext()
  const { token, patchUser } = useAuth()
  const { toast, confirm } = useUI()
  const navigate = useNavigate()
  const isActive = client?.is_active !== false

  const [name, setName] = useState('')
  const [websiteUrl, setWebsiteUrl] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [designation, setDesignation] = useState('')
  const [saving, setSaving] = useState(false)
  const [scraping, setScraping] = useState(false)
  const [scrapeHint, setScrapeHint] = useState(null)

  useEffect(() => {
    if (!client || client.id !== clientId) return
    setName(client.name || '')
    setWebsiteUrl(client.website_url || '')
    setSpecialty(client.specialty || '')
    setDesignation(client.designation || '')
    setScrapeHint(null)
  }, [clientId, client?.id])

  async function handleScrape() {
    if (!websiteUrl.trim() && !specialty.trim() && !(client?.reference_youtube_channel || '').trim()) {
      toast('Enter a website URL or specialty first', 'error')
      return
    }
    setScraping(true)
    setScrapeHint(null)
    try {
      const data = await api.scrapeClientProfile(token, clientId, {
        website_url: websiteUrl.trim() || undefined,
        specialty: specialty.trim() || undefined,
        reference_youtube_channel: client?.reference_youtube_channel || undefined,
      })
      if (data.clients?.length) {
        patchUser({
          clients: data.clients,
          active_client_id: data.active_client_id,
          active_channel_id: data.active_channel_id,
        })
      }
      if (data.website_url) setWebsiteUrl(data.website_url)
      if (data.specialty) setSpecialty(data.specialty)
      setScrapeHint({
        title: data.page_title,
        snippet: data.openai_rationale || data.page_snippet,
        pages: data.pages_scraped,
      })
      toast(
        data.suggested_topics?.length
          ? `Saved practice details · ${data.suggested_topics.length} topic ideas ready in Keywords and topics`
          : 'Practice details saved',
        'success',
      )
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setScraping(false)
    }
  }

  async function patchClients(data) {
    patchUser({
      clients: data.clients,
      active_client_id: data.active_client_id,
      active_channel_id: data.active_channel_id,
      has_clients: (data.clients || []).length > 0,
    })
  }

  async function handleToggleActive() {
    const label = client?.name || 'this client'
    const nextActive = !isActive
    const isConfirmed = await confirm({
      title: nextActive ? 'Mark client as active?' : 'Mark client as inactive?',
      message: nextActive
        ? `Move "${label}" back to the Active tab on the clients home page?`
        : `Mark "${label}" as inactive? They will move to the Inactive tab on the clients home page. You can mark them active again later.`,
    })
    if (!isConfirmed) return

    try {
      const data = await api.updateClient(token, clientId, { is_active: nextActive })
      await patchClients(data)
      toast(nextActive ? `Client "${label}" is now active.` : `Client "${label}" marked inactive.`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function handleDeleteClient() {
    const label = client?.name || 'this client'
    const isConfirmed = await confirm({
      title: 'Delete client?',
      message: `Are you sure you want to delete "${label}"? They will be removed from Active and Inactive lists. Their data is kept in the database and is not permanently erased.`,
      isDanger: true,
    })
    if (!isConfirmed) return

    try {
      const data = await api.deleteClient(token, clientId)
      await patchClients(data)
      toast(`Client "${label}" deleted.`, 'success')
      navigate('/clients', { replace: true })
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function handleSave(e) {
    e.preventDefault()
    if (!name.trim()) {
      toast('Client name is required', 'error')
      return
    }
    setSaving(true)
    try {
      const data = await api.updateClient(token, clientId, {
        name: name.trim(),
        website_url: websiteUrl.trim(),
        specialty: specialty.trim(),
        designation: designation.trim(),
      })
      patchUser({
        clients: data.clients,
        active_client_id: data.active_client_id,
        active_channel_id: data.active_channel_id,
      })
      toast('Practice details saved', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
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
              { label: 'Practice details' },
            ]}
          />
          <h1>
            Practice details
            {!isActive && <span className="client-status-badge">Inactive</span>}
          </h1>
          <p>Name, website, specialty, and designation for this doctor.</p>
        </div>
      </header>

      {!isActive && (
        <div className="client-status-banner">
          <i className="fa-solid fa-circle-pause" />
          <p>
            This client is inactive and appears under the Inactive tab on the clients home page.
          </p>
        </div>
      )}

      <form className="profile-form card animate-fade-in" onSubmit={handleSave}>
        <section className="profile-section">
          <div className="input-group">
            <label htmlFor="client-name">Name</label>
            <input
              id="client-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Dr. Jane Smith"
              required
            />
          </div>

          <div className="input-group">
            <label htmlFor="client-website">Practice website</label>
            <div className="input-with-action">
              <input
                id="client-website"
                type="url"
                value={websiteUrl}
                onChange={(e) => setWebsiteUrl(e.target.value)}
                placeholder="https://www.exampleclinic.com"
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleScrape}
                disabled={scraping}
              >
                {scraping ? (
                  <>
                    <i className="fa-solid fa-spinner fa-spin" /> Scraping…
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-globe" /> Scrape
                  </>
                )}
              </button>
            </div>
            <span className="field-hint">
              Deep-scrapes the site for specialty signals and topic ideas. Review topics in Keywords
              and topics.
            </span>
          </div>

          {scrapeHint && (scrapeHint.title || scrapeHint.snippet) && (
            <div className="scrape-preview">
              {scrapeHint.title && <strong>{scrapeHint.title}</strong>}
              {scrapeHint.snippet && <p>{scrapeHint.snippet}</p>}
              {scrapeHint.pages > 0 && (
                <p className="scrape-pages">{scrapeHint.pages} page(s) analyzed</p>
              )}
            </div>
          )}

          <div className="input-group">
            <label htmlFor="client-specialty">Specialty</label>
            <input
              id="client-specialty"
              type="text"
              value={specialty}
              onChange={(e) => setSpecialty(e.target.value)}
              placeholder="e.g. Cardiology, Dermatology, Pediatrics"
            />
          </div>

          <div className="input-group">
            <label htmlFor="client-designation">Designation</label>
            <input
              id="client-designation"
              type="text"
              value={designation}
              onChange={(e) => setDesignation(e.target.value)}
              placeholder="e.g. Chairman, Pain Medicine & Palliative Care"
            />
          </div>

          <div style={{ marginTop: '24px' }}>
            <button type="submit" className="btn btn-primary" disabled={saving || scraping}>
              {saving ? (
                <>
                  <i className="fa-solid fa-spinner fa-spin" /> Saving…
                </>
              ) : (
                <>
                  <i className="fa-solid fa-floppy-disk" /> Save practice details
                </>
              )}
            </button>
          </div>
        </section>
      </form>

      <section className="profile-form card client-account-actions animate-fade-in">
        <h2>Account status</h2>
        <p className="profile-section-desc">
          Inactive clients stay in the database and show up on the Inactive tab. Deleting a client
          only hides them from the app — records are kept.
        </p>
        <div className="client-account-actions-row">
          <button type="button" className="btn btn-secondary" onClick={handleToggleActive}>
            {isActive ? (
              <>
                <i className="fa-solid fa-circle-pause" /> Mark as inactive
              </>
            ) : (
              <>
                <i className="fa-solid fa-circle-play" /> Mark as active
              </>
            )}
          </button>
          <button type="button" className="btn btn-danger" onClick={handleDeleteClient}>
            <i className="fa-solid fa-trash-can" /> Delete client
          </button>
        </div>
      </section>
    </>
  )
}
