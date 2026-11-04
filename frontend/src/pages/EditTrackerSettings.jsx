import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import HoursStepper from '../components/HoursStepper'
import { EditFieldMenu, editorTone } from './EditTracker'

export default function EditTrackerSettings() {
  const { token } = useAuth()
  const { toast } = useUI()
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [editors, setEditors] = useState([])
  const [clients, setClients] = useState([])

  const load = useCallback(async () => {
    if (!token) return
    setLoading(true)
    try {
      const data = await api.getEditTrackerSettings(token)
      setEditors(data.editors || [])
      setClients(data.clients || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, toast])

  useEffect(() => {
    load()
  }, [load])

  const editorOptions = useMemo(() => ([
    { value: '', label: 'Unassigned', detail: 'No default editor', tone: 'plain', swatch: true },
    ...editors.map((editor) => ({
      value: editor.id,
      label: editor.name,
      detail: editor.max_hours_per_day ? `${editor.max_hours_per_day}h / day` : '',
      tone: editorTone(editor.id),
      swatch: true,
    })),
  ]), [editors])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return clients
    return clients.filter((client) => String(client.name || '').toLowerCase().includes(needle))
  }, [clients, query])

  function applyClient(next) {
    setClients((current) => current.map((row) => (row.client_id === next.client_id ? { ...row, ...next } : row)))
  }

  async function patchClient(client, patch) {
    if (!token) return
    const previous = { ...client }
    applyClient({ ...client, ...patch })
    try {
      const data = await api.patchEditTrackerSettings(token, {
        client_id: client.client_id,
        ...patch,
      })
      if (data?.client) applyClient(data.client)
    } catch (err) {
      applyClient(previous)
      toast(err.message, 'error')
    }
  }

  return (
    <div className="edit-tracker-page">
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Edit tracker', to: '/edit-tracker' },
              { label: 'Client settings' },
            ]}
          />
          <h1>Client settings</h1>
          <p>Default editor and long / short hours for each client. Videos without a manual editor override follow these defaults on the board.</p>
        </div>
        <Link to="/edit-tracker" className="btn btn-secondary">
          Back to board
        </Link>
      </header>

      <div className="edit-settings-toolbar">
        <label className="edit-settings-search">
          <i className="fa-solid fa-magnifying-glass" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search clients"
          />
        </label>
        <span>{visible.length} client{visible.length === 1 ? '' : 's'}</span>
      </div>

      {loading ? (
        <p className="text-muted">Loading settings…</p>
      ) : (
        <div className="edit-settings-table-wrap">
          <table className="edit-settings-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Default editor</th>
                <th>Long</th>
                <th>Short</th>
              </tr>
            </thead>
            <tbody>
              {visible.length ? visible.map((client) => {
                const tone = editorTone(client.video_editor_id)
                return (
                  <tr key={client.client_id}>
                    <td>
                      <strong>{client.name}</strong>
                    </td>
                    <td>
                      <EditFieldMenu
                        label="Editor"
                        value={client.video_editor_id || ''}
                        tone={tone}
                        options={editorOptions}
                        onChange={(videoEditorId) => patchClient(client, { video_editor_id: videoEditorId })}
                      />
                    </td>
                    <td>
                      <HoursStepper
                        value={client.long_video_hours}
                        tone={tone}
                        label="Long hours"
                        onChange={(hours) => patchClient(client, { long_video_hours: hours })}
                      />
                    </td>
                    <td>
                      <HoursStepper
                        value={client.short_video_hours}
                        tone={tone}
                        label="Short hours"
                        onChange={(hours) => patchClient(client, { short_video_hours: hours })}
                      />
                    </td>
                  </tr>
                )
              }) : (
                <tr>
                  <td colSpan={4} className="text-muted">No clients match that search.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
