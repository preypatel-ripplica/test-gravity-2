import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import CustomSelect from '../components/CustomSelect'
import { emptyTask, formatDueDate } from '../components/custom-tracker/customTrackerUtils'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import { todayParts } from '../components/tracker/trackerUtils'

const TONE_RANK = { urgent: 0, pending: 1, completed: 2, upcoming: 3 }

const SOURCE_OPTIONS = [
  { id: 'default', label: 'Deliverables' },
  { id: 'custom', label: 'Custom to-dos' },
]

const WEEK_OPTIONS = [
  { id: 'past', label: 'Late' },
  { id: 'current', label: 'Current week' },
  { id: 'next', label: 'Next week' },
]

const STATUS_OPTIONS = [
  { id: 'pending', label: 'Pending' },
  { id: 'urgent', label: 'Late' },
  { id: 'completed', label: 'Completed' },
]

function weekKey(year, month, week) {
  return (Number(year) || 0) * 1000 + (Number(month) || 0) * 10 + (Number(week) || 0)
}

function periodOf(row, today) {
  if (row.year && row.week) {
    const rowKey = weekKey(row.year, row.month, row.week)
    const nowKey = weekKey(today.year, today.month, today.week)
    if (rowKey < nowKey) return 'past'
    if (rowKey > nowKey) return 'next'
    return 'current'
  }
  if (row.tone === 'upcoming') return 'next'
  if (row.tone === 'urgent') return 'past'
  return 'current'
}

function rowGroup(row, today) {
  if (periodOf(row, today) === 'next') return 2
  if (row.source === 'custom') return 1
  return 0
}

function sortRows(rows, today) {
  return [...rows].sort((a, b) => {
    const groupDiff = rowGroup(a, today) - rowGroup(b, today)
    if (groupDiff) return groupDiff
    const clientDiff = String(a.client_name || '').localeCompare(String(b.client_name || ''), undefined, { sensitivity: 'base' })
    if (clientDiff) return clientDiff
    return (TONE_RANK[a.tone] ?? 9) - (TONE_RANK[b.tone] ?? 9)
  })
}

function toneClass(tone) {
  if (tone === 'urgent') return 'is-urgent'
  if (tone === 'completed') return 'is-completed'
  if (tone === 'upcoming') return 'is-pending is-upcoming'
  return 'is-pending'
}

function periodLabel(row, today) {
  if (row.source === 'custom') return 'Custom'
  const period = periodOf(row, today)
  if (period === 'next') return 'Next week'
  return ''
}

function rowSource(row) {
  return row.source === 'custom' ? 'custom' : 'default'
}

function matchesSource(row, sources) {
  if (sources === 'all') return true
  if (!sources.length) return false
  return sources.includes(rowSource(row))
}

function statusBucket(row) {
  if (row.tone === 'urgent') return 'urgent'
  if (row.tone === 'completed') return 'completed'
  return 'pending'
}

function isPicked(selected, id) {
  return selected === 'all' || selected.includes(id)
}

function togglePicked(selected, id, allIds) {
  const current = selected === 'all' ? allIds : selected
  const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
  return next.length === allIds.length ? 'all' : next
}

function summaryLabel(options, selected, allLabel) {
  if (selected === 'all') return allLabel
  if (!selected.length) return 'None'
  if (selected.length === 1) {
    return options.find((item) => item.id === selected[0])?.label || allLabel
  }
  return `${selected.length} selected`
}

function statusText(row) {
  if (row.tone === 'upcoming') return 'Script pending'
  if (row.tone === 'urgent') return 'Late'
  return row.status || (row.tone === 'completed' ? 'Done' : '')
}

function currentWeekStart(today) {
  const starts = [1, 8, 15, 22]
  const day = starts[Math.max(0, Math.min(3, (today.week || 1) - 1))]
  return `${today.year}-${String(today.month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function customTone(dueDate, done, today) {
  if (done) return 'completed'
  if (dueDate && dueDate < currentWeekStart(today)) return 'urgent'
  return 'pending'
}

function applyCustomPatch(row, patch, today) {
  const next = { ...row }
  if (patch.title != null) next.task = patch.title
  if (patch.due_date != null) next.due_date = patch.due_date
  if (patch.done != null) {
    next.completed = patch.done
    next.status_id = patch.done ? 'done' : 'in_progress'
    next.status = patch.done ? 'Done' : 'In progress'
  }
  next.tone = customTone(next.due_date, next.completed, today)
  return next
}

function customListRow(clientId, clientName, task, today) {
  return {
    source: 'custom',
    client_id: clientId,
    client_name: clientName,
    task: task.title || '',
    status: 'In progress',
    status_id: 'in_progress',
    due_date: task.due_date || '',
    comment: '',
    href: `/clients/${clientId}/tracker/custom`,
    week: today.week,
    year: today.year,
    month: today.month,
    completed: false,
    tone: customTone(task.due_date, false, today),
    content_type: 'custom',
    task_id: task.id,
  }
}

function TaskMeta({ row, today }) {
  const when = periodLabel(row, today)
  const status = row.tone === 'upcoming' ? '' : row.status
  return (
    <span className="all-tracker-pending-meta">
      {when ? <span className="all-tracker-source">{when}</span> : null}
      {status ? <span>{status}</span> : null}
      <span className={!row.due_date ? 'is-muted' : ''}>
        {row.due_date ? formatDueDate(row.due_date) : 'No due date'}
      </span>
    </span>
  )
}

function ExternalTaskLink({ href, className, children }) {
  if (!href) return <span className={className}>{children}</span>
  return (
    <a className={className} href={href} target="_blank" rel="noreferrer" title="Open in new tab">
      {children}
    </a>
  )
}

function FilterDropdown({ label, allLabel, options, selected, onChange, searchable = true }) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
  const boxRef = useRef(null)
  const allIds = options.map((item) => item.id)
  const query = needle.trim().toLowerCase()
  const visible = query
    ? options.filter((item) => item.label.toLowerCase().includes(query))
    : options

  useEffect(() => {
    if (!open) {
      setNeedle('')
      return undefined
    }
    function handlePointer(event) {
      if (boxRef.current && !boxRef.current.contains(event.target)) setOpen(false)
    }
    function handleKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  function selectVisible(on) {
    const visibleIds = visible.map((item) => item.id)
    if (on) {
      const next = new Set([...(selected === 'all' ? allIds : selected), ...visibleIds])
      onChange(next.size === allIds.length ? 'all' : [...next])
      return
    }
    const hide = new Set(visibleIds)
    const current = selected === 'all' ? allIds : selected
    onChange(current.filter((id) => !hide.has(id)))
  }

  return (
    <div className="all-trackers-dd" ref={boxRef}>
      <button
        type="button"
        className={`all-trackers-dd-btn${open ? ' is-open' : ''}${selected !== 'all' ? ' is-filtered' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="all-trackers-dd-copy">
          <span className="all-trackers-dd-kicker">{label}</span>
          <span className="all-trackers-dd-summary">{summaryLabel(options, selected, allLabel)}</span>
        </span>
        <i className={`fa-solid fa-chevron-down${open ? ' is-open' : ''}`} aria-hidden="true" />
      </button>
      {open ? (
        <div className="all-trackers-dd-menu" role="listbox" aria-multiselectable="true">
          <div className="all-trackers-dd-tools">
            <button type="button" onClick={() => selectVisible(true)}>Select all</button>
            <button type="button" onClick={() => selectVisible(false)}>Deselect all</button>
          </div>
          {searchable ? (
            <input
              className="form-control all-trackers-dd-search"
              value={needle}
              placeholder={`Search ${label.toLowerCase()}`}
              onChange={(event) => setNeedle(event.target.value)}
            />
          ) : null}
          <ul className="all-trackers-dd-list">
            {visible.length === 0 ? (
              <li className="all-trackers-dd-empty">No matches</li>
            ) : visible.map((item) => (
              <li key={item.id}>
                <label className="all-trackers-dd-option">
                  <input
                    type="checkbox"
                    checked={isPicked(selected, item.id)}
                    onChange={() => onChange(togglePicked(selected, item.id, allIds))}
                  />
                  <span>{item.label}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function CustomTaskEditor({ row, onPatch, autoFocus }) {
  return (
    <>
      <input
        className="sheet-cell-input"
        value={row.task || ''}
        aria-label="Task name"
        autoFocus={autoFocus}
        onChange={(event) => onPatch(row, { title: event.target.value }, { debounce: true })}
        onBlur={(event) => {
          const title = event.target.value.trim()
          if (!title) {
            onPatch(row, {}, { restoreTitle: true })
            return
          }
          onPatch(row, { title })
        }}
      />
      {row.href ? (
        <a
          className="all-trackers-list-open"
          href={row.href}
          target="_blank"
          rel="noreferrer"
          title="Open custom to-dos"
        >
          <i className="fa-solid fa-arrow-up-right-from-square" aria-hidden="true" />
        </a>
      ) : null}
    </>
  )
}

function CustomClientSelect({ row, options, onMove }) {
  const hasCurrent = options.some((item) => item.id === row.client_id)
  const choices = hasCurrent
    ? options
    : [{ id: row.client_id, label: row.client_name || 'Untitled client' }, ...options]
  return (
    <div className="all-trackers-list-client">
      <CustomSelect
        compact
        className="sheet-cell-select all-trackers-list-client-select"
        ariaLabel="Client"
        value={row.client_id}
        onChange={(next) => onMove(row, next)}
        searchable={choices.length > 8}
        options={choices.map((item) => ({ value: item.id, label: item.label }))}
      />
      <a
        className="all-trackers-list-open"
        href={`/clients/${row.client_id}`}
        target="_blank"
        rel="noreferrer"
        title="Open client"
      >
        <i className="fa-solid fa-arrow-up-right-from-square" aria-hidden="true" />
      </a>
    </div>
  )
}

export default function PocWeeklyTracker() {
  const { token, user } = useAuth()
  const { toast } = useUI()
  const today = useMemo(() => todayParts(), [])
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('cards')
  const [query, setQuery] = useState('')
  const [clientIds, setClientIds] = useState('all')
  const [sources, setSources] = useState('all')
  const [weeks, setWeeks] = useState('all')
  const [statuses, setStatuses] = useState('all')
  const [focusTaskId, setFocusTaskId] = useState('')
  const pendingPatches = useRef({})
  const saveTimers = useRef({})
  const clientSaves = useRef({})
  const lastSaved = useRef({})

  const activeClients = useMemo(
    () => (user?.clients || []).filter((client) => client.is_active !== false),
    [user?.clients],
  )
  const clientOptions = useMemo(
    () => activeClients.map((client) => ({ id: client.id, label: client.name || 'Untitled client' })),
    [activeClients],
  )

  const loadRows = useCallback(async ({ quiet } = {}) => {
    if (!token) return
    if (!quiet) setLoading(true)
    try {
      const result = await api.getTrackerSheetAll(token, today.year, today.month)
      const nextRows = result.rows || []
      const saved = {}
      for (const row of nextRows) {
        if (row.source === 'custom' && row.task_id) {
          saved[`${row.client_id}:${row.task_id}`] = {
            title: row.task || '',
            due_date: row.due_date || '',
            done: Boolean(row.completed),
          }
        }
      }
      lastSaved.current = saved
      setRows(nextRows)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [token, toast, today.month, today.year])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  const persistCustomPatch = useCallback(async (clientId, taskId, patch) => {
    const previous = clientSaves.current[clientId] || Promise.resolve()
    const next = previous.then(async () => {
      const result = await api.getCustomTracker(token, clientId)
      const tasks = (result.tracker?.tasks || []).map((task) => (
        String(task.id) === String(taskId) ? { ...task, ...patch } : task
      ))
      if (!tasks.some((task) => String(task.id) === String(taskId))) {
        throw new Error('That custom to-do was not found.')
      }
      await api.saveCustomTracker(token, clientId, tasks)
      const key = `${clientId}:${taskId}`
      lastSaved.current[key] = {
        ...(lastSaved.current[key] || {}),
        ...patch,
        title: patch.title != null ? patch.title : lastSaved.current[key]?.title,
        due_date: patch.due_date != null ? patch.due_date : lastSaved.current[key]?.due_date,
        done: patch.done != null ? patch.done : lastSaved.current[key]?.done,
      }
    }).catch(async (err) => {
      toast(err.message, 'error')
      await loadRows({ quiet: true })
    })
    clientSaves.current[clientId] = next.catch(() => {})
    return next
  }, [loadRows, toast, token])

  const persistCustomAdd = useCallback(async (clientId, afterTaskId, task) => {
    const previous = clientSaves.current[clientId] || Promise.resolve()
    const next = previous.then(async () => {
      const result = await api.getCustomTracker(token, clientId)
      const current = result.tracker?.tasks || []
      const idx = afterTaskId
        ? current.findIndex((item) => String(item.id) === String(afterTaskId))
        : -1
      const tasks = idx === -1
        ? [...current, task]
        : [...current.slice(0, idx + 1), task, ...current.slice(idx + 1)]
      await api.saveCustomTracker(token, clientId, tasks)
      lastSaved.current[`${clientId}:${task.id}`] = {
        title: task.title || '',
        due_date: task.due_date || '',
        done: false,
      }
    }).catch(async (err) => {
      toast(err.message, 'error')
      await loadRows({ quiet: true })
    })
    clientSaves.current[clientId] = next.catch(() => {})
    return next
  }, [loadRows, toast, token])

  const persistCustomMove = useCallback(async (fromClientId, toClientId, taskId, extraPatch = {}) => {
    if (!fromClientId || !toClientId || fromClientId === toClientId) return
    const previous = Promise.all([
      clientSaves.current[fromClientId] || Promise.resolve(),
      clientSaves.current[toClientId] || Promise.resolve(),
    ])
    const next = previous.then(async () => {
      const sourceResult = await api.getCustomTracker(token, fromClientId)
      const sourceTasks = sourceResult.tracker?.tasks || []
      const idx = sourceTasks.findIndex((task) => String(task.id) === String(taskId))
      if (idx === -1) throw new Error('That custom to-do was not found.')
      const moved = { ...sourceTasks[idx], ...extraPatch }
      if (moved.title != null) moved.title = String(moved.title).trim()
      const remaining = sourceTasks.filter((_, index) => index !== idx)
      const destResult = await api.getCustomTracker(token, toClientId)
      const destTasks = destResult.tracker?.tasks || []
      const nextDest = destTasks.some((task) => String(task.id) === String(moved.id))
        ? destTasks.map((task) => (String(task.id) === String(moved.id) ? { ...task, ...moved } : task))
        : [...destTasks, moved]
      await api.saveCustomTracker(token, fromClientId, remaining)
      await api.saveCustomTracker(token, toClientId, nextDest)
      const oldKey = `${fromClientId}:${taskId}`
      const newKey = `${toClientId}:${moved.id}`
      delete lastSaved.current[oldKey]
      lastSaved.current[newKey] = {
        title: moved.title || '',
        due_date: moved.due_date || '',
        done: Boolean(moved.done),
      }
    }).catch(async (err) => {
      toast(err.message, 'error')
      await loadRows({ quiet: true })
    })
    clientSaves.current[fromClientId] = next.catch(() => {})
    clientSaves.current[toClientId] = next.catch(() => {})
    return next
  }, [loadRows, toast, token])

  const addCustomForRow = useCallback((row) => {
    if (!row.client_id) return
    const task = emptyTask()
    const nextRow = customListRow(row.client_id, row.client_name, task, today)
    lastSaved.current[`${row.client_id}:${task.id}`] = {
      title: '',
      due_date: task.due_date || '',
      done: false,
    }
    setFocusTaskId(task.id)
    setRows((current) => {
      const idx = current.findIndex((item) => item === row)
      if (idx === -1) return [...current, nextRow]
      return [...current.slice(0, idx + 1), nextRow, ...current.slice(idx + 1)]
    })
    if (sources !== 'all' && !(Array.isArray(sources) && sources.includes('custom'))) {
      setSources(sources.length ? [...sources, 'custom'] : ['custom'])
    }
    persistCustomAdd(row.client_id, row.source === 'custom' ? row.task_id : null, task)
  }, [persistCustomAdd, sources, today])

  const patchCustom = useCallback((row, patch, options = {}) => {
    if (!row.client_id || !row.task_id) return
    const key = `${row.client_id}:${row.task_id}`
    if (options.restoreTitle) {
      clearTimeout(saveTimers.current[key])
      const pending = pendingPatches.current[key] || {}
      delete pending.title
      if (Object.keys(pending).length) pendingPatches.current[key] = pending
      else delete pendingPatches.current[key]
      const saved = lastSaved.current[key]
      setRows((current) => current.map((item) => (
        item.client_id === row.client_id && item.task_id === row.task_id
          ? applyCustomPatch(item, { title: saved?.title || '' }, today)
          : item
      )))
      return
    }
    if (patch.title != null && !String(patch.title).trim()) {
      clearTimeout(saveTimers.current[key])
      const pending = pendingPatches.current[key] || {}
      delete pending.title
      if (Object.keys(pending).length) pendingPatches.current[key] = pending
      else delete pendingPatches.current[key]
      setRows((current) => current.map((item) => (
        item.client_id === row.client_id && item.task_id === row.task_id
          ? { ...item, task: patch.title }
          : item
      )))
      return
    }
    pendingPatches.current[key] = { ...(pendingPatches.current[key] || {}), ...patch }
    setRows((current) => current.map((item) => (
      item.client_id === row.client_id && item.task_id === row.task_id
        ? applyCustomPatch(item, patch, today)
        : item
    )))
    clearTimeout(saveTimers.current[key])
    const flush = () => {
      const body = pendingPatches.current[key]
      if (!body) return
      delete pendingPatches.current[key]
      if (body.title != null) {
        body.title = String(body.title).trim()
        if (!body.title) return
      }
      persistCustomPatch(row.client_id, row.task_id, body)
    }
    if (options.debounce) {
      saveTimers.current[key] = setTimeout(flush, 450)
      return
    }
    flush()
  }, [persistCustomPatch, today])

  const moveCustom = useCallback((row, nextClientId) => {
    if (!row.client_id || !row.task_id || nextClientId === row.client_id) return
    const client = activeClients.find((item) => item.id === nextClientId)
    if (!client) return
    const key = `${row.client_id}:${row.task_id}`
    clearTimeout(saveTimers.current[key])
    const pending = { ...(pendingPatches.current[key] || {}) }
    delete pendingPatches.current[key]
    if (pending.title != null) {
      pending.title = String(pending.title).trim()
      if (!pending.title) delete pending.title
    }
    const patched = applyCustomPatch(row, pending, today)
    setRows((current) => current.map((item) => (
      item.client_id === row.client_id && item.task_id === row.task_id
        ? {
            ...patched,
            client_id: client.id,
            client_name: client.name || 'Untitled client',
            href: `/clients/${client.id}/tracker/custom`,
          }
        : item
    )))
    const oldKey = `${row.client_id}:${row.task_id}`
    const newKey = `${client.id}:${row.task_id}`
    lastSaved.current[newKey] = {
      ...(lastSaved.current[oldKey] || {}),
      ...pending,
      title: pending.title != null ? pending.title : lastSaved.current[oldKey]?.title,
      due_date: pending.due_date != null ? pending.due_date : lastSaved.current[oldKey]?.due_date,
      done: pending.done != null ? pending.done : lastSaved.current[oldKey]?.done,
    }
    delete lastSaved.current[oldKey]
    persistCustomMove(row.client_id, client.id, row.task_id, pending)
  }, [activeClients, persistCustomMove, today])

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return sortRows(rows.filter((row) => {
      if (!matchesSource(row, sources)) return false
      if (clientIds !== 'all' && !clientIds.includes(row.client_id)) return false
      if (needle) {
        const haystack = `${row.client_name || ''} ${row.task || ''}`.toLowerCase()
        if (!haystack.includes(needle)) return false
      }
      if (rowSource(row) === 'custom' && (row.completed || row.tone === 'completed')) return false
      if (rowSource(row) !== 'custom' && weeks !== 'all' && !weeks.includes(periodOf(row, today))) return false
      if (statuses !== 'all' && !statuses.includes(statusBucket(row))) return false
      return true
    }), today)
  }, [clientIds, query, rows, sources, statuses, today, weeks])

  const filtersIdle = (
    clientIds === 'all'
    && sources === 'all'
    && weeks === 'all'
    && statuses === 'all'
    && !query.trim()
  )

  const cards = useMemo(() => {
    const byClient = new Map()
    for (const row of filteredRows) {
      const id = row.client_id
      if (!id) continue
      if (!byClient.has(id)) byClient.set(id, [])
      byClient.get(id).push(row)
    }

    return activeClients
      .filter((client) => clientIds === 'all' || clientIds.includes(client.id))
      .filter((client) => {
        if (!query.trim()) return true
        const needle = query.trim().toLowerCase()
        if ((client.name || '').toLowerCase().includes(needle)) return true
        return (byClient.get(client.id) || []).length > 0
      })
      .map((client) => {
        const tasks = byClient.get(client.id) || []
        return {
          id: client.id,
          name: client.name,
          specialty: client.specialty || '',
          tasks,
          urgentCount: tasks.filter((row) => row.tone === 'urgent').length,
          pendingCount: tasks.filter((row) => row.tone === 'pending' || row.tone === 'upcoming').length,
        }
      })
      .filter((client) => client.tasks.length > 0 || filtersIdle)
      .sort((a, b) => {
        const countDiff = b.tasks.length - a.tasks.length
        if (countDiff) return countDiff
        return String(a.name || '').localeCompare(String(b.name || ''), undefined, { sensitivity: 'base' })
      })
  }, [activeClients, clientIds, filteredRows, filtersIdle, query])

  return (
    <div className="weekly-tracker-page all-trackers-page">
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs items={[{ label: 'All trackers' }]} />
          <h1>All trackers</h1>
          <p>
            Current work plus incomplete past weeks, shown as late. Items marked did not track are not listed.
          </p>
        </div>
        <div className="header-actions">
          <div className="segmented-control" role="tablist" aria-label="All trackers view">
            <button type="button" className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')}>
              Cards
            </button>
            <button type="button" className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>
              List
            </button>
          </div>
        </div>
      </header>

      <div className="all-trackers-filters">
        <div className="all-trackers-filter-row">
          <input
            className="form-control all-trackers-client-search"
            value={query}
            placeholder="Search clients or tasks"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="all-trackers-filter-row all-trackers-dd-row">
          <FilterDropdown
            label="Clients"
            allLabel="All clients"
            options={clientOptions}
            selected={clientIds}
            onChange={setClientIds}
          />
          <FilterDropdown
            label="Show"
            allLabel="Deliverables and custom"
            options={SOURCE_OPTIONS}
            selected={sources}
            onChange={setSources}
            searchable={false}
          />
          <FilterDropdown
            label="Week"
            allLabel="All weeks"
            options={WEEK_OPTIONS}
            selected={weeks}
            onChange={setWeeks}
            searchable={false}
          />
          <FilterDropdown
            label="Status"
            allLabel="All statuses"
            options={STATUS_OPTIONS}
            selected={statuses}
            onChange={setStatuses}
            searchable={false}
          />
        </div>
      </div>

      {loading ? (
        <p className="text-muted sheet-empty">Loading trackers…</p>
      ) : view === 'list' ? (
        filteredRows.length === 0 ? (
          <p className="text-muted sheet-empty">No tasks match those filters.</p>
        ) : (
          <div className="sheet-table-wrap all-trackers-list-wrap">
            <table className="sheet-table sheet-table-all">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Due</th>
                  <th>Client</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, index) => {
                  const custom = rowSource(row) === 'custom'
                  return (
                    <tr
                      key={`${row.client_id}-${row.source}-${row.task_id || row.task}-${row.due_date}-${index}`}
                      className={`all-trackers-list-row ${toneClass(row.tone)}${custom ? ' is-custom' : ''}`}
                    >
                      <td>
                        <div className="all-trackers-list-task">
                          <button
                            type="button"
                            className="all-trackers-list-add"
                            title="Add to-do for this client"
                            aria-label={`Add to-do for ${row.client_name || 'this client'}`}
                            onClick={() => addCustomForRow(row)}
                          >
                            <i className="fa-solid fa-plus" aria-hidden="true" />
                          </button>
                          {custom ? (
                            <CustomTaskEditor
                              row={row}
                              onPatch={patchCustom}
                              autoFocus={focusTaskId === row.task_id}
                            />
                          ) : row.href ? (
                            <ExternalTaskLink className="sheet-task-link" href={row.href}>
                              {row.task}
                              <i className="fa-solid fa-arrow-up-right-from-square all-tracker-open-tab" aria-hidden="true" />
                            </ExternalTaskLink>
                          ) : row.task}
                        </div>
                      </td>
                      <td>
                        {custom ? (
                          <CustomSelect
                            compact
                            className="sheet-cell-select all-trackers-list-status"
                            ariaLabel="Status"
                            value={row.completed ? 'done' : 'in_progress'}
                            onChange={(next) => patchCustom(row, { done: next === 'done' })}
                            options={[
                              { value: 'in_progress', label: 'In progress' },
                              { value: 'done', label: 'Done' },
                            ]}
                          />
                        ) : (statusText(row) || '—')}
                      </td>
                      <td className={!row.due_date && !custom ? 'is-muted' : ''}>
                        {custom ? (
                          <input
                            type="date"
                            className="sheet-cell-input sheet-cell-inline all-trackers-list-due"
                            aria-label="Due date"
                            value={row.due_date || ''}
                            onChange={(event) => patchCustom(row, { due_date: event.target.value })}
                          />
                        ) : (row.due_date ? formatDueDate(row.due_date) : '—')}
                      </td>
                      <td>
                        {custom ? (
                          <CustomClientSelect
                            row={row}
                            options={clientOptions}
                            onMove={moveCustom}
                          />
                        ) : (
                          <Link className="sheet-client-link" to={`/clients/${row.client_id}`} target="_blank" rel="noreferrer">
                            {row.client_name}
                            <i className="fa-solid fa-arrow-up-right-from-square all-tracker-open-tab" aria-hidden="true" />
                          </Link>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      ) : cards.length === 0 ? (
        <p className="text-muted sheet-empty">
          {activeClients.length === 0
            ? 'No active clients yet.'
            : 'No tasks match those filters.'}
        </p>
      ) : (
        <div className="all-trackers-grid">
          {cards.map((client) => (
            <article key={client.id} className="all-tracker-card card">
              <header className="all-tracker-card-head">
                <div className="all-tracker-card-title">
                  <Link className="all-tracker-client-link" to={`/clients/${client.id}`}>
                    {client.name}
                  </Link>
                  {client.specialty ? <p className="text-muted">{client.specialty}</p> : null}
                </div>
                <div className="all-tracker-card-actions">
                  <div className="all-tracker-counts">
                    {client.urgentCount > 0 ? (
                      <span className="all-tracker-count is-urgent">{client.urgentCount} late</span>
                    ) : null}
                    {client.pendingCount > 0 ? (
                      <span className="all-tracker-count is-pending">{client.pendingCount} pending</span>
                    ) : null}
                  </div>
                  <a
                    className="btn btn-secondary btn-sm"
                    href={`/clients/${client.id}/tracker`}
                    target="_blank"
                    rel="noreferrer"
                    title="Open in new tab"
                  >
                    Open tracker
                  </a>
                </div>
              </header>

              <div className="all-tracker-pending card">
                <p className="all-tracker-pending-label">Tasks</p>
                {client.tasks.length === 0 ? (
                  <p className="text-muted all-tracker-pending-empty">No open tasks.</p>
                ) : (
                  <ul className="all-tracker-pending-list">
                    {client.tasks.map((row, index) => (
                      <li key={`${row.source}-${row.task_id || row.task}-${row.status_id}-${row.due_date}-${index}`}>
                        <ExternalTaskLink
                          className={`all-tracker-pending-item ${toneClass(row.tone)}${row.source === 'custom' ? ' is-custom' : ''}`}
                          href={row.href || `/clients/${client.id}/tracker`}
                        >
                          <span className="all-tracker-pending-task-row">
                            <span className="all-tracker-pending-task">{row.task}</span>
                            {row.tone === 'urgent' ? (
                              <span className="all-tracker-urgent-badge">Late</span>
                            ) : null}
                            {row.tone === 'completed' && (periodOf(row, today) !== 'next' || row.status_id === 'posted') ? (
                              <span className="all-tracker-done-badge">Done</span>
                            ) : null}
                            {row.tone === 'upcoming' ? (
                              <span className="all-tracker-script-badge">Script pending</span>
                            ) : null}
                            <i className="fa-solid fa-arrow-up-right-from-square all-tracker-open-tab" aria-hidden="true" />
                          </span>
                          <TaskMeta row={row} today={today} />
                        </ExternalTaskLink>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
