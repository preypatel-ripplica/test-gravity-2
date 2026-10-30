export function newProfileId(prefix = 'id') {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID().slice(0, 12)}`
  }
  return `${prefix}-${Math.random().toString(16).slice(2, 14)}`
}
