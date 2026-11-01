/** Domain keys from projects.access / auth.me clients[].domains */
export const DOMAINS = {
  VIDEOS: 'videos',
  SOCIALMEDIA: 'socialmedia',
  WEBSITE: 'website',
  WHATSAPPBOT: 'whatsappbot',
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
