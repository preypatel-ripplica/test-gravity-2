export const DEFAULT_TRACKER_CONFIG = {
  site_url: '',
  brand_name: '',
  gsc_property_url: '',
  ga4_property_id: '',
  conversion_events: {
    appointment_bookings: '',
    contact_form_submissions: '',
    phone_call_clicks: '',
    whatsapp_clicks: '',
  },
  pagespeed_page_limit: 10,
  pagespeed_strategy: 'mobile',
  keyword_targets: [],
}

export const OAUTH_MESSAGE_TYPE = 'website-google-oauth'
export const PERFORMANCE_MONTHS = 3

export function normalizeTrackedHost(url = '') {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

export function pickGscProperty(siteUrl, sites = []) {
  if (!sites.length) return ''
  const host = normalizeTrackedHost(siteUrl)
  if (!host) return sites[0].site_url || ''
  return (
    sites.find((site) => site.site_url === `sc-domain:${host}`)?.site_url ||
    sites.find((site) => normalizeTrackedHost(site.site_url) === host)?.site_url ||
    sites[0].site_url ||
    ''
  )
}

export function pickGa4Property(properties = []) {
  return properties[0]?.property_id || ''
}

export function keywordTargetsText(targets = []) {
  return Array.isArray(targets) ? targets.join('\n') : ''
}

export function parseKeywordTargets(text = '') {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

export function mergeSettings(config = {}) {
  return {
    ...DEFAULT_TRACKER_CONFIG,
    ...config,
    conversion_events: {
      ...DEFAULT_TRACKER_CONFIG.conversion_events,
      ...(config.conversion_events || {}),
    },
  }
}

export function formatNumber(value) {
  const num = Number(value) || 0
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(2)}m`
  if (num >= 1_000) return `${(num / 1_000).toFixed(num >= 10_000 ? 1 : 2)}k`
  return num.toLocaleString()
}

export function formatDateLabel(iso) {
  if (!iso) return ''
  const [, month, day] = String(iso).split('-')
  return `${day}/${month}`
}

export function shortPagePath(url = '') {
  try {
    const parsed = new URL(url)
    return parsed.pathname + parsed.search || '/'
  } catch {
    return url
  }
}
