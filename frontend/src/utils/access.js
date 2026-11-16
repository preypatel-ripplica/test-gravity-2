/** Domain keys from projects.access / auth.me clients[].domains */
export const DOMAINS = {
  VIDEOS: 'videos',
  SOCIALMEDIA: 'socialmedia',
  WEBSITE: 'website',
  WHATSAPPBOT: 'whatsappbot',
}

/** Domains that unlock the weekly tracker (and which card types they own). */
export const TRACKER_DOMAINS = [DOMAINS.VIDEOS, DOMAINS.SOCIALMEDIA, DOMAINS.WEBSITE]

export const CARD_TYPE_DOMAIN = {
  long_video: DOMAINS.VIDEOS,
  short: DOMAINS.VIDEOS,
  paid_ads: DOMAINS.VIDEOS,
  static_post: DOMAINS.SOCIALMEDIA,
  blog: DOMAINS.WEBSITE,
}

export function clientDomains(client) {
  if (!client) return []
  if (client.is_owner) {
    return [DOMAINS.VIDEOS, DOMAINS.SOCIALMEDIA, DOMAINS.WEBSITE, DOMAINS.WHATSAPPBOT]
  }
  return Array.isArray(client.domains) ? client.domains : []
}

export function hasDomainAccess(client, domain) {
  return clientDomains(client).includes(domain)
}

export function hasAnyDomainAccess(client, domains = []) {
  return domains.some((domain) => hasDomainAccess(client, domain))
}

export function hasTrackerAccess(client) {
  return hasAnyDomainAccess(client, TRACKER_DOMAINS)
}

export function allowedTrackerCardTypes(client) {
  if (!client) return []
  if (client.is_owner) return Object.keys(CARD_TYPE_DOMAIN)
  const domains = new Set(clientDomains(client))
  return Object.entries(CARD_TYPE_DOMAIN)
    .filter(([, domain]) => domains.has(domain))
    .map(([type]) => type)
}

export function canAddTrackerCardType(client, type) {
  return allowedTrackerCardTypes(client).includes(type)
}
