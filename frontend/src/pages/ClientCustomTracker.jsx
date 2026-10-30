import { useCallback, useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import CustomBoard from '../components/custom-tracker/CustomBoard'
import { sortTasksCompletedLast } from '../components/custom-tracker/customTrackerUtils'
import TrackerViewSwitch from '../components/tracker/TrackerViewSwitch'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientCustomTracker() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const saveTimer = useRef(null)
  const skipNextSave = useRef(true)
  const loadedClient = useRef('')

  const loadBoard = useCallback(async (nextClientId) => {
    if (!token || !nextClientId) return
    setLoading(true)
    try {
      const result = await api.getCustomTracker(token, nextClientId)
      loadedClient.current = nextClientId
      skipNextSave.current = true
      setTasks(sortTasksCompletedLast(result.tracker?.tasks || []))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, toast])

  useEffect(() => {
    loadBoard(clientId)
  }, [clientId, loadBoard])

  useEffect(() => {
    if (skipNextSave.current) {
      skipNextSave.current = false
      return
    }
    if (!token || !clientId || loadedClient.current !== clientId) return
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      if (loadedClient.current !== clientId) return
      try {
        await api.saveCustomTracker(token, clientId, tasks)
      } catch (err) {
        toast(err.message, 'error')
      }
    }, 400)
  }, [tasks, token, clientId, toast])

  useEffect(() => () => clearTimeout(saveTimer.current), [])

  return (
    <div className="weekly-tracker-page">
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Custom trackers' },
            ]}
          />
          <TrackerViewSwitch clientId={clientId} />
          <h1>Custom trackers</h1>
          <p>A simple to-do list for this client — tasks and due dates.</p>
        </div>
      </header>

      {loading ? (
        <p className="text-muted" style={{ padding: '16px 0' }}>Loading board…</p>
      ) : (
        <CustomBoard tasks={tasks} onChange={setTasks} />
      )}
    </div>
  )
}
