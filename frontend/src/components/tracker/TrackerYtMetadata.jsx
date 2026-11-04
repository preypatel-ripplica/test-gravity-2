import { useCallback, useEffect, useMemo, useState } from 'react'
import CustomSelect from '../CustomSelect'
import api from '../../api'
import { YT_LANGUAGE_OPTIONS, localeHasTitle, maybeAdvanceStage } from './trackerUtils'

const PAGE_SIZE = 9

function languageLabel(key) {
  return YT_LANGUAGE_OPTIONS.find((o) => o.key === key)?.label || key
}

function generatedKeys(locales = {}) {
  return YT_LANGUAGE_OPTIONS.map((o) => o.key).filter((key) => locales[key]?.yt_title)
}

function allLanguageKeys() {
  return YT_LANGUAGE_OPTIONS.map((o) => o.key)
}

export default function TrackerYtMetadata({ card, weekContext, onChange }) {
  const { token, clientId, toast, channels = [], reloadWeek } = weekContext
  const [pickingLang, setPickingLang] = useState(false)
  const [generateLanguages, setGenerateLanguages] = useState(allLanguageKeys)
  const [generating, setGenerating] = useState(false)
  const [refining, setRefining] = useState(false)
  const [showRefs, setShowRefs] = useState(false)
  const [refChannelId, setRefChannelId] = useState(channels[0]?.id || '')
  const [videos, setVideos] = useState([])
  const [videoPage, setVideoPage] = useState(1)
  const [selectedRefIds, setSelectedRefIds] = useState([])
  const [previewLang, setPreviewLang] = useState('hinglish')
  const [refinePrompt, setRefinePrompt] = useState('')
  const [editingMeta, setEditingMeta] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [descriptionDraft, setDescriptionDraft] = useState('')
  const [tagsDraft, setTagsDraft] = useState('')
  const [savingDescription, setSavingDescription] = useState(false)
  const [refThumbFailed, setRefThumbFailed] = useState(false)
  const locales = card.yt_locales || {}
  const generated = generatedKeys(locales)
  const hasMeta = localeHasTitle(locales)
  const preview = locales[previewLang] || {}
  const scriptText = String(card.assets?.script_text || '').trim()
  const linked = Boolean(scriptText)
  const busy = generating || refining || savingDescription

  useEffect(() => {
    if (!refChannelId && channels[0]?.id) setRefChannelId(channels[0].id)
  }, [channels, refChannelId])

  useEffect(() => {
    if (generated.includes(previewLang)) return
    setPreviewLang(generated.includes('hinglish') ? 'hinglish' : generated[0] || 'hinglish')
  }, [generated, previewLang])

  useEffect(() => {
    setEditingMeta(false)
    setTitleDraft('')
    setDescriptionDraft('')
    setTagsDraft('')
  }, [previewLang, card.id])

  const loadVideos = useCallback(async (channelId) => {
    if (!token || !clientId || !channelId) return
    try {
      const data = await api.listVideos(token, clientId, channelId)
      const list = [...(data.videos || [])].sort((a, b) => String(b.published_at || '').localeCompare(String(a.published_at || '')))
      setVideos(list)
      setVideoPage(1)
    } catch (err) {
      toast(err.message, 'error')
    }
  }, [token, clientId, toast])

  useEffect(() => {
    if (showRefs && refChannelId) loadVideos(refChannelId)
  }, [showRefs, refChannelId, loadVideos])

  const visibleVideos = useMemo(() => videos.slice(0, videoPage * PAGE_SIZE), [videos, videoPage])

  function toggleLang(key) {
    setGenerateLanguages((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }

  function applyLocales(nextLocales, topicId) {
    onChange(maybeAdvanceStage({
      ...card,
      ...(topicId ? { topic_id: topicId } : {}),
      yt_locales: nextLocales || card.yt_locales || {},
    }))
  }

  async function refreshCardLocales(nextLocales, topicId) {
    if (topicId || (nextLocales && localeHasTitle(nextLocales))) applyLocales(nextLocales, topicId)
    try {
      await reloadWeek?.()
    } catch {
      // Locales may already be on the card from applyLocales.
    }
  }

  function cardFormat() {
    return card.type === 'short' ? 'Short' : 'Long'
  }

  async function handleGenerate(allowUnreferenced = false) {
    if (!linked) {
      toast('Add a script first.', 'error')
      return
    }
    if (generateLanguages.length === 0) {
      toast('Select at least one language.', 'error')
      return
    }
    const topicId = card.topic_id || (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : '')
    const continueWithoutReference = allowUnreferenced === true
    setGenerating(true)
    let nextLocales = null
    let unresolved = false
    try {
      const manualScript = card.assets?.script_source === 'manual' ? scriptText : ''
      const data = await api.generateYouTubeMetadata(token, clientId, {
        itemIds: card.content_plan_item_id ? [card.content_plan_item_id] : [],
        referenceVideoIds: continueWithoutReference ? [] : selectedRefIds,
        languages: generateLanguages,
        scriptOverride: manualScript || undefined,
        topicId: card.content_plan_item_id ? undefined : topicId,
        topicTitle: card.title,
        format: cardFormat(),
        allowUnreferencedThumbnail: continueWithoutReference,
      })
      if (data?.thumbnail_reference_failed) {
        unresolved = true
        setRefThumbFailed(true)
      } else {
        const item = (data.suggestions?.items || []).find((row) => row.id === card.content_plan_item_id)
        const keyword = (data.suggestions?.keyword_analysis || []).find((row) => row.topic_id === topicId)
        nextLocales = data.yt_locales || item?.yt_locales || keyword?.yt_locales || null
        setRefThumbFailed(false)
        setPickingLang(false)
        toast('YouTube metadata generated.', 'success')
      }
    } catch (err) {
      toast(err.message, 'error')
    }
    if (!unresolved) {
      await refreshCardLocales(nextLocales, card.content_plan_item_id ? card.topic_id : topicId)
    }
    setGenerating(false)
  }

  async function handleRefine() {
    if (!linked || !refinePrompt.trim()) {
      toast('Enter refine instructions.', 'error')
      return
    }
    const topicId = card.topic_id || (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : '')
    setRefining(true)
    let nextLocales = null
    try {
      const data = await api.refineYouTubeMetadata(token, clientId, {
        itemId: card.content_plan_item_id || undefined,
        userPrompt: refinePrompt,
        referenceVideoIds: selectedRefIds,
        language: previewLang,
        topicId,
        topicTitle: card.title,
        format: cardFormat(),
      })
      const item = (data.suggestions?.items || []).find((row) => row.id === card.content_plan_item_id)
      const keyword = (data.suggestions?.keyword_analysis || []).find((row) => row.topic_id === topicId)
      nextLocales = data.yt_locales || item?.yt_locales || keyword?.yt_locales || locales
      setRefinePrompt('')
      toast('Metadata refined.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
    await refreshCardLocales(nextLocales, topicId)
    setRefining(false)
  }

  const TITLE_MAX = 100
  const DESCRIPTION_MAX = 5000
  const TAGS_MAX = 500
  const tagList = tagsDraft.split(',').map((tag) => tag.trim()).filter(Boolean)
  const tagsLength = tagList.join(',').length
  const titleOver = titleDraft.length > TITLE_MAX
  const descriptionOver = descriptionDraft.length > DESCRIPTION_MAX
  const tagsOver = tagsLength > TAGS_MAX || tagList.some((tag) => tag.length > 100 || /[#<>]/.test(tag))
  const metaOver = titleOver || descriptionOver || tagsOver || !titleDraft.trim()

  function startMetaEdit() {
    setTitleDraft(preview.yt_title || '')
    setDescriptionDraft(preview.yt_description || '')
    setTagsDraft((preview.yt_tags || []).map((tag) => String(tag).replace(/#/g, '')).join(', '))
    setEditingMeta(true)
  }

  async function handleSaveDescription() {
    if (!card.topic_id) {
      toast('Choose a generated script first.', 'error')
      return
    }
    if (metaOver) {
      toast('Shorten the title, description, or tags before saving.', 'error')
      return
    }
    setSavingDescription(true)
    let nextLocales = null
    try {
      const data = await api.updateYouTubeDescription(token, clientId, {
        topicId: card.topic_id,
        language: previewLang,
        title: titleDraft.trim(),
        description: descriptionDraft,
        tags: tagList,
      })
      nextLocales = data.yt_locales || null
      setEditingMeta(false)
      toast('Metadata saved.', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
    await refreshCardLocales(nextLocales)
    setSavingDescription(false)
  }

  return (
    <section className="tracker-script-slot tracker-yt-meta">
      <div className="tracker-script-slot-head">
        <span className="tracker-kicker">Metadata</span>
        {linked ? (
          <div className="tracker-script-slot-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={busy}
              onClick={() => setShowRefs((v) => !v)}
            >
              Choose reference ({selectedRefIds.length})
            </button>
            {!pickingLang ? (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy}
                onClick={() => {
                  setGenerateLanguages(allLanguageKeys())
                  setPickingLang(true)
                }}
              >
                {hasMeta ? 'Regenerate metadata' : 'Generate metadata'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {!linked ? (
        <p className="tracker-hint">Add a script first, then generate metadata here.</p>
      ) : null}

      {showRefs && (
        <div className="tracker-ref-grid-wrap">
          {channels.length > 1 && (
            <CustomSelect
              value={refChannelId}
              ariaLabel="Reference channel"
              onChange={setRefChannelId}
              options={channels.map((ch) => ({ value: ch.id, label: ch.title || ch.id }))}
            />
          )}
          <p className="tracker-hint">If you pick none, the newest 3 thumbnails are used, and the newest 3 descriptions of the same format are used as examples.</p>
          <div className="tracker-ref-grid">
            {visibleVideos.map((video) => {
              const selected = selectedRefIds.includes(video.id)
              return (
                <button
                  type="button"
                  key={video.id}
                  className={`tracker-ref-tile${selected ? ' selected' : ''}`}
                  onClick={() => setSelectedRefIds(
                    selected ? selectedRefIds.filter((id) => id !== video.id) : [...selectedRefIds, video.id],
                  )}
                >
                  <img src={video.thumbnail_url} alt={video.title || ''} />
                </button>
              )
            })}
          </div>
          {videos.length > visibleVideos.length && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setVideoPage((n) => n + 1)}>
              Load more
            </button>
          )}
        </div>
      )}

      {pickingLang && (
        <div className="tracker-lang-picker">
          <div className="tracker-lang-picker-head">
            <strong>Languages to generate</strong>
            <button
              type="button"
              className="tracker-text-btn"
              onClick={() => setGenerateLanguages(
                generateLanguages.length === YT_LANGUAGE_OPTIONS.length
                  ? []
                  : allLanguageKeys(),
              )}
            >
              {generateLanguages.length === YT_LANGUAGE_OPTIONS.length ? 'Clear all' : 'Select all'}
            </button>
          </div>
          <div className="lang-picker-list">
            {YT_LANGUAGE_OPTIONS.map((lang) => {
              const checked = generateLanguages.includes(lang.key)
              return (
                <label key={lang.key} className={`lang-picker-row${checked ? ' selected' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggleLang(lang.key)} disabled={busy} />
                  <strong>{lang.label}</strong>
                </label>
              )
            })}
          </div>
          <div className="tracker-script-slot-actions">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || generateLanguages.length === 0} onClick={() => handleGenerate(false)}>
              {generating ? (
                <>
                  <i className="fa-solid fa-spinner fa-spin" /> Generating…
                </>
              ) : 'Generate now'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setPickingLang(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {refThumbFailed && (
        <div className="tracker-script-choose">
          <p className="tracker-hint">Thumbnail generation from the recent 3 failed. Continue without any reference? Nothing has been saved.</p>
          <div className="tracker-script-slot-actions">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => handleGenerate(true)}>
              {generating ? 'Generating…' : 'Yes'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setRefThumbFailed(false)}>
              No
            </button>
          </div>
        </div>
      )}

      {hasMeta && (
        <>
          <div className="locale-tab-row">
            {generated.map((key) => (
              <button
                key={key}
                type="button"
                className={`locale-tab${previewLang === key ? ' active' : ''}`}
                onClick={() => setPreviewLang(key)}
              >
                {languageLabel(key)}
              </button>
            ))}
          </div>
          <div className="tracker-yt-preview">
            <div className={`tracker-yt-preview-thumb${card.type === 'short' ? ' is-portrait' : ''}`}>
              {preview.yt_thumbnail_url ? (
                <img src={preview.yt_thumbnail_url} alt="" />
              ) : (
                <div className="tracker-yt-thumb-empty">No thumbnail</div>
              )}
            </div>
            <div className="tracker-yt-preview-copy">
              {editingMeta ? (
                <div className="tracker-description-edit">
                  <label className="tracker-meta-field">
                    <span>Title</span>
                    <input className="form-control" autoFocus value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} />
                    <small className={titleOver ? 'is-over' : ''}>{titleDraft.length} / {TITLE_MAX}</small>
                  </label>
                  <label className="tracker-meta-field">
                    <span>Description</span>
                    <textarea className="form-control" rows={6} value={descriptionDraft} onChange={(e) => setDescriptionDraft(e.target.value)} />
                    <small className={descriptionOver ? 'is-over' : ''}>{descriptionDraft.length} / {DESCRIPTION_MAX}</small>
                  </label>
                  <label className="tracker-meta-field">
                    <span>Tags</span>
                    <textarea className="form-control" rows={3} value={tagsDraft} onChange={(e) => setTagsDraft(e.target.value)} placeholder="Comma-separated tags" />
                    <small className={tagsOver ? 'is-over' : ''}>{tagsLength} / {TAGS_MAX}</small>
                  </label>
                  <div className="tracker-script-slot-actions">
                    <button type="button" className="btn btn-primary btn-sm" disabled={savingDescription || metaOver} onClick={handleSaveDescription}>
                      {savingDescription ? 'Saving…' : 'Save'}
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" disabled={savingDescription} onClick={() => setEditingMeta(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="tracker-yt-description-row">
                    <h4>{preview.yt_title}</h4>
                    <button type="button" className="tracker-icon-btn" title="Edit title, description, and tags" onClick={startMetaEdit}>
                      <i className="fa-solid fa-pencil" />
                    </button>
                  </div>
                  <p>{preview.yt_description}</p>
                  {preview.yt_tags?.length ? (
                    <small>{preview.yt_tags.map((t) => String(t).replace(/#/g, '')).join(', ')}</small>
                  ) : null}
                </>
              )}
            </div>
          </div>
          <div className="tracker-refine-row">
            <input
              className="form-control"
              placeholder="E.g., Make the title more clickbait"
              value={refinePrompt}
              onChange={(e) => setRefinePrompt(e.target.value)}
            />
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || !refinePrompt.trim()} onClick={handleRefine}>
              {refining ? (
                <>
                  <i className="fa-solid fa-spinner fa-spin" /> Refine
                </>
              ) : 'Refine'}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
