/** Posting-mix include flags. Unready platforms stay off in the UI and preview. */

export const STANDARD_PLATFORMS = [
  { key: 'youtube', label: 'YouTube' },
  { key: 'instagram', label: 'Instagram' },
  { key: 'facebook', label: 'Facebook' },
]

export function platformReady(key, flags = {}) {
  if (key === 'youtube') return Boolean(flags.youtube_ready)
  if (key === 'instagram') return Boolean(flags.instagram_connected)
  if (key === 'facebook') return Boolean(flags.facebook_connected)
  return true
}

export function includeFromFlags(flags, wanted) {
  const source = wanted || { youtube: true, instagram: true, facebook: true }
  return {
    youtube: Boolean(source.youtube) && platformReady('youtube', flags),
    instagram: Boolean(source.instagram) && platformReady('instagram', flags),
    facebook: Boolean(source.facebook) && platformReady('facebook', flags),
  }
}

export function previewColumns(include, extras = []) {
  const standard = STANDARD_PLATFORMS.filter((row) => include?.[row.key]).map((row) => row.label)
  return [...standard, ...extras.map((row) => row.label)]
}
