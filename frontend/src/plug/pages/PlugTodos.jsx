import { useEffect, useMemo, useRef, useState } from 'react'
import { useUI } from '../../context/UIContext'
import plugApi from '../api'
import { usePlugAuth } from '../AuthContext'
import PlugPageHeader from '../components/PlugPageHeader'

function sortTodos(list) {
  const open = []
  const done = []
  for (const item of list || []) {
    if (item.done) done.push(item)
    else open.push(item)
  }
  const bySort = (a, b) => (Number(a.sort) || 0) - (Number(b.sort) || 0)
  open.sort(bySort)
  done.sort(bySort)
  return [...open, ...done]
}

function TodoRow({
  todo,
  group,
  draggingId,
  onToggle,
  onDelete,
  onSaveText,
  onDragStart,
  onDragOver,
  onDropRow,
  onDragEnd,
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(todo.text)
  const inputRef = useRef(null)
  const rowRef = useRef(null)

  useEffect(() => {
    setDraft(todo.text)
  }, [todo.text])

  useEffect(() => {
    if (!editing || !inputRef.current) return
    inputRef.current.focus()
    inputRef.current.select()
  }, [editing])

  function finishEdit() {
    if (!editing) return
    setEditing(false)
    const text = draft.trim()
    if (!text) {
      setDraft(todo.text)
      return
    }
    if (text !== todo.text) onSaveText(todo, text)
  }

  return (
    <li
      ref={rowRef}
      className={`plug-todo-row ${todo.done ? 'is-done' : ''} ${draggingId === todo.id ? 'is-dragging' : ''}`}
      onDragOver={onDragOver}
      onDrop={(e) => onDropRow(e, todo, group)}
    >
      <button
        type="button"
        className="plug-todo-grip"
        title="Drag to reorder"
        aria-label="Drag to reorder"
        draggable
        onDragStart={(e) => onDragStart(e, todo, group, rowRef.current)}
        onDragEnd={onDragEnd}
      >
        <i className="fa-solid fa-grip-vertical" />
      </button>
      <input
        type="checkbox"
        checked={Boolean(todo.done)}
        onChange={() => onToggle(todo)}
        aria-label={todo.done ? 'Mark as open' : 'Mark as done'}
      />
      {editing ? (
        <input
          ref={inputRef}
          className="plug-todo-edit"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={finishEdit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              e.currentTarget.blur()
            }
            if (e.key === 'Escape') {
              setDraft(todo.text)
              setEditing(false)
            }
          }}
        />
      ) : (
        <button type="button" className="plug-todo-text" onClick={() => setEditing(true)}>
          {todo.text}
        </button>
      )}
      <button type="button" className="plug-todo-delete" aria-label="Delete todo" onClick={() => onDelete(todo)}>
        <i className="fa-solid fa-trash" />
      </button>
    </li>
  )
}

export default function PlugTodos() {
  const { token } = usePlugAuth()
  const { toast, confirm } = useUI()
  const [todos, setTodos] = useState([])
  const [addDraft, setAddDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [draggingId, setDraggingId] = useState(null)
  const dragRef = useRef({ id: null, group: null })

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await plugApi.listTodos(token)
        if (!cancelled) setTodos(sortTodos(data.todos || []))
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  const openTodos = useMemo(() => todos.filter((t) => !t.done), [todos])
  const doneTodos = useMemo(() => todos.filter((t) => t.done), [todos])

  async function persistOrder(openList, doneList) {
    setTodos(
      sortTodos([
        ...openList.map((t, i) => ({ ...t, done: false, sort: i })),
        ...doneList.map((t, i) => ({ ...t, done: true, sort: i })),
      ]),
    )
    try {
      const data = await plugApi.reorderTodos(token, {
        openIds: openList.map((t) => t.id),
        doneIds: doneList.map((t) => t.id),
      })
      setTodos(sortTodos(data.todos || []))
    } catch (err) {
      toast(err.message, 'error')
      const data = await plugApi.listTodos(token)
      setTodos(sortTodos(data.todos || []))
    }
  }

  async function handleAdd(e) {
    e.preventDefault()
    const text = addDraft.trim()
    if (!text || saving) return
    setSaving(true)
    try {
      const data = await plugApi.createTodo(token, text)
      setTodos(sortTodos(data.todos || []))
      setAddDraft('')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleToggle(todo) {
    const nextDone = !todo.done
    const without = todos.filter((item) => item.id !== todo.id)
    const open = without.filter((t) => !t.done)
    const done = without.filter((t) => t.done)
    const moved = { ...todo, done: nextDone }
    if (nextDone) done.push(moved)
    else open.push(moved)
    await persistOrder(open, done)
  }

  async function handleDelete(todo) {
    const ok = await confirm({
      title: 'Delete todo',
      message: `Remove “${todo.text}”?`,
      isDanger: true,
    })
    if (!ok) return
    const previous = todos
    setTodos((prev) => prev.filter((item) => item.id !== todo.id))
    try {
      const data = await plugApi.deleteTodo(token, todo.id)
      setTodos(sortTodos(data.todos || []))
    } catch (err) {
      setTodos(previous)
      toast(err.message, 'error')
    }
  }

  async function handleSaveText(todo, text) {
    setTodos((prev) => prev.map((item) => (item.id === todo.id ? { ...item, text } : item)))
    try {
      const data = await plugApi.updateTodo(token, { id: todo.id, text })
      setTodos(sortTodos(data.todos || []))
    } catch (err) {
      toast(err.message, 'error')
      const data = await plugApi.listTodos(token)
      setTodos(sortTodos(data.todos || []))
    }
  }

  function onDragStart(event, todo, group, rowEl) {
    dragRef.current = { id: todo.id, group }
    setDraggingId(todo.id)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', todo.id)
    if (rowEl) {
      const rect = rowEl.getBoundingClientRect()
      event.dataTransfer.setDragImage(rowEl, Math.min(24, rect.width / 4), rect.height / 2)
    }
  }

  function onDragOver(event) {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }

  async function dropOn(targetGroup, targetIndex) {
    const dragId = dragRef.current.id
    dragRef.current = { id: null, group: null }
    setDraggingId(null)
    if (!dragId) return
    const item = todos.find((t) => t.id === dragId)
    if (!item) return
    const open = todos.filter((t) => !t.done && t.id !== dragId)
    const done = todos.filter((t) => t.done && t.id !== dragId)
    const moving = { ...item, done: targetGroup === 'done' }
    const dest = targetGroup === 'open' ? open : done
    dest.splice(Math.max(0, Math.min(targetIndex, dest.length)), 0, moving)
    await persistOrder(open, done)
  }

  function onDropRow(event, targetTodo, targetGroup) {
    event.preventDefault()
    event.stopPropagation()
    const list = targetGroup === 'open' ? openTodos : doneTodos
    const targetIndex = list.findIndex((t) => t.id === targetTodo.id)
    if (dragRef.current.id === targetTodo.id && dragRef.current.group === targetGroup) {
      setDraggingId(null)
      return
    }
    dropOn(targetGroup, targetIndex < 0 ? list.length : targetIndex)
  }

  function onDropList(event, targetGroup) {
    event.preventDefault()
    const list = targetGroup === 'open' ? openTodos : doneTodos
    dropOn(targetGroup, list.length)
  }

  function onDragEnd() {
    dragRef.current = { id: null, group: null }
    setDraggingId(null)
  }

  return (
    <div className="plug-page animate-fade-in">
      <PlugPageHeader
        kicker="Todos"
        title="Todos"
        subtitle="Click text to edit. Drag the grip to shuffle. Done items stay at the bottom."
      />

      <form className="card plug-section plug-panel plug-todo-add" onSubmit={handleAdd}>
        <div className="plug-inline-add" style={{ marginBottom: 0 }}>
          <input
            value={addDraft}
            onChange={(e) => setAddDraft(e.target.value)}
            placeholder="Add an action..."
            maxLength={500}
          />
          <button type="submit" className="btn btn-primary" disabled={saving || !addDraft.trim()}>
            {saving ? 'Adding...' : 'Add'}
          </button>
        </div>
      </form>

      {loading ? (
        <p className="text-muted">Loading...</p>
      ) : todos.length === 0 ? (
        <div className="connect-prompt-container card plug-panel">
          <div className="prompt-illustration">
            <i className="fa-solid fa-list-check illustration-icon" />
          </div>
          <h2>No todos yet</h2>
          <p>Add something you need to film, edit, or post. Check it off and it moves down.</p>
        </div>
      ) : (
        <div className="card plug-section plug-panel plug-todo-board">
          <ul className="plug-todo-list" onDragOver={onDragOver} onDrop={(e) => onDropList(e, 'open')}>
            {openTodos.length === 0 ? (
              <li className="text-muted plug-todo-empty-open">Nothing open. Drop here or add an action.</li>
            ) : (
              openTodos.map((todo) => (
                <TodoRow
                  key={todo.id}
                  todo={todo}
                  group="open"
                  draggingId={draggingId}
                  onToggle={handleToggle}
                  onDelete={handleDelete}
                  onSaveText={handleSaveText}
                  onDragStart={onDragStart}
                  onDragOver={onDragOver}
                  onDropRow={onDropRow}
                  onDragEnd={onDragEnd}
                />
              ))
            )}
          </ul>
          {doneTodos.length > 0 && (
            <>
              <div className="plug-todo-done-label">Done</div>
              <ul className="plug-todo-list" onDragOver={onDragOver} onDrop={(e) => onDropList(e, 'done')}>
                {doneTodos.map((todo) => (
                  <TodoRow
                    key={todo.id}
                    todo={todo}
                    group="done"
                    draggingId={draggingId}
                    onToggle={handleToggle}
                    onDelete={handleDelete}
                    onSaveText={handleSaveText}
                    onDragStart={onDragStart}
                    onDragOver={onDragOver}
                    onDropRow={onDropRow}
                    onDragEnd={onDragEnd}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}
