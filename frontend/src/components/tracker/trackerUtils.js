export const CARD_TYPES = {
  long_video: 'long_video',
  short: 'short',
  static_post: 'static_post',
  blog: 'blog',
  paid_ads: 'paid_ads',
}

export const DELIVERABLE_FAMILIES = ['video', 'static_post', 'blog', 'paid_ads']
export const VIDEO_FORMATS = ['long', 'short']
export const MAX_SLOTS_PER_FAMILY = 24
export const WEEKS_IN_TRACKER_MONTH = 4
const REMAINDER_WEEK_INDEXES = [1, 3, 0, 2]

export const DEFAULT_DELIVERABLE_SLOTS = [
  { type: 'video', format: 'long' },
  { type: 'video', format: 'short' },
  { type: 'static_post' },
  { type: 'blog' },
]

const LEGACY_SLOT = {
  long_video: { type: 'video', format: 'long' },
  short: { type: 'video', format: 'short' },
  static_post: { type: 'static_post' },
  blog: { type: 'blog' },
  paid_ads: { type: 'paid_ads' },
  video: { type: 'video', format: 'long' },
}

export const MARKING_NONE = 'none'
export const MARKING_DID_NOT_TRACK = 'did_not_track'
export const MARKING_MISSED = MARKING_DID_NOT_TRACK

export function normalizeMarking(value) {
  const text = String(value || '').trim() || MARKING_NONE
  if (text === 'missed') return MARKING_DID_NOT_TRACK
  if (text === MARKING_NONE || text === MARKING_DID_NOT_TRACK) return text
  return MARKING_NONE
}

export function isDidNotTrack(value) {
  return normalizeMarking(value) === MARKING_DID_NOT_TRACK
}

export function cardStatus(card, weekContext) {
  if (isDidNotTrack(card?.marking)) {
    return { id: 'untracked', label: 'Did not track' }
  }
  const stages = stageList(card?.type)
  const stageId = card?.stage || 'planned'
  const idx = Math.max(0, stages.findIndex((stage) => stage.id === stageId))
  if (stages.length && idx >= stages.length - 1) {
    return { id: 'completed', label: 'Completed' }
  }
  const year = weekContext?.year
  const month = weekContext?.month
  const week = weekContext?.week
  if (
    year != null
    && month != null
    && week != null
    && isPastTrackerWeek(year, month, week)
  ) {
    return { id: 'late', label: 'Late' }
  }
  if (!stageId || stageId === 'planned' || idx <= 0) {
    return { id: 'not_started', label: 'Not started' }
  }
  return { id: 'in_progress', label: 'In progress' }
}

export function normalizeSlot(item) {
  if (typeof item === 'string') return LEGACY_SLOT[item] ? { ...LEGACY_SLOT[item] } : null
  if (!item || typeof item !== 'object') return null
  const family = String(item.type || '').trim()
  if (LEGACY_SLOT[family] && !DELIVERABLE_FAMILIES.includes(family)) {
    const mapped = { ...LEGACY_SLOT[family] }
    if (mapped.type === 'video') {
      mapped.format = VIDEO_FORMATS.includes(item.format) ? item.format : mapped.format
    }
    return mapped
  }
  if (!DELIVERABLE_FAMILIES.includes(family)) return null
  if (family === 'video') {
    return { type: 'video', format: VIDEO_FORMATS.includes(item.format) ? item.format : 'long' }
  }
  return { type: family }
}

export function normalizeDeliverables(list) {
  if (!Array.isArray(list)) return DEFAULT_DELIVERABLE_SLOTS.map((slot) => ({ ...slot }))
  const out = []
  const counts = {}
  for (const item of list) {
    const slot = normalizeSlot(item)
    if (!slot) continue
    counts[slot.type] = (counts[slot.type] || 0) + 1
    if (counts[slot.type] > MAX_SLOTS_PER_FAMILY) continue
    out.push(slot)
  }
  return out
}

export function slotToCardType(slot) {
  if (slot?.type === 'video') return slot.format === 'short' ? 'short' : 'long_video'
  return slot?.type || ''
}

export function cardTypesFromSlots(list) {
  return normalizeDeliverables(list).map(slotToCardType).filter(Boolean)
}

export function allowedCardTypes(list) {
  const seen = []
  for (const type of cardTypesFromSlots(list)) {
    if (!seen.includes(type)) seen.push(type)
  }
  return seen
}

export function weekShareCounts(total, weekCount = WEEKS_IN_TRACKER_MONTH) {
  const n = Math.max(0, Number(total) || 0)
  const weeks = Math.max(1, Number(weekCount) || WEEKS_IN_TRACKER_MONTH)
  const base = Math.floor(n / weeks)
  const rem = n % weeks
  const counts = Array.from({ length: weeks }, () => base)
  const extraAt = weeks === WEEKS_IN_TRACKER_MONTH ? REMAINDER_WEEK_INDEXES : [...Array(weeks).keys()].reverse()
  for (let i = 0; i < rem; i += 1) counts[extraAt[i % weeks]] += 1
  return counts
}

export const ADDABLE_CARD_TYPES = [
  { type: 'long_video', label: 'Long video' },
  { type: 'short', label: 'Short video' },
  { type: 'static_post', label: 'Static post' },
  { type: 'blog', label: 'Blog' },
]

export function isVideoCard(type) {
  return type === 'long_video' || type === 'short'
}

export function hasVideoDeliverable(list) {
  return normalizeDeliverables(list).some((slot) => slot.type === 'video')
}

export function hasStaticDeliverable(list) {
  return normalizeDeliverables(list).some((slot) => slot.type === 'static_post')
}

export function isBeforeTrackerStart(client, year, month, week) {
  const startYear = Number(client?.tracker_start_year)
  const startMonth = Number(client?.tracker_start_month)
  const startWeek = Number(client?.tracker_start_week)
  if (!startYear || !startMonth || !startWeek) return false
  if (year !== startYear) return year < startYear
  if (month !== startMonth) return month < startMonth
  return week < startWeek
}

export const TYPE_LABELS = {
  long_video: 'Long video',
  short: 'Short video',
  static_post: 'Static post',
  blog: 'Blog',
  paid_ads: 'Paid ads',
}

const TYPE_ORDER = Object.keys(TYPE_LABELS)

export function sortCardsByType(cards = []) {
  return [...cards].sort((left, right) => {
    const leftRank = TYPE_ORDER.indexOf(left?.type)
    const rightRank = TYPE_ORDER.indexOf(right?.type)
    const leftIndex = leftRank < 0 ? TYPE_ORDER.length : leftRank
    const rightIndex = rightRank < 0 ? TYPE_ORDER.length : rightRank
    if (leftIndex !== rightIndex) return leftIndex - rightIndex
    return (Number(left?.sort_order) || 0) - (Number(right?.sort_order) || 0)
  })
}

export const TYPE_PILL = {
  long_video: 'tracker-pill-blue',
  short: 'tracker-pill-pink',
  static_post: 'tracker-pill-gold',
  blog: 'tracker-pill-green',
  paid_ads: 'tracker-pill-violet',
}

export const LANG_LABELS = {
  hinglish: 'Hindi',
  arabic: 'Arabic',
  russian: 'Russian',
}

export const PLATFORM_LABELS = {
  youtube: 'YouTube',
  facebook: 'Facebook',
  instagram: 'Instagram',
  website: 'Website',
  other: 'Other',
}

export const STAGES = {
  long_video: [
    { id: 'planned', label: 'Planned' },
    { id: 'script_generated', label: 'Script generated' },
    { id: 'audio_generated', label: 'Audio received' },
    { id: 'video_edited', label: 'Video edited' },
    { id: 'shared_with_doctor', label: 'Shared with doctor' },
    { id: 'yt_metadata_generated', label: 'Metadata generated' },
    { id: 'posted', label: 'Posted' },
    { id: 'link_shared_with_doctor', label: 'Link shared with doctor' },
  ],
  short: [
    { id: 'planned', label: 'Planned' },
    { id: 'script_generated', label: 'Script generated' },
    { id: 'audio_generated', label: 'Audio received' },
    { id: 'video_edited', label: 'Video edited' },
    { id: 'shared_with_doctor', label: 'Shared with doctor' },
    { id: 'yt_metadata_generated', label: 'Metadata generated' },
    { id: 'posted', label: 'Posted' },
    { id: 'link_shared_with_doctor', label: 'Link shared with doctor' },
  ],
  static_post: [
    { id: 'planned', label: 'Planned' },
    { id: 'posted', label: 'Posted' },
    { id: 'link_shared_with_doctor', label: 'Link shared with doctor' },
  ],
  blog: [
    { id: 'planned', label: 'Planned' },
    { id: 'published', label: 'Published' },
    { id: 'link_shared_with_doctor', label: 'Link shared with doctor' },
  ],
  paid_ads: [
    { id: 'planned', label: 'Planned' },
    { id: 'creatives_checked', label: 'Creatives checked' },
    { id: 'balance_checked', label: 'Balance checked' },
    { id: 'next_2_weeks_planned', label: 'Next 2 weeks planned' },
    { id: 'results_discussed', label: 'Results discussed' },
    { id: 'link_shared_with_doctor', label: 'Link shared with doctor' },
  ],
}

export const DEFAULT_PLATFORMS = {
  long_video: ['youtube', 'facebook', 'instagram'],
  short: ['youtube', 'facebook', 'instagram'],
  static_post: ['facebook', 'instagram'],
  blog: ['website'],
  paid_ads: [],
}

export const LANG_ORDER = ['hinglish', 'arabic', 'russian']

export const VIDEO_DEFAULT_SLOTS = {
  hinglish: ['youtube', 'facebook', 'instagram'],
  arabic: ['youtube', 'facebook', 'instagram'],
  russian: ['youtube', 'facebook', 'instagram'],
}

export function displayLanguages(languages = []) {
  const found = LANG_ORDER.filter((lang) => languages.includes(lang))
  return found.length ? found : [...LANG_ORDER]
}

export function newId(prefix = 'id') {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID().slice(0, 12)}`
  }
  return `${prefix}-${Math.random().toString(16).slice(2, 14)}`
}

export function newUuid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const rand = Math.floor(Math.random() * 16)
    const value = char === 'x' ? rand : ((rand % 4) + 8)
    return value.toString(16)
  })
}

/** Ids for a custom-script save. A new custom script gets a fresh pair. An edit keeps the pair. */
export function manualScriptIdentity(card, payload) {
  const explicitNew = Boolean(payload && typeof payload === 'object' && !payload.itemId && !payload.topicId)
  if (explicitNew) {
    return { content_plan_item_id: newUuid(), topic_id: newUuid() }
  }
  const fromPayload = payload && typeof payload === 'object'
  const content_plan_item_id = (fromPayload ? payload.itemId : null) || card?.content_plan_item_id || null
  let topic_id = (fromPayload ? payload.topicId : null) || card?.topic_id || null
  if (content_plan_item_id && !topic_id) topic_id = newUuid()
  return { content_plan_item_id, topic_id }
}

/**
 * Copy script/topic ids from a save response onto the open card.
 * A newer local script row (different id) is left alone.
 * The same script row keeps the topic the server stored.
 */
export function savedScriptIdsConflict(local, saved) {
  if (!local || !saved) return false
  const localItem = local.content_plan_item_id || null
  const savedItem = saved.content_plan_item_id || null
  return Boolean(localItem && savedItem && localItem !== savedItem)
}

export function mergeSavedScriptIds(local, saved) {
  if (!local || !saved) return local
  const localItem = local.content_plan_item_id || null
  const savedItem = saved.content_plan_item_id || null
  if (localItem && savedItem && localItem !== savedItem) return local
  const content_plan_item_id = localItem || savedItem || null
  const topic_id = savedItem && saved.topic_id && (!localItem || localItem === savedItem)
    ? saved.topic_id
    : (local.topic_id || saved.topic_id || null)
  const idsSame = (
    content_plan_item_id === (local.content_plan_item_id || null)
    && topic_id === (local.topic_id || null)
  )
  const next = idsSame ? local : { ...local, content_plan_item_id, topic_id }
  // The save response is hydrated for this topic. Use it, but don't wipe titles
  // the page just generated if this response was built before they were stored.
  if ((next.topic_id || null) === (saved.topic_id || null) && saved.yt_locales) {
    const serverHasTitles = Object.values(saved.yt_locales).some((loc) => loc && String(loc.yt_title || '').trim())
    const localHasTitles = Object.values(next.yt_locales || {}).some((loc) => loc && String(loc.yt_title || '').trim())
    if (serverHasTitles || !localHasTitles) {
      if (saved.yt_locales !== next.yt_locales) return { ...next, yt_locales: saved.yt_locales }
    }
  }
  return next
}

export function emptyCard(type, sortOrder, isDefault = false) {
  return {
    id: newId('card'),
    type,
    title: '',
    started: true,
    collapsed: true,
    sort_order: sortOrder,
    stage: 'planned',
    marking: MARKING_NONE,
    is_default: isDefault,
    assets: { script_url: '', script_text: '', script_source: '', audio_url: '', video_url: '' },
    destinations: [],
    structure: {
      platforms: [...(DEFAULT_PLATFORMS[type] || [])],
      extra_slots: [],
      hidden_cells: [],
    },
    generated_post_ids: [],
    generated_posts: [],
    destination_post_ids: {},
    feedback_notes: [],
    doctor_notes: [],
    editor_notes: [],
    doctor_files: [],
    content_plan_item_id: null,
    topic_id: null,
    delay_reason: '',
    delay_proofs: [],
    delay_recorded_at: '',
    history: [],
    editor_id: '',
    editor_overridden: false,
    edit_hours: 0,
    planned_edit_date: '',
  }
}

export function calendarWeekDates(from = new Date()) {
  const day = new Date(from.getFullYear(), from.getMonth(), from.getDate())
  const monday = new Date(day)
  monday.setDate(day.getDate() - ((day.getDay() + 6) % 7))
  return Array.from({ length: 7 }, (_, index) => {
    const next = new Date(monday)
    next.setDate(monday.getDate() + index)
    return next
  })
}

export function isoDate(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function defaultEditHours(client, type = '') {
  const stored = type === 'short' ? client?.short_video_hours : client?.long_video_hours
  const parsed = Number(stored)
  if (parsed > 0) return parsed
  const name = String(client?.name || '').trim()
  if (/^dr\.?\b/i.test(name)) return 1
  if (String(client?.specialty || '').trim()) return 1
  if (String(client?.designation || '').trim()) return 1
  return 2
}

const HISTORY_CAP = 200
const HISTORY_COALESCE_MS = 180000
const ASSET_HISTORY_LABELS = {
  script_text: 'Script',
  script_url: 'Script file',
  audio_url: 'Audio',
  video_url: 'Video',
}

function cleanHistoryText(value) {
  return String(value || '').trim()
}

function shortHistoryText(value, limit = 80) {
  const text = cleanHistoryText(value)
  if (text.length <= limit) return text
  return `${text.slice(0, limit - 1)}…`
}

function stageHistoryLabel(type, stageId) {
  const match = stageList(type).find((row) => row.id === (stageId || 'planned'))
  if (match) return match.label
  return String(stageId || 'planned').replace(/_/g, ' ')
}

function destHistoryLabel(dest) {
  const platform = PLATFORM_LABELS[dest?.platform] || String(dest?.platform || 'Link')
  const lang = LANG_LABELS[dest?.language] || ''
  return lang ? `${platform} (${lang})` : platform
}

function noteIds(card, key) {
  return new Set((card?.[key] || []).map((row) => row?.id).filter(Boolean))
}

function fileMap(card, key) {
  const out = {}
  for (const row of card?.[key] || []) {
    const id = row?.id || row?.url
    if (id) out[id] = row
  }
  return out
}

function filledDestMap(card) {
  const out = {}
  for (const dest of card?.destinations || []) {
    const url = cleanHistoryText(dest?.url)
    if (!url) continue
    const key = dest?.id || `${dest?.language || ''}-${dest?.platform || ''}-${url}`
    out[key] = dest
  }
  return out
}

export function historyEvent(kind, label, { detail = '', by = '' } = {}) {
  return {
    id: newId('hist'),
    at: new Date().toISOString(),
    by,
    kind,
    label,
    detail: cleanHistoryText(detail),
  }
}

export function formatHistoryWhen(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function canCoalesceHistory(last, event) {
  if (!last || last.kind !== event.kind || event.kind !== 'title') return false
  if (cleanHistoryText(last.by) !== cleanHistoryText(event.by)) return false
  const lastAt = Date.parse(last.at || '')
  const nextAt = Date.parse(event.at || '')
  if (Number.isNaN(lastAt) || Number.isNaN(nextAt)) return false
  return Math.abs(nextAt - lastAt) <= HISTORY_COALESCE_MS
}

export function mergeCardHistory(base = [], events = [], by = '') {
  const history = [...(base || [])].filter((row) => row && row.label)
  for (const event of events || []) {
    if (!event?.label) continue
    const row = {
      ...event,
      id: event.id || newId('hist'),
      at: event.at || new Date().toISOString(),
      by: event.by || by,
      kind: event.kind || 'update',
      detail: cleanHistoryText(event.detail),
    }
    const last = history[history.length - 1]
    if (canCoalesceHistory(last, row)) {
      last.at = row.at
      last.detail = row.detail || last.detail || ''
      last.label = row.label || last.label
      continue
    }
    history.push(row)
  }
  return history.slice(-HISTORY_CAP)
}

export function diffCardHistory(previous, incoming) {
  const events = []
  if (!incoming) return events
  const isNew = !previous
  const before = previous || emptyCard(incoming.type, 0)
  if (isNew) {
    events.push(historyEvent('created', `${TYPE_LABELS[incoming.type] || 'Tracker'} card added`))
  }

  const beforeStage = before.stage || 'planned'
  const nextStage = incoming.stage || 'planned'
  if (beforeStage !== nextStage) {
    events.push(historyEvent('stage', `Status changed to ${stageHistoryLabel(incoming.type, nextStage)}`, {
      detail: `${stageHistoryLabel(incoming.type, beforeStage)} → ${stageHistoryLabel(incoming.type, nextStage)}`,
    }))
  }

  const beforeMarking = normalizeMarking(before.marking)
  const nextMarking = normalizeMarking(incoming.marking)
  if (beforeMarking !== nextMarking) {
    if (isDidNotTrack(nextMarking)) events.push(historyEvent('marking', 'Marked as did not track'))
    else if (beforeMarking === MARKING_DID_NOT_TRACK) events.push(historyEvent('marking', 'Cleared did not track'))
  }

  const beforeTitle = cleanHistoryText(before.title)
  const nextTitle = cleanHistoryText(incoming.title)
  if (beforeTitle !== nextTitle) {
    if (nextTitle && !beforeTitle) events.push(historyEvent('title', 'Title added', { detail: nextTitle }))
    else if (nextTitle) events.push(historyEvent('title', 'Title updated', { detail: nextTitle }))
    else events.push(historyEvent('title', 'Title cleared'))
  }

  const beforeAssets = before.assets || {}
  const nextAssets = incoming.assets || {}
  Object.entries(ASSET_HISTORY_LABELS).forEach(([key, label]) => {
    const prevValue = cleanHistoryText(beforeAssets[key])
    const nextValue = cleanHistoryText(nextAssets[key])
    if (prevValue === nextValue) return
    const detail = key === 'script_text' ? (nextValue ? 'Script text saved' : '') : shortHistoryText(nextValue)
    if (nextValue && !prevValue) events.push(historyEvent('asset', `${label} added`, { detail }))
    else if (nextValue) events.push(historyEvent('asset', `${label} updated`, { detail }))
    else events.push(historyEvent('asset', `${label} removed`))
  })

  if (cleanHistoryText(before.content_plan_item_id) !== cleanHistoryText(incoming.content_plan_item_id) && incoming.content_plan_item_id) {
    events.push(historyEvent('script', 'Script attached from content plan'))
  }

  const beforeDests = filledDestMap(before)
  const nextDests = filledDestMap(incoming)
  Object.entries(nextDests).forEach(([key, dest]) => {
    const url = cleanHistoryText(dest.url)
    const label = destHistoryLabel(dest)
    if (!beforeDests[key]) events.push(historyEvent('destination', `${label} link added`, { detail: shortHistoryText(url) }))
    else if (cleanHistoryText(beforeDests[key].url) !== url) {
      events.push(historyEvent('destination', `${label} link updated`, { detail: shortHistoryText(url) }))
    }
  })
  Object.entries(beforeDests).forEach(([key, dest]) => {
    if (!nextDests[key]) events.push(historyEvent('destination', `${destHistoryLabel(dest)} link removed`))
  })

  const addedFeedback = [...noteIds(incoming, 'feedback_notes')].filter((id) => !noteIds(before, 'feedback_notes').has(id))
  addedFeedback.forEach(() => events.push(historyEvent('note', 'Feedback note added')))
  const addedDoctor = [...noteIds(incoming, 'doctor_notes')].filter((id) => !noteIds(before, 'doctor_notes').has(id))
  addedDoctor.forEach(() => events.push(historyEvent('note', 'Doctor note added')))
  const addedEditor = [...noteIds(incoming, 'editor_notes')].filter((id) => !noteIds(before, 'editor_notes').has(id))
  addedEditor.forEach(() => events.push(historyEvent('note', 'Editor note added')))

  const beforeFiles = fileMap(before, 'doctor_files')
  const nextFiles = fileMap(incoming, 'doctor_files')
  Object.entries(nextFiles).forEach(([key, row]) => {
    if (!beforeFiles[key]) events.push(historyEvent('file', 'Doctor file added', { detail: cleanHistoryText(row.name) }))
  })

  if ((incoming.generated_post_ids || []).length > (before.generated_post_ids || []).length) {
    events.push(historyEvent('post', 'Generated post added'))
  }

  const beforeReason = cleanHistoryText(before.delay_reason)
  const nextReason = cleanHistoryText(incoming.delay_reason)
  if (beforeReason !== nextReason && nextReason) {
    events.push(historyEvent('delay', 'Delay reason added', { detail: shortHistoryText(nextReason, 120) }))
  }
  const beforeProofs = fileMap(before, 'delay_proofs')
  const nextProofs = fileMap(incoming, 'delay_proofs')
  const addedProofs = Object.entries(nextProofs).filter(([key]) => !beforeProofs[key]).map(([, row]) => row)
  if (addedProofs.length) {
    events.push(historyEvent('delay', 'Delay proof uploaded', {
      detail: addedProofs.map((row) => cleanHistoryText(row.name) || 'Proof').join(', '),
    }))
  }
  return events
}

export function applyCardHistory(previous, incoming, by = '') {
  const events = diffCardHistory(previous, incoming).map((event) => ({ ...event, by: event.by || by }))
  if (!events.length) return incoming
  return {
    ...incoming,
    history: mergeCardHistory(previous?.history || incoming.history || [], events, by),
  }
}

export function seedDestinations(card, languages = []) {
  const destinations = []
  if (card.type === 'paid_ads') return destinations
  if (isVideoCard(card.type)) {
    const langs = displayLanguages(languages)
    for (const language of langs) {
      for (const platform of VIDEO_DEFAULT_SLOTS[language] || ['youtube', 'facebook']) {
        destinations.push({ id: newId('dest'), language, platform, url: '' })
      }
    }
  } else {
    const platforms = card.structure?.platforms || DEFAULT_PLATFORMS[card.type] || []
    for (const platform of platforms) {
      destinations.push({ id: newId('dest'), platform, url: '' })
    }
  }
  return destinations
}

export function startCard(card, languages) {
  const destinations = card.destinations?.length ? card.destinations : seedDestinations(card, languages)
  return { ...card, started: true, destinations }
}

export function stageList(type) {
  return STAGES[type] || STAGES.blog
}

export function nextStage(card) {
  const stages = stageList(card.type)
  const idx = Math.max(0, stages.findIndex((s) => s.id === card.stage))
  if (idx >= stages.length - 1) return card
  return { ...card, stage: stages[idx + 1].id }
}

export function nextStageId(card) {
  const stages = stageList(card.type)
  const idx = Math.max(0, stages.findIndex((s) => s.id === card.stage))
  if (idx >= stages.length - 1) return null
  return stages[idx + 1].id
}

export function sectionForStage(card, stageId) {
  if (card.type === 'paid_ads') return 'paid_ads'
  if (card.type === 'blog') return 'destinations'
  if (card.type === 'static_post') return 'generate'
  if (!stageId || stageId === 'planned') return 'script'
  if (stageId === 'script_generated') return 'script'
  if (stageId === 'yt_metadata_generated') return 'yt_metadata'
  if (stageId === 'audio_generated') return 'video'
  if (stageId === 'video_edited') return 'video'
  if (stageId === 'shared_with_doctor') return 'doctor'
  if (stageId === 'posted') return 'publish'
  if (stageId === 'link_shared_with_doctor') return 'destinations'
  return 'destinations'
}

export function nextStageSection(card) {
  const stageId = nextStageId(card)
  if (!stageId) return null
  return sectionForStage(card, stageId)
}

export const COMPLETE_STAGE = 'link_shared_with_doctor'

export function hasTrackerScript(card) {
  const assets = card?.assets || {}
  if (String(assets.script_text || '').trim()) return true
  const url = String(assets.script_url || '').trim()
  return Boolean(url && !/^https?:\/\//i.test(url))
}

export function isSourceFileUrl(url) {
  const value = String(url || '').trim().toLowerCase()
  if (!value) return false
  return (
    value.includes('drive.google.com')
    || value.includes('docs.google.com')
    || value.includes('/uploaded_videos/')
  )
}

export function hasLiveDestination(card) {
  return (card?.destinations || []).some((dest) => {
    const url = String(dest?.url || '').trim()
    return Boolean(url) && !isSourceFileUrl(url)
  })
}

export function hasDoctorShare(card) {
  return Boolean((card?.doctor_notes || []).length || (card?.doctor_files || []).length)
}

export function hasVideoFile(card) {
  return Boolean(String(card?.assets?.video_url || '').trim())
}

export function hasAudioOrVideo(card) {
  const assets = card?.assets || {}
  return Boolean(String(assets.audio_url || '').trim() || String(assets.video_url || '').trim())
}

export function stageReached(card, stageId) {
  const stages = stageList(card?.type).map((row) => row.id)
  const current = Math.max(0, stages.indexOf(card?.stage || 'planned'))
  const target = stages.indexOf(stageId)
  return target >= 0 && current >= target
}

export function canMarkSharedWithDoctor(card) {
  return isVideoCard(card?.type)
}

export function canConfirmLinkShared(card) {
  const stages = stageList(card?.type).map((row) => row.id)
  return stages[stages.length - 1] === COMPLETE_STAGE
}

export function confirmChecklist(card) {
  if (isVideoCard(card?.type)) {
    return [
      { id: 'script_generated', label: 'Script generated', done: hasTrackerScript(card) },
      { id: 'video_edited', label: 'Video edited', done: hasVideoFile(card) },
      { id: 'shared_with_doctor', label: 'Shared with doctor', done: hasDoctorShare(card) },
      { id: 'yt_metadata_generated', label: 'Metadata generated', done: localeHasTitle(card?.yt_locales || {}) },
      { id: 'posted', label: 'Posted', done: hasLiveDestination(card) },
    ]
  }
  if (card?.type === 'blog') {
    return [{ id: 'published', label: 'Published', done: hasLiveDestination(card) }]
  }
  if (card?.type === 'static_post') {
    return [{ id: 'posted', label: 'Posted', done: hasLiveDestination(card) }]
  }
  return []
}

export function maybeAdvanceStage(card) {
  const stages = stageList(card.type).map((s) => s.id)
  const lastId = stages[stages.length - 1]
  if ((card.stage || '') === lastId) return { ...card, stage: lastId }
  let idx = Math.max(0, stages.indexOf(card.stage))
  const bump = (id) => {
    const next = stages.indexOf(id)
    if (next > idx) idx = next
  }
  if (isVideoCard(card.type)) {
    if (hasTrackerScript(card)) bump('script_generated')
    if (hasAudioOrVideo(card)) bump('audio_generated')
    if (hasVideoFile(card)) bump('video_edited')
    if (hasDoctorShare(card)) bump('shared_with_doctor')
    if (localeHasTitle(card.yt_locales || {})) bump('yt_metadata_generated')
    if (hasLiveDestination(card)) bump('posted')
  }
  if (hasLiveDestination(card)) {
    if (card.type === 'blog') bump('published')
    if (card.type === 'static_post') bump('posted')
  }
  if (stages[idx] === lastId) idx = Math.max(0, stages.length - 2)
  return { ...card, stage: stages[idx] }
}

export function isCompletedCard(card) {
  const stages = stageList(card?.type)
  if (!stages.length) return false
  return (card?.stage || '') === stages[stages.length - 1].id
}

export function stageCheckpointDone(card, stageId) {
  if (!card) return false
  if (stageId === 'planned') return Boolean(card.started)
  if (stageId === 'script_generated') return hasTrackerScript(card)
  if (stageId === 'yt_metadata_generated') return localeHasTitle(card.yt_locales || {})
  if (stageId === 'audio_generated') return hasAudioOrVideo(card)
  if (stageId === 'video_edited') return hasVideoFile(card)
  if (stageId === 'shared_with_doctor') return hasDoctorShare(card)
  if (stageId === 'posted' || stageId === 'published') return hasLiveDestination(card)
  if (stageId === COMPLETE_STAGE) return isCompletedCard(card)
  return stageReached(card, stageId)
}

export function hasDelayProof(card, proofRequired = false) {
  const reason = String(card?.delay_reason || '').trim()
  if (!reason) return false
  if (!proofRequired) return true
  const proofs = card?.delay_proofs || []
  return proofs.some((file) => String(file?.url || '').trim())
}

export function isPastTrackerWeek(year, month, week) {
  const today = todayParts()
  if (Number(year) !== today.year) return Number(year) < today.year
  if (Number(month) !== today.month) return Number(month) < today.month
  return Number(week) < today.week
}

export function needsDelayProof(prev, next, year, month, week, proofRequired = false) {
  if (!isPastTrackerWeek(year, month, week)) return false
  if (!isCompletedCard(next)) return false
  if (prev && isCompletedCard(prev)) return false
  if (hasDelayProof(next, proofRequired)) return false
  return true
}

export function isPastDueForDelay(dueDate) {
  const raw = String(dueDate || '').trim().slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return false
  const today = todayParts()
  const ranges = weekRanges(today.year, today.month)
  const current = ranges.find((row) => row.week === today.week) || ranges[0]
  const start = `${today.year}-${String(today.month).padStart(2, '0')}-${String(current.start).padStart(2, '0')}`
  return raw < start
}

export function nextStageLabel(card) {
  const stages = stageList(card.type)
  const idx = Math.max(0, stages.findIndex((s) => s.id === card.stage))
  if (idx >= stages.length - 1) return null
  return stages[idx + 1].label
}

export function weekRanges(year, month) {
  const last = new Date(year, month, 0).getDate()
  return [
    { week: 1, start: 1, end: Math.min(7, last) },
    { week: 2, start: 8, end: Math.min(14, last) },
    { week: 3, start: 15, end: Math.min(21, last) },
    { week: 4, start: 22, end: last },
  ].filter((row) => row.start <= last)
}

export function weekOfDate(date) {
  const d = date.getDate()
  if (d <= 7) return 1
  if (d <= 14) return 2
  if (d <= 21) return 3
  return 4
}

export function todayParts() {
  const now = new Date()
  return { year: now.getFullYear(), month: now.getMonth() + 1, week: weekOfDate(now), date: now }
}

export const EMPTY_WEEK_SUMMARY = { out: 0, total: 4, to_start: 4 }

export function monthLabel(year, month) {
  return new Date(year, month - 1, 1).toLocaleString('en-US', { month: 'long', year: 'numeric' })
}

export function formatChipRange(year, month, start, end) {
  const startDate = new Date(year, month - 1, start)
  const endDate = new Date(year, month - 1, end)
  const startName = startDate.toLocaleString('en-US', { month: 'short' })
  const endName = endDate.toLocaleString('en-US', { month: 'short' })
  if (startName === endName) return `${startName} ${start} – ${end}`
  return `${startName} ${start} – ${endName} ${end}`
}

export function destPlatforms(card) {
  if (isVideoCard(card.type)) return ['youtube', 'facebook', 'instagram']
  if (card.type === 'blog') return ['website']
  if (card.type === 'paid_ads') return []
  return ['facebook', 'instagram']
}

export function destRows(card, languages = []) {
  if (isVideoCard(card.type)) return displayLanguages(languages)
  return [null]
}

export function destsFor(card, language, platform) {
  return (card.destinations || []).filter((dest) => (
    dest.platform === platform && (language ? dest.language === language : !dest.language)
  ))
}

export function filledDestCount(card, languages = []) {
  const platforms = destPlatforms(card)
  const rows = destRows(card, languages)
  let total = 0
  let filled = 0
  for (const language of rows) {
    for (const platform of platforms) {
      const slots = destsFor(card, language, platform)
      total += Math.max(slots.length, 1)
      filled += slots.filter((dest) => (dest.url || '').trim()).length
    }
  }
  return { filled, total }
}

export function cardsSummary(cards) {
  const total = cards.length
  const out = cards.filter((card) => (
    (card.destinations || []).some((dest) => (dest.url || '').trim())
  )).length
  const toStart = cards.filter((card) => !card.started).length
  return { out, total, toStart }
}

export function serializableCard(card) {
  const { generated_posts, yt_locales, live_posts, template_topic, ...rest } = card
  return rest
}

export function templateTopic(card) {
  return String(card?.title || card?.template_topic || '').trim()
}

function postDay(value) {
  const raw = String(value || '').trim()
  return raw.length >= 10 ? raw.slice(0, 10) : ''
}

export function templateKind(card) {
  const stage = card?.stage || ''
  if (isVideoCard(card?.type)) {
    if (stage === 'script_generated' || stage === 'yt_metadata_generated' || stage === 'audio_generated') return 'script'
    if (stage === 'video_edited' || stage === 'shared_with_doctor') return 'video'
    if (stage === 'posted' || stage === 'link_shared_with_doctor') return 'posted'
    return null
  }
  if (card?.type === 'static_post' && (stage === 'posted' || stage === 'link_shared_with_doctor')) return 'posted'
  if (card?.type === 'blog' && (stage === 'published' || stage === 'link_shared_with_doctor')) return 'posted'
  return null
}

const LIVE_DEST_PLATFORMS = new Set(['youtube', 'instagram', 'facebook'])

function postLinkKey(platform, language) {
  const plat = String(platform || '').toLowerCase()
  const lang = String(language || '').toLowerCase()
  return plat === 'youtube' ? `youtube:${lang}` : plat
}

function considerPostLink(best, row, { allowEmptyDate = false } = {}) {
  const url = String(row?.url || '').trim()
  if (!url || isSourceFileUrl(url)) return
  const postedAt = String(row?.posted_at || '')
  if (!allowEmptyDate && !postDay(postedAt)) return
  const platform = String(row.platform || '').toLowerCase()
  const language = String(row.language || '').toLowerCase()
  if (!platform) return
  const key = postLinkKey(platform, language)
  const prev = best.get(key)
  if (!prev || postedAt > String(prev.posted_at || '')) {
    best.set(key, { platform, language, url, posted_at: postedAt })
  }
}

export function latestPostLinks(card) {
  const best = new Map()
  for (const row of card?.live_posts || []) considerPostLink(best, row)

  const destsByKey = new Map()
  for (const dest of card?.destinations || []) {
    const url = String(dest?.url || '').trim()
    const platform = String(dest?.platform || '').toLowerCase()
    if (!url || !platform || isSourceFileUrl(url)) continue
    const language = String(dest?.language || '').toLowerCase()
    const key = postLinkKey(platform, language)
    const bucket = destsByKey.get(key) || []
    bucket.push({ platform, language, url })
    destsByKey.set(key, bucket)
  }
  for (const [key, rows] of destsByKey) {
    const urls = [...new Set(rows.map((row) => row.url))]
    if (urls.length !== 1) {
      if (!best.has(key)) {
        const last = rows[rows.length - 1]
        best.set(key, { ...last, posted_at: '' })
      }
      continue
    }
    const row = rows[0]
    const prev = best.get(key)
    if (prev && prev.url === row.url) continue
    best.set(key, {
      platform: row.platform,
      language: row.language,
      url: row.url,
      posted_at: prev?.posted_at || '',
    })
  }
  return [...best.values()]
}

export function livePostsAfterDestChange(previous, nextCard, now = '') {
  const postedAt = String(now || new Date().toISOString())
  const prevDests = (previous?.destinations || []).filter((row) => row && typeof row === 'object')
  const nextDests = (nextCard?.destinations || []).filter((row) => row && typeof row === 'object')
  const prevById = new Map(prevDests.map((row) => [String(row.id || ''), row]))
  const nextById = new Map(nextDests.map((row) => [String(row.id || ''), row]))
  let live = (nextCard?.live_posts || previous?.live_posts || [])
    .filter((row) => row && typeof row === 'object')
    .map((row) => ({ ...row }))

  function samePost(row, platform, url) {
    return String(row.platform || '').toLowerCase() === platform && String(row.url || '').trim() === url
  }

  for (const prev of prevDests) {
    if (nextById.has(String(prev.id || ''))) continue
    const url = String(prev.url || '').trim()
    const platform = String(prev.platform || '').toLowerCase()
    if (!url || !LIVE_DEST_PLATFORMS.has(platform)) continue
    if (nextDests.some((row) => samePost(row, platform, url))) continue
    live = live.filter((row) => !samePost(row, platform, url))
  }

  for (const dest of nextDests) {
    const url = String(dest.url || '').trim()
    const platform = String(dest.platform || '').toLowerCase()
    const prev = prevById.get(String(dest.id || ''))
    const prevUrl = String(prev?.url || '').trim()
    if (!LIVE_DEST_PLATFORMS.has(platform)) continue
    if (!url || isSourceFileUrl(url)) {
      if (prevUrl) live = live.filter((row) => !samePost(row, platform, prevUrl))
      continue
    }
    const language = String(dest.language || '').toLowerCase()
    if (prevUrl && prevUrl !== url) {
      const idx = live.findIndex((row) => samePost(row, platform, prevUrl))
      const updated = { platform, language, url, posted_at: postedAt }
      if (idx >= 0) live[idx] = { ...live[idx], ...updated }
      else live.push(updated)
    } else if (!prevUrl && !live.some((row) => samePost(row, platform, url))) {
      live.push({ platform, language, url, posted_at: postedAt })
    }
  }
  return live
}

export function templateMessage(card, clientName) {
  const kind = templateKind(card)
  if (!kind) return ''
  const who = String(clientName || '').trim()
  const topic = templateTopic(card)
  const lines = [who ? `Hi ${who},` : 'Hi,', '']
  if (kind === 'script') {
    lines.push(topic ? `Your script is ready for "${topic}".` : 'Your script is ready.')
    return lines.join('\n')
  }
  if (kind === 'video') {
    lines.push(topic ? `Your video for "${topic}" is ready.` : 'Your video is ready.')
    const videoUrl = String(card?.assets?.video_url || '').trim()
    if (videoUrl) lines.push(videoUrl)
    return lines.join('\n')
  }
  if (card?.type === 'blog') {
    lines.push(topic ? `Your blog "${topic}" is live.` : 'Your blog is live.')
  } else if (card?.type === 'static_post') {
    lines.push(topic ? `Your static post for "${topic}" is live.` : 'Your static post is live.')
  } else {
    lines.push(topic ? `Your video for "${topic}" is posted.` : 'Your video is posted.')
  }
  const platformOrder = ['youtube', 'instagram', 'facebook', 'website']
  const links = latestPostLinks(card).sort((a, b) => {
    const platformDiff = platformOrder.indexOf(a.platform) - platformOrder.indexOf(b.platform)
    if (platformDiff) return platformDiff
    return LANG_ORDER.indexOf(a.language) - LANG_ORDER.indexOf(b.language)
  })
  if (!links.length) {
    return lines.join('\n')
  }
  for (const row of links) {
    const platform = PLATFORM_LABELS[row.platform] || row.platform || 'Link'
    const language = row.platform === 'youtube' && row.language
      ? ` (${LANG_LABELS[row.language] || row.language})`
      : ''
    lines.push(`${platform}${language}: ${row.url}`)
  }
  return lines.join('\n')
}

export const YT_LANGUAGE_OPTIONS = [
  { key: 'hinglish', label: 'Hinglish' },
  { key: 'arabic', label: 'Arabic' },
  { key: 'russian', label: 'Russian' },
]

export function localeHasTitle(locales = {}) {
  return Object.values(locales).some((loc) => loc && String(loc.yt_title || '').trim())
}

export function scriptTextValue(assets = {}) {
  if ((assets.script_text || '').trim()) return assets.script_text
  const legacy = assets.script_url || ''
  if (legacy && !/^https?:\/\//i.test(legacy)) return legacy
  return ''
}

export function parseTimecode(text) {
  const match = String(text || '').match(/\b(\d{1,2}:\d{2}(?::\d{2})?)\b/)
  return match ? match[1] : null
}
