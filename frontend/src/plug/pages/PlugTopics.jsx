import { useEffect, useState } from 'react'
import { useUI } from '../../context/UIContext'
import plugApi from '../api'
import { usePlugAuth } from '../AuthContext'
import PlugPageHeader from '../components/PlugPageHeader'

const LANGUAGE_OPTIONS = [
  { value: 'english', label: 'English' },
  { value: 'hinglish', label: 'Hinglish' },
  { value: 'hindi', label: 'Hindi' },
]

export default function PlugTopics() {
  const { token, creator, refresh } = usePlugAuth()
  const { toast, prompt } = useUI()

  const [language, setLanguage] = useState(creator?.language || 'english')
  const [run, setRun] = useState(null)
  const [searching, setSearching] = useState(false)
  const [redoId, setRedoId] = useState(null)
  const [copiedId, setCopiedId] = useState(null)
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    if (creator?.language) setLanguage(creator.language)
  }, [creator?.language])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        await refresh()
        const data = await plugApi.listTopics(token)
        if (!cancelled && data.run) {
          setRun(data.run)
          if (data.run.language) setLanguage(data.run.language)
        }
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  function profileGap() {
    const missing = []
    if (!creator?.niche?.trim()) missing.push('niche')
    if (!creator?.niche_details?.trim()) missing.push('details about niche')
    if (!missing.length) return ''
    if (missing.length === 1) return `Add ${missing[0]} in Profile before searching.`
    return 'Add niche and details about niche in Profile before searching.'
  }

  async function runSearch(extraPrompt = '') {
    if (profileGap()) return
    setSearching(true)
    try {
      const data = await plugApi.searchTopics(token, {
        language: (language || 'english').trim() || 'english',
        prompt: extraPrompt,
      })
      setRun(data)
      setOpenId(data.topics?.[0]?.id || null)
      toast('Four topics ready', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSearching(false)
    }
  }

  async function handleRedoSearch() {
    const extra = await prompt({
      title: 'Redo search with a prompt',
      placeholder: 'e.g. more beginner-friendly, skip money talk, lean into stories…',
      defaultValue: run?.prompt || '',
    })
    if (extra == null) return
    await runSearch(extra.trim())
  }

  async function handleRedoScript(topic) {
    const extra = await prompt({
      title: `Redo script: ${topic.title}`,
      placeholder: 'e.g. stronger hook, shorter CTA, funnier, more Hindi…',
    })
    if (!extra?.trim()) return
    setRedoId(topic.id)
    try {
      const data = await plugApi.redoScript(token, {
        topicId: topic.id,
        prompt: extra.trim(),
        language: (language || run?.language || 'english').trim(),
      })
      setRun(data.run)
      toast('Script updated', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setRedoId(null)
    }
  }

  async function copyScript(topic) {
    try {
      await navigator.clipboard.writeText(topic.script || '')
      setCopiedId(topic.id)
      setTimeout(() => setCopiedId(null), 1600)
    } catch {
      toast('Could not copy', 'error')
    }
  }

  async function handleRate(topic, next) {
    const rating = topic.rating === next ? null : next
    setRun((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        topics: (prev.topics || []).map((item) =>
          item.id === topic.id ? { ...item, rating } : item,
        ),
      }
    })
    try {
      const data = await plugApi.rateScript(token, { topicId: topic.id, rating })
      if (data.run) setRun(data.run)
    } catch (err) {
      toast(err.message, 'error')
      try {
        const data = await plugApi.listTopics(token)
        if (data.run) setRun(data.run)
      } catch {
        /* keep optimistic value */
      }
    }
  }

  const topics = run?.topics || []
  const profileGapMessage = profileGap()

  return (
    <div className="plug-page animate-fade-in">
      <PlugPageHeader
        kicker="Ideas"
        title="Topics"
        subtitle="Search for 4 ideas scored out of 100, each with a 45s-1 min spoken script."
      />

      <div className="card plug-section plug-panel plug-topics-toolbar">
        <div className="plug-toolbar-row">
          <div className="input-group plug-language-field">
            <label htmlFor="plug-language">Language</label>
            <div className="plug-language-controls">
              <input
                id="plug-language"
                type="text"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="english"
              />
              <div className="plug-lang-chips">
                {LANGUAGE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`plug-lang-chip ${language === opt.value ? 'active' : ''}`}
                    onClick={() => setLanguage(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="plug-toolbar-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => runSearch('')}
              disabled={searching}
            >
              {searching ? 'Searching…' : 'Search'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleRedoSearch}
              disabled={searching}
            >
              Redo with prompt
            </button>
          </div>
        </div>
        <p className="text-muted plug-hint">Spoken language as a string. Common values: english, hinglish, hindi.</p>
        {profileGapMessage ? <p className="plug-warn">{profileGapMessage}</p> : null}
      </div>

      {topics.length === 0 && !searching && (
        <div className="connect-prompt-container card plug-panel">
          <div className="prompt-illustration">
            <i className="fa-solid fa-lightbulb illustration-icon" />
          </div>
          <h2>No topics yet</h2>
          <p>Search uses your niche, niche details, and example topics. Scripts follow your example scripts if you added them.</p>
        </div>
      )}

      {searching && (
        <p className="text-muted plug-searching">Looking up what is currently interesting in your niche…</p>
      )}

      <div className="plug-topic-list">
        {topics.map((topic, index) => {
          const open = openId === topic.id
          const rank = String(index + 1).padStart(2, '0')
          return (
            <article key={topic.id} className={`card plug-topic-card ${open ? 'is-open' : ''}`}>
              <button
                type="button"
                className="plug-topic-summary"
                onClick={() => setOpenId(open ? null : topic.id)}
              >
                <span className="plug-topic-num">{rank}</span>
                <div className="plug-score" aria-label={`Score ${topic.score} out of 100`}>
                  <strong>{topic.score}</strong>
                  <span>/100</span>
                </div>
                <div className="plug-topic-copy">
                  <h3>{topic.title}</h3>
                  {topic.angle ? <p className="text-muted">{topic.angle}</p> : null}
                </div>
                <i className={`fa-solid fa-chevron-${open ? 'up' : 'down'}`} />
              </button>
              {open && (
                <div className="plug-topic-body">
                  <div className="plug-script-meta">
                    {topic.hook_used ? <span>Hook: {topic.hook_used}</span> : null}
                    {topic.cta_line ? <span>CTA: {topic.cta_line}</span> : null}
                  </div>
                  <pre className="plug-script">{topic.script}</pre>
                  <div className="plug-topic-actions">
                    <div className="plug-vote">
                      <button
                        type="button"
                        className={`plug-vote-btn ${topic.rating === 'like' ? 'is-like' : ''}`}
                        aria-label="Like script"
                        aria-pressed={topic.rating === 'like'}
                        disabled={Boolean(redoId)}
                        onClick={() => handleRate(topic, 'like')}
                      >
                        <i className="fa-solid fa-thumbs-up" />
                      </button>
                      <button
                        type="button"
                        className={`plug-vote-btn ${topic.rating === 'dislike' ? 'is-dislike' : ''}`}
                        aria-label="Dislike script"
                        aria-pressed={topic.rating === 'dislike'}
                        disabled={Boolean(redoId)}
                        onClick={() => handleRate(topic, 'dislike')}
                      >
                        <i className="fa-solid fa-thumbs-down" />
                      </button>
                    </div>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => copyScript(topic)}>
                      {copiedId === topic.id ? 'Copied' : 'Copy script'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleRedoScript(topic)}
                      disabled={redoId === topic.id || searching}
                    >
                      {redoId === topic.id ? 'Rewriting…' : 'Redo script with prompt'}
                    </button>
                  </div>
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}
