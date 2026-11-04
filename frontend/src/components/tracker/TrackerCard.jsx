import { useEffect, useRef, useState } from 'react'
import api from '../../api'
import TrackerCardHistory from './TrackerCardHistory'
import TrackerDestinations from './TrackerDestinations'
import TrackerNotes from './TrackerNotes'
import TrackerPublishVideo from './TrackerPublishVideo'
import TrackerScriptSlot from './TrackerScriptSlot'
import TrackerStaticGenerate from './TrackerStaticGenerate'
import TrackerYtMetadata from './TrackerYtMetadata'
import {
  cardStatus,
  hasDelayProof,
  isDidNotTrack,
  MARKING_DID_NOT_TRACK,
  MARKING_NONE,
  TYPE_LABELS,
  TYPE_PILL,
  calendarWeekDates,
  isoDate,
  isVideoCard,
  maybeAdvanceStage,
  nextStageId,
  nextStageLabel,
  nextStageSection,
  sectionForStage,
  stageList,
  templateKind,
  templateMessage,
} from './trackerUtils'

function StatusBadge({ card, weekContext }) {
  const status = cardStatus(card, weekContext)
  return <span className={`tracker-pill tracker-pill-status-${status.id}`}>{status.label}</span>
}

function DidNotTrackButton({ card, onChange }) {
  const marked = isDidNotTrack(card.marking)
  return (
    <button
      type="button"
      className={`btn btn-sm ${marked ? 'btn-danger-confirm' : 'btn-secondary'}`}
      onClick={(event) => {
        event.stopPropagation()
        onChange({
          ...card,
          marking: marked ? MARKING_NONE : MARKING_DID_NOT_TRACK,
        })
      }}
    >
      {marked ? 'Clear did not track' : 'Did not track'}
    </button>
  )
}

function PaidAdsSteps({ card, onChange }) {
  const stages = stageList('paid_ads')
  const current = Math.max(0, stages.findIndex((stage) => stage.id === card.stage))
  function toggle(stageId) {
    const idx = stages.findIndex((stage) => stage.id === stageId)
    if (idx < 0) return
    const nextId = current === idx ? stages[Math.max(0, idx - 1)].id : stageId
    onChange({ ...card, started: true, stage: nextId })
  }
  return (
    <div className="tracker-paid-steps" data-tracker-section="paid_ads">
      {stages.filter((stage) => stage.id !== 'planned').map((stage) => {
        const idx = stages.findIndex((row) => row.id === stage.id)
        const done = idx <= current
        return (
          <label key={stage.id} className={`tracker-paid-step${done ? ' is-on' : ''}`}>
            <input type="checkbox" checked={done} onChange={() => toggle(stage.id)} />
            <span>{stage.label}</span>
          </label>
        )
      })}
    </div>
  )
}

const VIDEO_ACCEPT = 'video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm'

function VideoAssetRow({ card, value, onSave, weekContext }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value || '')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)
  const { token, clientId, year, month, week, toast, onWeekUpdate } = weekContext || {}

  async function handleUpload(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !token || !clientId) return
    setUploading(true)
    try {
      const result = await api.uploadWeeklyTrackerFile(
        token,
        { clientId, year, month, week, cardId: card.id, target: 'video_url' },
        file,
      )
      if (onWeekUpdate) onWeekUpdate(result)
      else if (result.file?.url) onSave(result.file.url)
      toast('Video uploaded', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setUploading(false)
    }
  }

  if (uploading) {
    return (
      <div className="tracker-asset-row is-video is-uploading" data-tracker-section="video">
        <span className="tracker-kicker">Video for the doctor</span>
        <em><i className="fa-solid fa-spinner fa-spin" /> Uploading…</em>
      </div>
    )
  }

  if (editing) {
    return (
      <div className="tracker-asset-row is-editing" data-tracker-section="video">
        <span className="tracker-kicker">Video for the doctor</span>
        <input className="form-control" autoFocus value={draft} placeholder="Paste Drive URL" onChange={(e) => setDraft(e.target.value)} />
        <button type="button" className="btn btn-primary btn-sm" onClick={() => { onSave(draft.trim()); setEditing(false) }}>Save</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setDraft(value || ''); setEditing(false) }}>Cancel</button>
      </div>
    )
  }

  return (
    <div className="tracker-asset-row is-video" data-tracker-section="video">
      <span className="tracker-kicker">Video for the doctor</span>
      <em>{value || 'Not added yet — paste a link or upload'}</em>
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setDraft(value || ''); setEditing(true) }}>
        Paste link
      </button>
      <button type="button" className="btn btn-primary btn-sm" onClick={() => fileRef.current?.click()}>
        Upload from computer
      </button>
      <input ref={fileRef} type="file" accept={VIDEO_ACCEPT} hidden onChange={handleUpload} />
    </div>
  )
}

function Timeline({ card, onSelectStage }) {
  const stages = stageList(card.type)
  const current = Math.max(0, stages.findIndex((s) => s.id === card.stage))
  const progress = stages.length <= 1 ? 1 : current / (stages.length - 1)
  return (
    <div className="tracker-timeline" style={{ '--tracker-steps': String(stages.length) }}>
      <div className="tracker-timeline-track">
        <div className="tracker-timeline-fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <div className="tracker-timeline-steps">
        {stages.map((stage, index) => (
          <button
            type="button"
            key={stage.id}
            className={`tracker-timeline-step${index <= current ? ' is-done' : ''}${index === current ? ' is-current' : ''}`}
            onClick={() => onSelectStage?.(stage.id)}
          >
            <span className="tracker-timeline-dot" />
            <small>{stage.label}</small>
          </button>
        ))}
      </div>
    </div>
  )
}

function stopToggle(event) {
  event.stopPropagation()
}

function DelayProofNote({ card }) {
  if (!hasDelayProof(card)) return null
  const proofs = card.delay_proofs || []
  return (
    <div className="delay-proof-note">
      <strong>Delay reason</strong>
      <p>{card.delay_reason}</p>
      <ul>
        {proofs.map((file) => (
          <li key={file.id || file.url}>
            <a href={file.url} target="_blank" rel="noreferrer">
              {file.name || 'Proof'}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function VideoEditFields({ card, weekContext, onChange, lockEditor = false }) {
  if (!isVideoCard(card.type)) return null
  const editors = weekContext?.editors || []
  const dates = weekContext?.weekDates || calendarWeekDates()
  const editorName = editors.find((row) => row.id === card.editor_id)?.name || card.editor_id || 'Unassigned'
  return (
    <div className="tracker-edit-fields" onClick={stopToggle}>
      {lockEditor ? (
        <div className="tracker-assign-field">
          <span className="tracker-kicker">Editor</span>
          <div className="tracker-assign-strip">
            <span className="tracker-assign-cell is-on">{editorName}</span>
          </div>
        </div>
      ) : (
        <div className="tracker-assign-field">
          <span className="tracker-kicker">Editor</span>
          <div className="tracker-assign-strip" role="listbox" aria-label="Editor">
            <button
              type="button"
              role="option"
              aria-selected={!card.editor_id}
              className={`tracker-assign-cell${!card.editor_id ? ' is-on' : ''}`}
              onClick={() => onChange({ ...card, editor_id: '', editor_overridden: true })}
            >
              Unassigned
            </button>
            {editors.map((editor) => (
              <button
                type="button"
                role="option"
                key={editor.id}
                aria-selected={card.editor_id === editor.id}
                className={`tracker-assign-cell${card.editor_id === editor.id ? ' is-on' : ''}`}
                onClick={() => onChange({ ...card, editor_id: editor.id, editor_overridden: true })}
              >
                {editor.name}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="tracker-assign-field">
        <span className="tracker-kicker">Edit date</span>
        <div className="tracker-day-strip" role="listbox" aria-label="Edit date">
          {dates.map((day) => {
            const value = isoDate(day)
            const on = card.planned_edit_date === value
            return (
              <button
                type="button"
                role="option"
                key={value}
                aria-selected={on}
                className={`tracker-day-cell${on ? ' is-on' : ''}`}
                onClick={() => onChange({ ...card, planned_edit_date: on ? '' : value })}
              >
                <small>{day.toLocaleDateString('en-GB', { weekday: 'short' })}</small>
                <strong>{day.getDate()}</strong>
              </button>
            )
          })}
        </div>
      </div>
      {card.edit_hours ? <em className="tracker-edit-hours">{card.edit_hours}h</em> : null}
    </div>
  )
}

function TemplateMessageButton({ card, clientName, toast }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const message = templateKind(card) ? templateMessage(card, clientName) : ''

  useEffect(() => {
    if (!open) return undefined
    function onPointerDown(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!message) return null

  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(message)
      toast?.('Message copied', 'success')
    } catch {
      toast?.('Could not copy the message', 'error')
    }
  }

  return (
    <div className="tracker-template" ref={wrapRef}>
      <button
        type="button"
        className={`btn btn-secondary${open ? ' is-on' : ''}`}
        onClick={() => setOpen((value) => !value)}
      >
        Template message
      </button>
      {open ? (
        <div className="tracker-template-card" role="dialog" aria-label="Template message">
          <div className="tracker-template-head">
            <strong>Template message</strong>
            <button type="button" className="btn btn-primary btn-sm" onClick={copyMessage}>
              Copy
            </button>
          </div>
          <pre>{message}</pre>
        </div>
      ) : null}
    </div>
  )
}

function DeleteCardButton({ onDelete }) {
  if (!onDelete) return null
  return (
    <button
      type="button"
      className="tracker-icon-btn is-danger"
      data-tip="Remove"
      onClick={(event) => {
        event.stopPropagation()
        onDelete()
      }}
    >
      <i className="fa-solid fa-xmark" />
    </button>
  )
}

export default function TrackerCard({
  card,
  languages,
  weekContext,
  scriptedItems = [],
  titleOptions = [],
  scriptBusy = false,
  onPickScript,
  onSaveScriptText,
  onSaveManualScript,
  onChange,
  onDelete,
  variant = 'full',
}) {
  const editorView = variant === 'editor'
  const nextLabel = nextStageLabel(card)
  const nextSection = nextStageSection(card)
  const cardRef = useRef(null)

  function saveAsset(key, url) {
    const assets = { ...(card.assets || {}), [key]: url }
    onChange(maybeAdvanceStage({ ...card, assets }))
  }

  function scrollToSection(sectionId) {
    if (!sectionId || !cardRef.current) return
    const el = cardRef.current.querySelector(`[data-tracker-section="${sectionId}"]`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.remove('tracker-section-flash')
    void el.offsetWidth
    el.classList.add('tracker-section-flash')
    window.setTimeout(() => el.classList.remove('tracker-section-flash'), 1300)
  }

  const status = cardStatus(card, weekContext)
  const stateClass = ` is-status-${status.id}`

  function toggleCollapsed() {
    onChange({ ...card, collapsed: !card.collapsed })
  }

  function handleTitleToggle(event) {
    if (event.target.closest('.tracker-title-input, .btn, .tracker-icon-btn, .tracker-head-actions')) return
    toggleCollapsed()
  }

  function handleTitleKeyDown(event) {
    if (event.key !== 'Enter' && event.key !== ' ') return
    if (event.target.closest('input, textarea, .btn, .tracker-icon-btn, .tracker-head-actions')) return
    event.preventDefault()
    toggleCollapsed()
  }

  if (card.collapsed) {
    return (
      <div className={`tracker-type-card is-collapsed${stateClass}`}>
        <div
          className="tracker-collapsed-main"
          role="button"
          tabIndex={0}
          aria-expanded="false"
          onClick={toggleCollapsed}
          onKeyDown={handleTitleKeyDown}
        >
          <span className={`tracker-pill ${TYPE_PILL[card.type]}`}>{TYPE_LABELS[card.type]}</span>
          <strong className="tracker-collapsed-title">{card.title || 'Untitled'}</strong>
          <StatusBadge card={card} weekContext={weekContext} />
          {hasDelayProof(card) ? <span className="tracker-pill tracker-pill-delay">Delay noted</span> : null}
          <span className="tracker-icon-btn" data-tip="Expand" aria-hidden="true">
            <i className="fa-solid fa-chevron-down" />
          </span>
        </div>
        <div className="tracker-head-actions" onClick={stopToggle}>
          <DidNotTrackButton card={card} onChange={onChange} />
          <DeleteCardButton onDelete={onDelete} />
        </div>
      </div>
    )
  }

  return (
    <article ref={cardRef} className={`tracker-expanded-card${stateClass}`}>
      <header
        className="tracker-expanded-head"
        onClick={handleTitleToggle}
        onKeyDown={handleTitleKeyDown}
      >
        <span className={`tracker-pill ${TYPE_PILL[card.type]}`}>{TYPE_LABELS[card.type]}</span>
        <StatusBadge card={card} weekContext={weekContext} />
        <input
          className="tracker-title-input"
          value={card.title || ''}
          placeholder="What's this one about?"
          onClick={stopToggle}
          onChange={(e) => onChange({ ...card, title: e.target.value })}
        />
        <div className="tracker-head-actions" onClick={stopToggle}>
          <button type="button" className="tracker-icon-btn" data-tip="Collapse" onClick={toggleCollapsed}>
            <i className="fa-solid fa-chevron-up" />
          </button>
          {editorView ? null : (
            <>
              <DidNotTrackButton card={card} onChange={onChange} />
              <DeleteCardButton onDelete={onDelete} />
            </>
          )}
        </div>
      </header>

      {editorView ? null : <DelayProofNote card={card} />}

      <div className="tracker-stage-block">
        <VideoEditFields
          card={card}
          weekContext={weekContext}
          onChange={onChange}
          lockEditor={editorView}
        />
        {editorView ? null : (
          <>
            <Timeline
              card={card}
              onSelectStage={(stageId) => {
                onChange({ ...card, started: true, stage: stageId })
                scrollToSection(sectionForStage({ ...card, stage: stageId }, stageId))
              }}
            />
            <div className="tracker-next-row">
              <div>
                <strong>Next: {nextLabel || 'Done'}</strong>
                <p className="tracker-hint">Current stage: {card.stage.replace(/_/g, ' ')}</p>
              </div>
              <div className="tracker-next-actions">
                <TemplateMessageButton card={card} clientName={weekContext?.clientName} toast={weekContext?.toast} />
                {nextLabel && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      const nextId = nextStageId(card)
                      if (nextId) onChange({ ...card, started: true, stage: nextId })
                      scrollToSection(nextSection)
                    }}
                  >
                    {nextLabel} →
                  </button>
                )}
              </div>
            </div>
          </>
        )}
        {isVideoCard(card.type) && (
          <div className="tracker-asset-list">
            {editorView ? null : (
              <>
                <div data-tracker-section="script">
                  <TrackerScriptSlot
                    card={card}
                    scriptedItems={scriptedItems}
                    titleOptions={titleOptions}
                    busy={scriptBusy}
                    onPick={onPickScript}
                    onSaveEdit={onSaveScriptText}
                    onSaveManual={onSaveManualScript}
                  />
                </div>
                <div data-tracker-section="yt_metadata">
                  <TrackerYtMetadata card={card} weekContext={weekContext} onChange={onChange} />
                </div>
              </>
            )}
            <VideoAssetRow
              card={card}
              value={card.assets?.video_url}
              onSave={(url) => saveAsset('video_url', url)}
              weekContext={weekContext}
            />
            {editorView ? null : (
              <div data-tracker-section="publish">
                <TrackerPublishVideo card={card} weekContext={weekContext} onChange={onChange} />
              </div>
            )}
          </div>
        )}
      </div>

      {editorView || card.type !== 'static_post' ? null : (
        <div data-tracker-section="generate">
          <TrackerStaticGenerate card={card} weekContext={weekContext} onChange={onChange} />
        </div>
      )}

      {editorView || card.type !== 'paid_ads' ? null : (
        <PaidAdsSteps card={card} onChange={onChange} />
      )}

      {(isVideoCard(card.type) || card.type === 'paid_ads') && (
        <TrackerNotes
          title="Feedback"
          hint={card.type === 'paid_ads'
            ? 'Notes from the ads review, spend check, or client call.'
            : 'Type 2:30 the broll is wrong and the timecode is picked up automatically.'}
          section="feedback"
          card={card}
          languages={languages}
          weekContext={weekContext}
          onWeekUpdate={weekContext.onWeekUpdate}
        />
      )}
      {isVideoCard(card.type) ? (
        <div data-tracker-section="editor">
          <TrackerNotes
            title="Editor notes"
            hint="Simple back-and-forth between internal and the editor for this video."
            section="editor"
            card={card}
            languages={languages}
            weekContext={weekContext}
            onWeekUpdate={weekContext.onWeekUpdate}
          />
        </div>
      ) : null}
      {editorView ? null : (
        <div data-tracker-section="doctor">
          <TrackerNotes
            title="From the doctor"
            hint="Photos or files the doctor gave us for this one."
            section="doctor"
            card={card}
            languages={languages}
            weekContext={weekContext}
            onWeekUpdate={weekContext.onWeekUpdate}
            showDoctorFiles
          />
        </div>
      )}

      {editorView || card.type === 'paid_ads' ? null : (
        <div data-tracker-section="destinations">
          <TrackerDestinations
            card={card}
            languages={languages}
            onChange={(next) => onChange(maybeAdvanceStage(next))}
          />
        </div>
      )}

      {editorView ? null : <TrackerCardHistory card={card} />}
    </article>
  )
}
