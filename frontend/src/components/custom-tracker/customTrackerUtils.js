import { newId } from '../tracker/trackerUtils'

export const STATUSES = [
  { id: 'todo', label: 'To do' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'done', label: 'Done' },
]

export const PRIORITIES = [
  { id: 'p0', label: 'P0' },
  { id: 'p1', label: 'P1' },
  { id: 'p2', label: 'P2' },
]

export function emptyCategory(name = 'New category') {
  return {
    id: newId('cat'),
    name,
    is_default: false,
    collapsed: false,
    issues: [],
  }
}

export function emptyIssue() {
  return {
    id: newId('iss'),
    display_id: '',
    title: '',
    status: 'todo',
    priority: 'p1',
    collapsed: false,
    comment: '',
    tasks: [],
  }
}

export function defaultDueDate(daysAhead = 2) {
  const date = new Date()
  date.setDate(date.getDate() + daysAhead)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function emptyTask(title = '') {
  return {
    id: newId('tsk'),
    title,
    done: false,
    due_date: defaultDueDate(2),
    comment: '',
    delay_reason: '',
    delay_proofs: [],
    delay_recorded_at: '',
  }
}

export function sortTasksCompletedLast(tasks = []) {
  const open = []
  const done = []
  for (const task of tasks) {
    if (task?.done) done.push(task)
    else open.push(task)
  }
  return [...open, ...done]
}

export function emptyNote(text, author = '') {
  return {
    id: newId('note'),
    text,
    created_by: author,
    created_at: new Date().toISOString(),
  }
}

export function formatDueDate(iso) {
  if (!iso) return ''
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return iso
  return new Date(year, month - 1, day).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function categoryIssueCount(category) {
  return (category.issues || []).length
}
