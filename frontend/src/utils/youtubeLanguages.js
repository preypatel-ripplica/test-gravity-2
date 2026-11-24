export const YOUTUBE_LANGUAGE_OPTIONS = [
  { key: 'hinglish', label: 'Hindi' },
  { key: 'english', label: 'English' },
  { key: 'bengali', label: 'Bengali' },
  { key: 'telugu', label: 'Telugu' },
  { key: 'marathi', label: 'Marathi' },
  { key: 'tamil', label: 'Tamil' },
  { key: 'gujarati', label: 'Gujarati' },
  { key: 'kannada', label: 'Kannada' },
  { key: 'malayalam', label: 'Malayalam' },
  { key: 'punjabi', label: 'Punjabi' },
  { key: 'odia', label: 'Odia' },
  { key: 'urdu', label: 'Urdu' },
  { key: 'arabic', label: 'Arabic' },
  { key: 'russian', label: 'Russian' },
]

export function languageKey(raw, label) {
  let text = String(raw || label || '').trim().toLowerCase()
  if (text === 'hindi' || text === 'hinglish') return 'hinglish'
  text = text.replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return text.slice(0, 40)
}

export function languageLabel(key, explicit) {
  if (explicit && String(explicit).trim()) return String(explicit).trim()
  return YOUTUBE_LANGUAGE_OPTIONS.find((row) => row.key === key)?.label || key
}
