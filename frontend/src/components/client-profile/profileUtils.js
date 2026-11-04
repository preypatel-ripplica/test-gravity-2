export const EDITOR_FIELD_ID = 'fld-video-editor'
export const EDITOR_FIELD_LABEL = 'Editor'
export const LONG_HOURS_FIELD_ID = 'fld-long-video-hours'
export const LONG_HOURS_FIELD_LABEL = 'Long video hours'
export const SHORT_HOURS_FIELD_ID = 'fld-short-video-hours'
export const SHORT_HOURS_FIELD_LABEL = 'Short video hours'

export const DEFAULT_PREFERENCE_SECTION_TITLES = [
  'Video Editing / Generation',
  'Meeting / Communication',
  'Assets & Learnings',
]

const DEFAULT_PREFERENCE_SECTION_LOOKUP = new Set(
  DEFAULT_PREFERENCE_SECTION_TITLES.map((title) => title.trim().toLowerCase()),
)

export function newProfileId(prefix = 'id') {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID().slice(0, 12)}`
  }
  return `${prefix}-${Math.random().toString(16).slice(2, 14)}`
}

export function isDefaultPreferenceSection(section) {
  if (!section) return false
  if (section.is_default) return true
  return DEFAULT_PREFERENCE_SECTION_LOOKUP.has((section.title || '').trim().toLowerCase())
}
