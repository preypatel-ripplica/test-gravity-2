import { useEffect, useRef, useState } from 'react'
import { emptyTask, formatDueDate, sortTasksCompletedLast } from './customTrackerUtils'

function DuePicker({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    function onDoc(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className="ct-due" ref={wrapRef}>
      <button
        type="button"
        className={`ct-due-btn${value ? ' has-date' : ''}`}
        title={value ? 'Change due date' : 'Set due date'}
        onClick={() => setOpen((v) => !v)}
      >
        {value ? formatDueDate(value) : <i className="fa-regular fa-calendar" />}
      </button>
      {open ? (
        <div className="ct-due-pop">
          <input
            type="date"
            value={value || ''}
            onChange={(event) => {
              onChange(event.target.value)
              setOpen(false)
            }}
          />
        </div>
      ) : null}
    </div>
  )
}

function AddRow({ placeholder, onAdd }) {
  const [text, setText] = useState('')

  function commit() {
    const title = text.trim()
    if (!title) return
    onAdd(title)
    setText('')
  }

  return (
    <div className="ct-task ct-composer">
      <span className="ct-check ct-check-ghost">
        <input type="checkbox" disabled tabIndex={-1} />
      </span>
      <input
        className="ct-inline-input"
        placeholder={placeholder}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
        }}
      />
    </div>
  )
}

function TaskRow({ task, onChange, onRemove }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(task.comment || '')
  const comment = String(task.comment || '').trim()

  function startEdit() {
    setDraft(task.comment || '')
    setEditing(true)
  }

  function saveComment() {
    onChange({ ...task, comment: draft.trim() })
    setEditing(false)
  }

  function deleteComment() {
    setDraft('')
    onChange({ ...task, comment: '' })
    setEditing(false)
  }

  return (
    <div className="ct-task-block">
      <div className={`ct-task${task.done ? ' is-complete' : ''}`}>
        <label className="ct-check">
          <input
            type="checkbox"
            checked={Boolean(task.done)}
            onChange={(event) => onChange({ ...task, done: event.target.checked })}
          />
        </label>
        <input
          className={`ct-inline-input${task.done ? ' is-done' : ''}`}
          value={task.title}
          placeholder="Task"
          onChange={(event) => onChange({ ...task, title: event.target.value })}
        />
        <DuePicker value={task.due_date || ''} onChange={(due_date) => onChange({ ...task, due_date })} />
        <button
          type="button"
          className={`ct-icon-btn${comment ? ' is-on' : ''}`}
          title={comment ? 'Edit comment' : 'Add comment'}
          onClick={startEdit}
        >
          <i className="fa-solid fa-pen" />
        </button>
        <button type="button" className="ct-icon-btn" title="Remove" onClick={onRemove}>
          <i className="fa-solid fa-xmark" />
        </button>
      </div>
      {comment && !editing ? <p className="ct-comment-preview">{comment}</p> : null}
      {editing ? (
        <div className="ct-comment-edit">
          <textarea
            className="ct-comment-input"
            rows={2}
            value={draft}
            placeholder="Add a comment"
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                setEditing(false)
                setDraft(task.comment || '')
              }
            }}
          />
          <div className="ct-comment-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={saveComment}>
              Save
            </button>
            {comment ? (
              <button type="button" className="btn btn-secondary btn-sm" onClick={deleteComment}>
                Delete
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setEditing(false)
                setDraft(task.comment || '')
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function CustomBoard({ tasks = [], onChange }) {
  const [hideCompleted, setHideCompleted] = useState(false)
  const rows = sortTasksCompletedLast(tasks || [])
  const openTasks = rows.filter((task) => !task.done)
  const completedTasks = rows.filter((task) => task.done)
  const hasCompleted = completedTasks.length > 0

  function updateTasks(updater) {
    onChange((prev) => sortTasksCompletedLast(updater(prev || [])))
  }

  function patchTask(taskId, nextTask) {
    updateTasks((prev) => prev.map((row) => (row.id === taskId ? nextTask : row)))
  }

  return (
    <div className="ct-board">
      <div className="ct-board-head">
        <div>
          <h2>To-dos</h2>
          <p>Tasks and due dates for this client.</p>
        </div>
      </div>

      <div className="ct-category-stack">
        <article className="ct-issue">
          <div className="ct-task-list">
            {openTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onChange={(next) => patchTask(task.id, next)}
                onRemove={() => updateTasks((prev) => prev.filter((row) => row.id !== task.id))}
              />
            ))}
            <AddRow
              placeholder="Add task"
              onAdd={(title) => updateTasks((prev) => {
                const next = emptyTask(title)
                const firstDone = prev.findIndex((row) => row.done)
                if (firstDone === -1) return [...prev, next]
                return [...prev.slice(0, firstDone), next, ...prev.slice(firstDone)]
              })}
            />
            {!hideCompleted
              ? completedTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  onChange={(next) => patchTask(task.id, next)}
                  onRemove={() => updateTasks((prev) => prev.filter((row) => row.id !== task.id))}
                />
              ))
              : null}
            {hasCompleted ? (
              <button
                type="button"
                className="ct-text-btn ct-hide-completed"
                onClick={() => setHideCompleted((value) => !value)}
              >
                {hideCompleted ? 'Show completed' : 'Hide completed'}
              </button>
            ) : null}
          </div>
        </article>
      </div>
    </div>
  )
}
