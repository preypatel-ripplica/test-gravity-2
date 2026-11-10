import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import { TYPE_LABELS, TYPE_PILL } from '../components/tracker/trackerUtils'

const ALL_TAB = 'all'
const UNASSIGNED = 'unassigned'
const DRAG_THRESHOLD = 8
const DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const DEFAULT_WEEKDAYS = [0, 1, 2, 3, 4, 5]
const FALLBACK_WEEKS = [
  { offset: 0, label: 'This week', range_label: '' },
  { offset: 1, label: 'Next week', range_label: '' },
]

function typeLabel(type) {
  return TYPE_LABELS[type] || type
}

function typeShort(type) {
  if (type === 'long_video') return 'long'
  if (type === 'short') return 'short'
  return String(type || 'video').replace(/_/g, ' ')
}

function videoTaskLabel(item) {
  const week = Number(item?.week) || 0
  const task = week ? `week${week} ${typeShort(item?.type)}` : typeShort(item?.type)
  const title = String(item?.title || '').trim() || 'Untitled'
  return `${task} : ${title}`
}

function hoursLabel(value) {
  const hours = Number(value) || 0
  const text = Number.isInteger(hours) ? String(hours) : hours.toFixed(1)
  return `${text}h`
}

function cardKey(item) {
  return `${item.client_id}:${item.year}:${item.month}:${item.week}:${item.card_id}`
}

function sameCard(left, right) {
  return cardKey(left) === cardKey(right)
}

function dropIdFromPoint(x, y) {
  const el = document.elementFromPoint(x, y)
  return el?.closest('[data-drop-id]')?.getAttribute('data-drop-id') || null
}

function dateFromDropId(dropId) {
  if (!dropId || dropId === UNASSIGNED) return ''
  return dropId
}

function weekDateSet(days) {
  return new Set((days || []).map((day) => day.date))
}

function dateOnBoard(item, weekDates) {
  const day = item.planned_edit_date || ''
  return weekDates.has(day) ? day : ''
}

function annotateItems(items, days, editors) {
  const weekDates = weekDateSet(days)
  const totals = {}
  for (const item of items) {
    const day = dateOnBoard(item, weekDates)
    const editorId = item.editor_id || ''
    if (!editorId || !day) continue
    totals[editorId] = totals[editorId] || {}
    totals[editorId][day] = (totals[editorId][day] || 0) + (Number(item.edit_hours) || 0)
  }
  const editorCap = Object.fromEntries((editors || []).map((editor) => [editor.id, Number(editor.max_hours_per_day) || 0]))
  return items.map((item) => {
    const day = dateOnBoard(item, weekDates)
    const cap = editorCap[item.editor_id] || 0
    let spill = false
    let reason = ''
    if (!day) {
      spill = true
      reason = 'unassigned'
    } else if (cap && (totals[item.editor_id]?.[day] || 0) > cap + 1e-9) {
      spill = true
      reason = 'editor spill'
    }
    return { ...item, spill, spill_reason: reason }
  })
}

export default function EditTracker() {
  const { token, user } = useAuth()
  const { toast, confirm } = useUI()
  const navigate = useNavigate()
  const isEditorUser = user?.type === 'editor'
  const scopedEditorId = user?.editor_id || ''
  const [weekOffset, setWeekOffset] = useState(0)
  const [workingWeekdays, setWorkingWeekdays] = useState(DEFAULT_WEEKDAYS)
  const [board, setBoard] = useState(null)
  const [tab, setTab] = useState(isEditorUser && scopedEditorId ? scopedEditorId : ALL_TAB)
  const [viewMode, setViewMode] = useState('board') // board | micro
  const compact = viewMode === 'micro'
  const [loading, setLoading] = useState(true)
  const [assigning, setAssigning] = useState(false)
  const [dropTarget, setDropTarget] = useState(null)
  const [dragKey, setDragKey] = useState(null)
  const ghostRef = useRef(null)
  const ghostOffsetRef = useRef({ x: 0, y: 0 })
  const seededDays = useRef(false)
  const canAssign = !isEditorUser && board?.can_assign !== false
  const canManageSettings = !isEditorUser && board?.can_manage_settings !== false
  const canDrag = !isEditorUser

  function showGhost(item, { rect, clientX, clientY }) {
    const node = ghostRef.current
    if (!node) return
    ghostOffsetRef.current = { x: clientX - rect.left, y: clientY - rect.top }
    node.replaceChildren()
    const name = document.createElement('strong')
    name.textContent = item.client_name || ''
    const title = document.createElement('p')
    title.textContent = videoTaskLabel(item)
    node.append(name, title)
    node.style.width = `${rect.width}px`
    node.style.display = 'block'
    moveGhost(clientX, clientY)
  }

  function moveGhost(clientX, clientY) {
    const node = ghostRef.current
    if (!node || node.style.display === 'none') return
    const offset = ghostOffsetRef.current
    node.style.transform = `translate(${clientX - offset.x}px, ${clientY - offset.y}px)`
  }

  function hideGhost() {
    const node = ghostRef.current
    if (!node) return
    node.style.display = 'none'
    node.style.transform = 'translate(-9999px, -9999px)'
  }

  const applyBoard = useCallback((data) => {
    setBoard(data)
    if (!seededDays.current && Array.isArray(data?.working_weekdays) && data.working_weekdays.length) {
      seededDays.current = true
      setWorkingWeekdays(data.working_weekdays)
    }
  }, [])

  const loadBoard = useCallback(async ({ quiet } = {}) => {
    if (!token) return
    if (!quiet) {
      setLoading(true)
      setBoard((prev) => (prev?.week_offset === weekOffset ? prev : null))
    }
    try {
      const data = await api.getEditTrackerBoard(token, { week_offset: weekOffset })
      applyBoard(data)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [token, weekOffset, applyBoard, toast])

  useEffect(() => {
    loadBoard()
  }, [loadBoard])

  const items = board?.items || []
  const days = useMemo(() => {
    const wanted = new Set(workingWeekdays)
    return (board?.days || []).map((day, index) => ({
      ...day,
      weekday_index: Number.isInteger(day.weekday_index) ? day.weekday_index : index,
      working: wanted.has(Number.isInteger(day.weekday_index) ? day.weekday_index : index),
    }))
  }, [board, workingWeekdays])
  const weekDates = useMemo(() => weekDateSet(days), [days])
  const editors = board?.editors || []
  const editorTabs = board?.editors_in_use || []
  const weekOptions = board?.weeks?.length ? board.weeks : FALLBACK_WEEKS
  const thisWeek = weekOffset === 0

  const visibleItems = useMemo(() => {
    if (tab === ALL_TAB) return items
    return items.filter((item) => item.editor_id === tab)
  }, [items, tab])

  const dayCapacity = useMemo(() => {
    const roster = editorTabs.length ? editorTabs : editors
    if (tab !== ALL_TAB) {
      const editor = roster.find((row) => row.id === tab) || editors.find((row) => row.id === tab)
      return Number(editor?.max_hours_per_day) || 0
    }
    return roster.reduce((sum, editor) => sum + (Number(editor.max_hours_per_day) || 0), 0)
  }, [tab, editorTabs, editors])

  const unassignedItems = visibleItems.filter((item) => !dateOnBoard(item, weekDates))
  const dayOverflow = useMemo(() => {
    const flags = {}
    for (const day of days) {
      const dayItems = visibleItems.filter((item) => dateOnBoard(item, weekDates) === day.date)
      flags[day.date] = dayItems.some((item) => item.spill && item.spill_reason === 'editor spill')
    }
    return flags
  }, [days, visibleItems, weekDates])

  useEffect(() => {
    if (isEditorUser && scopedEditorId) {
      setTab(scopedEditorId)
      return
    }
    if (tab === ALL_TAB) return
    if (!editorTabs.some((editor) => editor.id === tab)) setTab(ALL_TAB)
  }, [tab, editorTabs, isEditorUser, scopedEditorId])

  const applyItemPatch = useCallback((item, patch) => {
    setBoard((prev) => {
      if (!prev) return prev
      const nextItems = prev.items.map((row) => (sameCard(row, item) ? { ...row, ...patch } : row))
      return {
        ...prev,
        items: annotateItems(nextItems, prev.days, prev.editors),
      }
    })
  }, [])

  async function persistPatch(item, patch, previous) {
    if (!token) return
    const fields = {}
    if ('editor_id' in patch) fields.editor_id = patch.editor_id
    if ('planned_edit_date' in patch) fields.planned_edit_date = patch.planned_edit_date
    if (!Object.keys(fields).length) return
    try {
      await api.patchEditTrackerCard(token, {
        client_id: item.client_id,
        year: item.year,
        month: item.month,
        week: item.week,
        card_id: item.card_id,
        ...fields,
      })
    } catch (err) {
      if (previous) applyItemPatch(item, previous)
      toast(err.message, 'error')
    }
  }

  function patchCard(item, patch) {
    const previous = {}
    for (const key of Object.keys(patch)) previous[key] = item[key]
    applyItemPatch(item, patch)
    persistPatch(item, patch, previous)
  }

  function moveCard(item, dropId) {
    const nextDate = dateFromDropId(dropId)
    if ((item.planned_edit_date || '') === nextDate) return
    patchCard(item, { planned_edit_date: nextDate })
  }

  function toggleWeekday(index) {
    setWorkingWeekdays((current) => {
      if (current.includes(index)) return current.filter((day) => day !== index)
      return [...current, index].sort((left, right) => left - right)
    })
  }

  async function handleAssign() {
    if (!token) return
    if (!workingWeekdays.length) {
      toast('Select at least one working day', 'error')
      return
    }
    const ok = await confirm({
      title: thisWeek ? 'Reassign this week?' : 'Reassign next week?',
      message: thisWeek
        ? 'This will replace this week’s current placements. Late work and this week’s videos will be redistributed across the selected days.'
        : 'This will replace next week’s current placements. Only next week’s videos will be distributed. Late work stays on this week.',
      isDanger: true,
    })
    if (!ok) return
    setAssigning(true)
    try {
      const data = await api.assignEditTracker(token, {
        week_offset: weekOffset,
        working_weekdays: workingWeekdays,
      })
      applyBoard(data)
      toast(thisWeek ? 'Work assigned for this week' : 'Work assigned for next week', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setAssigning(false)
    }
  }

  function handleDragStart(item, payload) {
    if (!canDrag) return
    setDragKey(cardKey(item))
    showGhost(item, payload)
  }

  function handleDragHover(dropId, point) {
    if (point) moveGhost(point.x, point.y)
    setDropTarget((current) => (current === dropId ? current : dropId))
  }

  function handleDragEnd(item, dropId) {
    hideGhost()
    setDragKey(null)
    setDropTarget(null)
    if (item && dropId != null) moveCard(item, dropId)
  }

  return (
    <div className={`edit-tracker-page${dragKey ? ' is-dragging-board' : ''}`}>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs items={[{ label: 'Edit tracker' }]} />
          <h1>Edit tracker</h1>
          <p>
            {isEditorUser
              ? 'Your assigned long / short videos for this week and late carry-over.'
              : thisWeek
                ? 'Distribute late work and this week’s long / short videos across editors and days.'
                : 'Plan next week’s long / short videos. Late work stays on this week.'}
          </p>
        </div>
        <div className="edit-tracker-header-actions">
          {canManageSettings ? (
            <Link to="/edit-tracker/settings" className="edit-tracker-settings-btn" title="Client settings">
              <i className="fa-solid fa-gear" />
              <span>Client settings</span>
            </Link>
          ) : null}
          <div className="edit-tracker-week-switch" role="tablist" aria-label="Week">
            {weekOptions.map((week) => (
              <button
                key={week.offset}
                type="button"
                role="tab"
                aria-selected={weekOffset === week.offset}
                className={`edit-tracker-week-btn${weekOffset === week.offset ? ' is-on' : ''}`}
                onClick={() => setWeekOffset(week.offset)}
              >
                <strong>{week.label}</strong>
                {week.range_label ? <span>{week.range_label}</span> : null}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="edit-tracker-toolbar">
        {!isEditorUser ? (
          <div className="edit-tracker-days">
            <span>Working days</span>
            <div className="edit-day-picks" role="group" aria-label="Working days">
              {DAY_LETTERS.map((letter, index) => {
                const on = workingWeekdays.includes(index)
                return (
                  <button
                    key={`${letter}-${index}`}
                    type="button"
                    className={`edit-day-pick${on ? ' is-on' : ''}`}
                    aria-pressed={on}
                    aria-label={DAY_NAMES[index]}
                    onClick={() => toggleWeekday(index)}
                  >
                    {letter}
                  </button>
                )
              })}
            </div>
          </div>
        ) : <div />}
        <div className="edit-tracker-toolbar-actions">
          <div className="edit-view-toggle" role="tablist" aria-label="Card view">
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'board'}
              className={viewMode === 'board' ? 'is-on' : ''}
              onClick={() => setViewMode('board')}
            >
              Board
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'micro'}
              className={viewMode === 'micro' ? 'is-on' : ''}
              onClick={() => setViewMode('micro')}
            >
              Micro
            </button>
          </div>
          {canAssign ? (
            <button type="button" className="btn btn-primary" onClick={handleAssign} disabled={assigning}>
              Assign
            </button>
          ) : null}
        </div>
      </div>

      {!isEditorUser ? (
        <div className="edit-tracker-tabs" role="tablist" aria-label="Editors">
          <button
            type="button"
            role="tab"
            aria-selected={tab === ALL_TAB}
            className={`edit-tracker-tab is-all${tab === ALL_TAB ? ' is-on' : ''}`}
            onClick={() => setTab(ALL_TAB)}
          >
            All
          </button>
          {editorTabs.map((editor) => (
            <button
              key={editor.id}
              type="button"
              role="tab"
              aria-selected={tab === editor.id}
              className={`edit-tracker-tab is-${editorTone(editor.id)}${tab === editor.id ? ' is-on' : ''}`}
              onClick={() => setTab(editor.id)}
            >
              {editor.name}
              {editor.max_hours_per_day ? <em>{editor.max_hours_per_day}h / day</em> : null}
            </button>
          ))}
        </div>
      ) : null}

      {loading && !board ? (
        <p className="text-muted">Loading edit board…</p>
      ) : (
        <>
          <div className="edit-tracker-week">
            {days.map((day) => {
              const dayItems = visibleItems.filter((item) => dateOnBoard(item, weekDates) === day.date)
              const hours = dayItems.reduce((sum, item) => sum + (Number(item.edit_hours) || 0), 0)
              const overflow = dayOverflow[day.date]
              return (
                <section
                  key={day.date}
                  data-drop-id={day.date}
                  className={`edit-tracker-day${overflow ? ' is-spill' : ''}${day.working ? '' : ' is-off'}${dropTarget === day.date ? ' is-drop' : ''}`}
                >
                  <header>
                    <div>
                      <strong>{day.weekday}</strong>
                      <span>{day.label}</span>
                    </div>
                    <em title={dayCapacity ? `${hours} of ${dayCapacity} hours` : hoursLabel(hours)}>
                      {dayCapacity ? `${hoursLabel(hours)} / ${hoursLabel(dayCapacity)}` : hoursLabel(hours)}
                    </em>
                    {overflow ? <small>Over capacity</small> : null}
                  </header>
                  <CardsLane
                    items={dayItems}
                    editors={editors}
                    days={days}
                    compact={compact}
                    groupByEditor={tab === ALL_TAB}
                    dragKey={dragKey}
                    emptyHint={dropTarget === day.date ? 'Drop to assign' : 'No videos'}
                    lockEditor={isEditorUser}
                    onPatch={patchCard}
                    onOpen={(item) => navigate(item.href)}
                    onDragStart={canDrag ? handleDragStart : undefined}
                    onDragHover={canDrag ? handleDragHover : undefined}
                    onDragEnd={canDrag ? handleDragEnd : undefined}
                  />
                </section>
              )
            })}
          </div>

          <section
            data-drop-id={UNASSIGNED}
            className={`edit-tracker-unassigned${dropTarget === UNASSIGNED ? ' is-drop' : ''}`}
          >
            <header>
              <h2>Unassigned</h2>
              <span>{unassignedItems.length} unassigned</span>
            </header>
            {unassignedItems.length ? (
              <CardsLane
                items={unassignedItems}
                editors={editors}
                days={days}
                compact={compact}
                groupByEditor={false}
                wide
                dragKey={dragKey}
                lockEditor={isEditorUser}
                onPatch={patchCard}
                onOpen={(item) => navigate(item.href)}
                onDragStart={canDrag ? handleDragStart : undefined}
                onDragHover={canDrag ? handleDragHover : undefined}
                onDragEnd={canDrag ? handleDragEnd : undefined}
              />
            ) : (
              <p className="edit-tracker-drop-hint">
                {dropTarget === UNASSIGNED ? 'Drop to unassign' : 'No unassigned work.'}
              </p>
            )}
          </section>
          <div ref={ghostRef} className="edit-work-ghost" aria-hidden="true" />
        </>
      )}

      {assigning ? (
        <div className="edit-assign-overlay" role="status" aria-live="polite">
          <div className="edit-assign-spinner" aria-hidden="true">
            {Array.from({ length: 8 }, (_, index) => (
              <span key={index} style={{ '--i': index }} />
            ))}
          </div>
          <p>{thisWeek ? 'Assigning this week’s work…' : 'Assigning next week’s work…'}</p>
        </div>
      ) : null}
    </div>
  )
}

export function editorTone(editorId) {
  if (editorId === 'yash') return 'yash'
  if (editorId === 'roshan') return 'roshan'
  if (editorId === 'test-editor') return 'test'
  return 'plain'
}

function groupItemsByEditor(items, editors) {
  const buckets = new Map()
  for (const editor of editors || []) {
    buckets.set(editor.id, { id: editor.id, name: editor.name, items: [] })
  }
  buckets.set('', { id: '', name: 'Unassigned', items: [] })
  for (const item of items) {
    const id = item.editor_id || ''
    if (!buckets.has(id)) {
      buckets.set(id, { id, name: id || 'Unassigned', items: [] })
    }
    buckets.get(id).items.push(item)
  }
  return [...buckets.values()].filter((group) => group.items.length)
}

function latestNotePreview(item) {
  const feedback = item.feedback_notes_preview || []
  const editorNotes = item.editor_notes_preview || []
  const feedbackCount = Number(item.feedback_note_count) || feedback.length || 0
  const editorCount = Number(item.editor_note_count) || editorNotes.length || 0
  const newest = [...editorNotes, ...feedback].find((note) => strNoteText(note))
  return {
    feedbackCount,
    editorCount,
    newest,
  }
}

function strNoteText(note) {
  return String(note?.text || '').trim()
}

function shortAuthor(value) {
  const raw = String(value || '').trim()
  if (!raw) return 'note'
  const at = raw.indexOf('@')
  if (at > 0) return raw.slice(0, at)
  return raw
}

function CardsLane({
  items,
  editors,
  days,
  compact,
  groupByEditor,
  wide,
  dragKey,
  emptyHint,
  lockEditor = false,
  onPatch,
  onOpen,
  onDragStart,
  onDragHover,
  onDragEnd,
}) {
  const cardProps = {
    editors,
    days,
    compact,
    lockEditor,
    onPatch,
    onOpen,
    onDragStart,
    onDragHover,
    onDragEnd,
  }

  function renderCard(item) {
    return (
      <EditWorkCard
        key={cardKey(item)}
        item={item}
        dragging={dragKey === cardKey(item)}
        {...cardProps}
        onOpen={() => onOpen(item)}
      />
    )
  }

  if (!items.length) {
    return emptyHint ? <p className="edit-tracker-drop-hint">{emptyHint}</p> : null
  }

  if (!groupByEditor) {
    return <div className={wide ? 'edit-tracker-unassigned-grid' : 'edit-tracker-day-cards'}>{items.map(renderCard)}</div>
  }

  const groups = groupItemsByEditor(items, editors)
  return (
    <div className={wide ? 'edit-tracker-unassigned-groups' : 'edit-tracker-day-cards'}>
      {groups.map((group) => {
        const hours = group.items.reduce((sum, item) => sum + (Number(item.edit_hours) || 0), 0)
        return (
          <div key={group.id || 'unassigned'} className={`edit-editor-group is-${editorTone(group.id)}${wide ? ' is-wide' : ''}`}>
            <header className="edit-editor-group-head" title={`${group.name} · ${hoursLabel(hours)}`}>
              <i className={`edit-field-dot is-${editorTone(group.id)}`} />
              <strong>{group.name}</strong>
              <em>{hoursLabel(hours)}</em>
            </header>
            <div className={wide ? 'edit-tracker-unassigned-grid' : 'edit-editor-group-cards'}>
              {group.items.map(renderCard)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function EditFieldMenu({ label, value, options, tone, onChange }) {
  const [open, setOpen] = useState(false)
  const [menuStyle, setMenuStyle] = useState(null)
  const ref = useRef(null)
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  const selected = options.find((option) => option.value === value) || options[0]
  const selectedTone = selected?.tone || tone || 'plain'

  const placeMenu = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    const width = Math.max(rect.width, 196)
    const openUp = window.innerHeight - rect.bottom < 240 && rect.top > 240
    const alignRight = rect.left + width > window.innerWidth - 12
    setMenuStyle({
      top: openUp ? undefined : rect.bottom + 6,
      bottom: openUp ? window.innerHeight - rect.top + 6 : undefined,
      left: alignRight ? undefined : Math.max(12, rect.left),
      right: alignRight ? Math.max(12, window.innerWidth - rect.right) : undefined,
      width,
    })
  }, [])

  useLayoutEffect(() => {
    if (!open) return undefined
    placeMenu()
    window.addEventListener('resize', placeMenu)
    window.addEventListener('scroll', placeMenu, true)
    return () => {
      window.removeEventListener('resize', placeMenu)
      window.removeEventListener('scroll', placeMenu, true)
    }
  }, [open, placeMenu])

  useEffect(() => {
    if (!open) return undefined
    function onDoc(event) {
      if (ref.current?.contains(event.target) || menuRef.current?.contains(event.target)) return
      setOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div
      className={`edit-field is-${selectedTone}${open ? ' is-open' : ''}`}
      ref={ref}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <span className="edit-field-label">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="edit-field-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {selected?.swatch ? <i className={`edit-field-dot is-${selectedTone}`} /> : null}
        <span className="edit-field-copy">
          <strong>{selected?.label || 'Unassigned'}</strong>
          {selected?.detail ? <em>{selected.detail}</em> : null}
        </span>
        <i className={`fa-solid fa-chevron-down${open ? ' is-open' : ''}`} />
      </button>
      {open
        ? createPortal(
            <div
              ref={menuRef}
              className="edit-field-menu"
              role="listbox"
              style={menuStyle || { visibility: 'hidden' }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {options.map((option) => {
                const on = option.value === value
                return (
                  <button
                    key={option.value || 'unassigned'}
                    type="button"
                    role="option"
                    aria-selected={on}
                    className={`edit-field-option is-${option.tone || 'plain'}${on ? ' is-on' : ''}`}
                    onClick={() => {
                      onChange(option.value)
                      setOpen(false)
                    }}
                  >
                    {option.swatch ? <i className={`edit-field-dot is-${option.tone || 'plain'}`} /> : null}
                    <span className="edit-field-copy">
                      <strong>{option.label}</strong>
                      {option.detail ? <em>{option.detail}</em> : null}
                    </span>
                    {on ? <i className="fa-solid fa-check" /> : null}
                  </button>
                )
              })}
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}

function EditWorkCard({
  item,
  editors,
  days,
  compact,
  dragging,
  lockEditor = false,
  onPatch,
  onOpen,
  onDragStart,
  onDragHover,
  onDragEnd,
}) {
  const cardRef = useRef(null)
  const canDrag = typeof onDragStart === 'function'
  const overflow = item.spill && item.spill_reason === 'editor spill'
  const editorOptions = useMemo(() => ([
    { value: '', label: 'Unassigned', detail: 'No editor yet', tone: 'plain', swatch: true },
    ...editors.map((editor) => ({
      value: editor.id,
      label: editor.name,
      detail: editor.max_hours_per_day ? `${editor.max_hours_per_day}h / day` : '',
      tone: editorTone(editor.id),
      swatch: true,
    })),
  ]), [editors])
  const cardTone = editorTone(item.editor_id)
  const dayOptions = useMemo(() => ([
    { value: '', label: 'Unassigned', detail: 'No edit day', tone: cardTone, swatch: true },
    ...days.map((day) => ({
      value: day.date,
      label: day.weekday,
      detail: day.label,
      tone: cardTone,
      swatch: true,
    })),
  ]), [days, cardTone])

  function handlePointerDown(event) {
    if (event.button !== 0) return
    if (event.target.closest('select, input, button, label, a')) return
    if (!canDrag) {
      onOpen()
      return
    }
    event.preventDefault()
    const pointerId = event.pointerId
    const originX = event.clientX
    const originY = event.clientY
    let active = false
    let lastDrop = null
    const card = cardRef.current

    function finish(dropId) {
      try {
        card?.releasePointerCapture?.(pointerId)
      } catch {
        /* already released */
      }
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      onDragEnd?.(item, dropId)
    }

    function onMove(ev) {
      const dx = ev.clientX - originX
      const dy = ev.clientY - originY
      if (!active) {
        if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
        active = true
        onDragStart(item, {
          rect: card?.getBoundingClientRect?.() || { left: originX, top: originY, width: 240 },
          clientX: ev.clientX,
          clientY: ev.clientY,
        })
        try {
          card?.setPointerCapture(pointerId)
        } catch {
          /* Safari can throw if the node is gone */
        }
      }
      ev.preventDefault()
      const dropId = dropIdFromPoint(ev.clientX, ev.clientY)
      lastDrop = dropId
      onDragHover?.(dropId, { x: ev.clientX, y: ev.clientY })
    }

    function onUp(ev) {
      if (!active) {
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('pointercancel', onCancel)
        onOpen()
        return
      }
      finish(dropIdFromPoint(ev.clientX, ev.clientY) || lastDrop)
    }

    function onCancel() {
      if (active) {
        finish(undefined)
        return
      }
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
    }

    window.addEventListener('pointermove', onMove, { passive: false })
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
  }

  return (
    <article
      ref={cardRef}
      className={`edit-work-card is-${editorTone(item.editor_id)}${overflow ? ' is-spill' : ''}${item.late ? ' is-late' : ''}${dragging ? ' is-dragging' : ''}${compact ? ' is-micro' : ''}`}
      onPointerDown={handlePointerDown}
    >
      <div className="edit-work-top">
        <span className="edit-work-grip" aria-hidden="true">
          <i className="fa-solid fa-grip-vertical" />
        </span>
        <span className={`tracker-pill ${TYPE_PILL[item.type] || ''}`}>{typeLabel(item.type)}</span>
        {item.late ? <span className="tracker-pill tracker-pill-delay">Late</span> : null}
        <em>{hoursLabel(item.edit_hours)}</em>
      </div>
      <strong>{item.client_name}</strong>
      <p>{videoTaskLabel(item)}</p>
      {compact || lockEditor ? null : (
        <div className="edit-work-fields">
          <EditFieldMenu
            label="Editor"
            value={item.editor_id || ''}
            tone={cardTone}
            options={editorOptions}
            onChange={(editorId) => onPatch(item, { editor_id: editorId })}
          />
          <EditFieldMenu
            label="Edit day"
            value={item.planned_edit_date || ''}
            tone={cardTone}
            options={dayOptions}
            onChange={(plannedEditDate) => onPatch(item, { planned_edit_date: plannedEditDate })}
          />
        </div>
      )}
      {compact ? null : (() => {
        const { newest } = latestNotePreview(item)
        if (!newest || !strNoteText(newest)) return null
        return (
          <div
            className="edit-work-notes"
            onPointerDown={(event) => event.stopPropagation()}
          >
            <p className="edit-work-note-preview">
              <strong>{shortAuthor(newest.created_by)}</strong>
              {strNoteText(newest)}
            </p>
          </div>
        )
      })()}
      {overflow ? <small>Over capacity</small> : null}
    </article>
  )
}
