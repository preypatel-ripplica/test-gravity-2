/** Read profession presentation from the client payload. Doctor is the default. */

const DOCTOR_UI = {
  keyword_layout: 'priority_trends',
  title_pick: 'weighted_mapped',
  profile_label: 'Doctor profile',
}

export function presentationFromClient(client) {
  const caps = client?.capabilities || {}
  const ui = { ...DOCTOR_UI, ...(caps.ui || {}) }
  return {
    profession: client?.profession || 'doctor',
    usesGoogleTrends: caps.uses_google_trends !== false,
    usesVideoMapping: caps.uses_video_mapping !== false,
    usesRecommendationsTab: caps.uses_recommendations_tab !== false,
    usesFestivals: caps.uses_festivals !== false,
    usesMonthlyReport: caps.uses_monthly_report !== false,
    keywordLayout: ui.keyword_layout,
    titlePick: ui.title_pick,
    profileLabel: ui.profile_label,
    audienceNoun: ui.audience_noun || (client?.profession === 'creator' ? 'creator' : 'doctor'),
    aiRankedKeywords: ui.keyword_layout === 'ai_ranked',
    scoreRankTitles: ui.title_pick === 'score_rank',
  }
}

export function useClientPresentation(client) {
  return presentationFromClient(client)
}
