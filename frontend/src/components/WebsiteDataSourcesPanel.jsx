import { useState } from 'react'
import { keywordTargetsText, parseKeywordTargets } from './websiteReportsShared'

export default function WebsiteDataSourcesPanel({
  loading,
  saving,
  settings,
  properties,
  connected,
  onSave,
  onUpdateSetting,
  onUpdateConversionEvent,
}) {
  const [expanded, setExpanded] = useState(false)

  const gscLabel =
    settings.gsc_property_url ||
    (properties.gsc_sites?.length ? 'Will auto-pick from site URL' : 'No Search Console property yet')
  const ga4Label =
    settings.ga4_property_id ||
    (properties.ga4_properties?.length
      ? properties.ga4_properties[0].display_name
      : 'No Analytics property detected yet')

  const siteHost = (() => {
    try {
      return settings.site_url ? new URL(settings.site_url).hostname : 'No site URL'
    } catch {
      return settings.site_url || 'No site URL'
    }
  })()

  const keywordCount = Array.isArray(settings.keyword_targets) ? settings.keyword_targets.length : 0

  return (
    <section className="access-panel card animate-fade-in website-data-sources" style={{ marginBottom: 24 }}>
      <div className="access-panel-head website-data-sources-head">
        <div>
          <h2>Data sources</h2>
          <p className="text-muted">
            Site URL, Search Console / GA4, keywords, PageSpeed, and conversion events.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setExpanded((value) => !value)}
        >
          <i className={`fa-solid fa-chevron-${expanded ? 'up' : 'down'}`} />{' '}
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>

      {!expanded ? (
        <div className="website-data-sources-summary">
          <div className="website-data-sources-chip">
            <span className="label">Brand</span>
            <strong title={settings.brand_name || siteHost}>
              {settings.brand_name || siteHost}
            </strong>
          </div>
          <div className="website-data-sources-chip">
            <span className="label">Site</span>
            <strong title={settings.site_url || ''}>{siteHost}</strong>
          </div>
          <div className="website-data-sources-chip">
            <span className="label">Google</span>
            <strong>{connected ? 'Connected' : 'Not connected'}</strong>
          </div>
          <div className="website-data-sources-chip">
            <span className="label">GSC</span>
            <strong title={gscLabel}>{settings.gsc_property_url || 'Not set'}</strong>
          </div>
          <div className="website-data-sources-chip">
            <span className="label">Keywords</span>
            <strong>{keywordCount}</strong>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded(true)}>
            Edit settings
          </button>
        </div>
      ) : loading ? (
        <div className="inline-loading">
          <i className="fa-solid fa-spinner fa-spin" /> Loading settings…
        </div>
      ) : (
        <form className="website-reports-form" onSubmit={onSave}>
          <div className="credentials-form-grid">
            <label>
              Brand name (on PDFs)
              <input
                value={settings.brand_name || ''}
                onChange={(event) => onUpdateSetting('brand_name', event.target.value)}
                placeholder="Jain Pain Clinic"
              />
            </label>
            <label>
              Site URL
              <input
                value={settings.site_url}
                onChange={(event) => onUpdateSetting('site_url', event.target.value)}
                placeholder="https://example.com"
              />
            </label>
            <label>
              GSC property
              <input value={gscLabel} readOnly />
            </label>
            <label>
              GA4 property
              <input value={ga4Label} readOnly />
            </label>
            <label>
              PageSpeed limit
              <input
                type="number"
                min="1"
                max="25"
                value={settings.pagespeed_page_limit}
                onChange={(event) => onUpdateSetting('pagespeed_page_limit', event.target.value)}
              />
            </label>
            <label>
              PageSpeed strategy
              <select
                value={settings.pagespeed_strategy}
                onChange={(event) => onUpdateSetting('pagespeed_strategy', event.target.value)}
              >
                <option value="mobile">Mobile</option>
                <option value="desktop">Desktop</option>
              </select>
            </label>
            <label className="website-reports-span-2">
              Fixed keyword list
              <textarea
                rows={6}
                value={keywordTargetsText(settings.keyword_targets)}
                onChange={(event) =>
                  onUpdateSetting('keyword_targets', parseKeywordTargets(event.target.value))
                }
                placeholder={'Back Pain Treatment Ahmedabad\nSciatica Treatment\nKnee Pain Specialist'}
              />
            </label>
          </div>

          <p className="text-muted" style={{ margin: '4px 0 16px' }}>
            Search Console and Analytics run independently. Connect Google, then save a site URL so
            properties can auto-pick.
          </p>

          <h3 className="website-reports-subhead">GA4 conversion event mapping</h3>
          <div className="credentials-form-grid">
            <label>
              Appointment bookings
              <input
                value={settings.conversion_events.appointment_bookings}
                onChange={(event) =>
                  onUpdateConversionEvent('appointment_bookings', event.target.value)
                }
                placeholder="appointment_booked"
              />
            </label>
            <label>
              Contact form submissions
              <input
                value={settings.conversion_events.contact_form_submissions}
                onChange={(event) =>
                  onUpdateConversionEvent('contact_form_submissions', event.target.value)
                }
                placeholder="generate_lead"
              />
            </label>
            <label>
              Phone call clicks
              <input
                value={settings.conversion_events.phone_call_clicks}
                onChange={(event) =>
                  onUpdateConversionEvent('phone_call_clicks', event.target.value)
                }
                placeholder="phone_click"
              />
            </label>
            <label>
              WhatsApp clicks
              <input
                value={settings.conversion_events.whatsapp_clicks}
                onChange={(event) =>
                  onUpdateConversionEvent('whatsapp_clicks', event.target.value)
                }
                placeholder="whatsapp_click"
              />
            </label>
          </div>

          <div className="website-reports-actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              <i className="fa-solid fa-floppy-disk" /> {saving ? 'Saving…' : 'Save trackers'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
