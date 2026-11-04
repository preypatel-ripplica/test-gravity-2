import { useMemo, useState } from 'react'
import { scriptTextValue } from './trackerUtils'

function itemLabel(item) {
  return item.title_hinglish || item.working_title || item.title_en || item.topic_text || 'Untitled'
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
  onPick,
  onSaveEdit,
  onSaveManual,
  busy = false,
}) {
  const [mode, setMode] = useState(null)
  const [scriptOpen, setScriptOpen] = useState(true)
  const [draft, setDraft] = useState('')
  const [titleDraft, setTitleDraft] = useState('')
  const value = scriptTextValue(card.assets)
  const title = card.title || ''
  const source = card.assets?.script_source === 'manual' ? 'custom' : 'existing'
  const available = useMemo(
    () => scriptedItems.filter((item) => item.id && (item.script || '').trim()),
    [scriptedItems],
  )

  function openExisting() {
    setScriptOpen(true)
    setMode('pick')
  }

  function openCustom() {
    const manual = card.assets?.script_source === 'manual'
    setScriptOpen(true)
    setTitleDraft(manual ? title : '')
    setDraft(manual ? value : '')
    setMode('custom')
  }

  function startEdit() {
    setScriptOpen(true)
    setDraft(value)
    if (card.assets?.script_source === 'manual') {
      setTitleDraft(title)
    }
    setMode('edit')
  }

  function switchTo(next) {
    if (next === 'existing') openExisting()
    else openCustom()
  }

  const switchValue = mode === 'pick'
    ? 'existing'
    : mode === 'custom'
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
    const manual = card.assets?.script_source === 'manual'
    const titleId = `tracker-script-title-edit-${card.id}`
    const scriptId = `tracker-script-body-edit-${card.id}`
    return (
      <div className="tracker-script-slot is-editing">
        {header}
        {manual ? (
          <>
            <label className="tracker-kicker" htmlFor={titleId}>Title</label>
            <input
              id={titleId}
              className="form-control"
              autoFocus
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              placeholder="Title"
            />
            <label className="tracker-kicker" htmlFor={scriptId}>Script</label>
          </>
        ) : null}
        <textarea
          id={manual ? scriptId : undefined}
          className="form-control"
          autoFocus={!manual}
          rows={8}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={manual ? 'Paste or write the script' : undefined}
        />
        <div className="tracker-script-slot-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !draft.trim() || (manual && !titleDraft.trim())}
            onClick={() => {
              if (manual) {
                onSaveManual({
                  text: draft,
                  title: titleDraft.trim(),
                  topicId: card.topic_id || null,
                  itemId: card.content_plan_item_id || null,
                })
              } else {
                onSaveEdit(draft)
              }
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

  if (mode === 'custom') {
    const titleId = `tracker-script-title-${card.id}`
    const scriptId = `tracker-script-body-${card.id}`
    return (
      <div className="tracker-script-slot">
        {header}
        <div className="tracker-script-choose">
          <p className="tracker-hint">Type a title and script for this card. This stays on the card.</p>
          <label className="tracker-kicker" htmlFor={titleId}>Title</label>
          <input
            id={titleId}
            className="form-control"
            autoFocus
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            placeholder="Title"
          />
          <label className="tracker-kicker" htmlFor={scriptId}>Script</label>
          <textarea
            id={scriptId}
            className="form-control"
            rows={8}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Paste or write the script"
          />
          <div className="tracker-script-slot-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || !titleDraft.trim() || !draft.trim()}
              onClick={() => {
                onSaveManual({
                  text: draft,
                  title: titleDraft.trim(),
                  topicId: null,
                  itemId: null,
                })
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
