export function isPlugMigrated(client) {
  return Boolean(String(client?.migrated_from_plug || '').trim())
}

export function isCreatorClient(client) {
  return String(client?.profession || '').toLowerCase() === 'creator' || isPlugMigrated(client)
}
