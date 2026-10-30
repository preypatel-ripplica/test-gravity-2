const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

function url(path) {
  return `${API_URL}${path}`
}

async function parseError(response) {
  const err = await response.json().catch(() => ({}))
  return err.detail || `HTTP ${response.status}`
}

export async function plugFetch(path, { token, body, form } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  let payload
  if (form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    payload = form
  } else {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body ?? {})
  }

  const response = await fetch(url(path), { method: 'POST', headers, body: payload })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  if (response.status === 204) return null
  return response.json()
}

const plugApi = {
  register: (username, password) => plugFetch('/plug/auth.register', { body: { username, password } }),
  login: (username, password) => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return plugFetch('/plug/auth.login', { form })
  },
  me: (token) => plugFetch('/plug/auth.me', { token }),
  updateProfile: (token, fields) => plugFetch('/plug/profile.update', { token, body: fields }),
  saveInstagramConfig: (token, config) => plugFetch('/plug/instagram.config.save', { token, body: config }),
  getInstagramConfig: (token) => plugFetch('/plug/instagram.config.get', { token }),
  getInstagramConnectUrl: (token) => plugFetch('/plug/instagram.connect-url', { token }),
  disconnectInstagram: (token) => plugFetch('/plug/instagram.disconnect', { token }),
  analytics: (token, { since, until } = {}) => plugFetch('/plug/analytics.get', { token, body: { since, until } }),
  searchTopics: (token, { language, prompt } = {}) =>
    plugFetch('/plug/topics.search', { token, body: { language: language || 'english', prompt: prompt || '' } }),
  listTopics: (token) => plugFetch('/plug/topics.list', { token }),
  redoScript: (token, { topicId, prompt, language }) =>
    plugFetch('/plug/topics.script.redo', {
      token,
      body: { topic_id: topicId, prompt, language: language || undefined },
    }),
  rateScript: (token, { topicId, rating }) =>
    plugFetch('/plug/topics.script.rate', {
      token,
      body: { topic_id: topicId, rating: rating || null },
    }),
  listTodos: (token) => plugFetch('/plug/todos.list', { token }),
  createTodo: (token, text) => plugFetch('/plug/todos.create', { token, body: { text } }),
  updateTodo: (token, { id, text, done }) =>
    plugFetch('/plug/todos.update', { token, body: { id, text, done } }),
  deleteTodo: (token, id) => plugFetch('/plug/todos.delete', { token, body: { id } }),
  reorderTodos: (token, { openIds, doneIds }) =>
    plugFetch('/plug/todos.reorder', {
      token,
      body: { open_ids: openIds || [], done_ids: doneIds || [] },
    }),
}

export default plugApi
