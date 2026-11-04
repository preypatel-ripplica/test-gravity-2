import { useMemo, useState } from 'react'
import { scriptTextValue } from './trackerUtils'

function itemLabel(item) {
  return item.title_hinglish || item.working_title || item.title_en || item.topic_text || 'Untitled'
}

function fuzzyScore(query, text) {
  const q = query.trim().toLowerCase()
  const value = String(text || '').toLowerCase()
  if (!q) return 1
  const at = value.indexOf(q)
  if (at >= 0) return 200 - at
  let qi = 0
  let streak = 0
  for (const ch of value) {
    if (ch === q[qi]) {
      qi += 1
      streak += 1
      if (qi === q.length) return 40 + streak
    }
  }
  return 0
}

function ScriptSwitch({ value, onChange }) {
  return (
    <div className="tracker-script-switch" role="tablist">
      <button type="button" role="tab" aria-selected={value === 'existing'} className={value === 'existing' ? 'is-on' : ''} onClick={() => onChange('existing')}>
        Choose Existing script
      </button>
      <button type="button" role="tab" aria-selected={value === 'custom'} className={value === 'custom' ? 'is-on' : ''} onClick={() => onChange('custom')}>
        Custom script
      </button>
    </div>
  )
}

export default function TrackerScriptSlot({
  card,
  scriptedItems = [],
  titleOptions = [],
  onPick,
  onSaveEdit,
  onSaveManual,
  busy = false,
}) {
  const [mode, setMode] = useState(null)
  const [scriptOpen, setScriptOpen] = useState(true)
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [pickedTitle, setPickedTitle] = useState(null)
  const value = scriptTextValue(card.assets)
  const title = card.title || ''
  const source = card.assets?.script_source === 'manual' ? 'custom' : 'existing'
  const available = useMemo(
    () => scriptedItems.filter((item) => item.id && (item.script || '').trim()),
    [scriptedItems],
  )
  const titles = useMemo(() => {
    const ranked = titleOptions
      .map((row) => ({
        ...row,
        score: Math.max(fuzzyScore(query, row.title), fuzzyScore(query, row.keyword)),
      }))
      .filter((row) => row.score > 0)
    ranked.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
    return ranked
  }, [titleOptions, query])

  function openExisting() {
    setScriptOpen(true)
    setMode('pick')
  }

  function openCustom() {
    setScriptOpen(true)
    setQuery('')
    setPickedTitle(null)
    setDraft('')
    setMode('title')
  }

  function startEdit() {
    setScriptOpen(true)
    setDraft(value)
    setMode('edit')
  }

  function switchTo(next) {
    if (next === 'existing') openExisting()
    else openCustom()
  }

  const switchValue = mode === 'pick'
    ? 'existing'
    : (mode === 'title' || mode === 'write')
      ? 'custom'
      : source

  const header = (
    <div className="tracker-script-slot-head">
      <span className="tracker-kicker">Final script</span>
      <div className="tracker-script-slot-actions">
        {value && mode == null ? (
          <button type="button" className="tracker-icon-btn" title="Edit script" disabled={busy} onClick={startEdit}>
            <i className="fa-solid fa-pencil" />
          </button>
        ) : null}
        <ScriptSwitch value={switchValue} onChange={switchTo} />
        <button
          type="button"
          className="tracker-icon-btn"
          title={scriptOpen ? 'Collapse script' : 'Expand script'}
          onClick={() => setScriptOpen((open) => !open)}
        >
          <i className={`fa-solid ${scriptOpen ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
        </button>
      </div>
    </div>
  )

  if (!scriptOpen) {
    return (
      <div className="tracker-script-slot">
        {header}
      </div>
    )
  }

  if (mode === 'edit') {
    return (
      <div className="tracker-script-slot is-editing">
        {header}
        <textarea
          className="form-control"
          autoFocus
          rows={8}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="tracker-script-slot-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !draft.trim()}
            onClick={() => {
              onSaveEdit(draft)
              setMode(null)
            }}
          >
            Save
          </button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setMode(null)}>
            Cancel
          </button>
        </div>
      </div>
    )
  }

  if (mode === 'title' || mode === 'write') {
    return (
      <div className="tracker-script-slot">
        {header}
        <div className="tracker-script-choose">
          <p className="tracker-hint">Every keyword is listed, including ones that do not have a script yet. This script stays on the card.</p>
          <input
            className="form-control"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles"
          />
          <div className="tracker-script-keyword-list tracker-title-results">
            {titles.length === 0 ? (
              <p className="tracker-hint">No titles match that search.</p>
            ) : titles.map((row) => (
              <button
                key={row.key}
                type="button"
                className={`tracker-script-keyword${pickedTitle?.key === row.key ? ' is-current' : ''}`}
                onClick={() => {
                  setPickedTitle(row)
                  setMode('write')
                }}
              >
                <strong>{row.title}</strong>
                {row.keyword && row.keyword !== row.title ? <small>Keyword · {row.keyword}</small> : <small>Keyword</small>}
              </button>
            ))}
          </div>
          {mode === 'write' && pickedTitle ? (
            <>
              <p className="tracker-hint">Writing for <strong>{pickedTitle.title}</strong></p>
              <textarea
                className="form-control"
                autoFocus
                rows={8}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Paste or write the script"
              />
              <div className="tracker-script-slot-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={busy || !draft.trim()}
                  onClick={() => {
                    onSaveManual({
                      text: draft,
                      title: pickedTitle.title,
                      topicId: pickedTitle.topicId,
                      itemId: pickedTitle.itemId,
                    })
                    setMode(null)
                  }}
                >
                  Save
                </button>
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setMode(value ? null : 'title')}>
                  Cancel
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
    )
  }

  if (mode === 'pick' || !value) {
    return (
      <div className="tracker-script-slot">
        {header}
        <div className="tracker-script-choose">
          <p className="tracker-hint">Use a script that was already written in the content plan.</p>
          {available.length === 0 ? (
            <p className="tracker-hint">No generated {card.type === 'short' ? 'short' : 'long'} scripts yet.</p>
          ) : (
            <div className="tracker-script-keyword-list tracker-title-results">
              {available.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`tracker-script-keyword${item.id === card.content_plan_item_id && source === 'existing' ? ' is-current' : ''}`}
                  disabled={busy}
                  onClick={() => {
                    onPick(item)
                    setMode(null)
                  }}
                >
                  <strong>{itemLabel(item)}</strong>
                  <small>Keyword · {item.topic_text}</small>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="tracker-script-slot">
      {header}
      {title ? <h4 className="tracker-script-title">{title}</h4> : null}
      <pre className="tracker-script-body">{value}</pre>
    </div>
  )
}
