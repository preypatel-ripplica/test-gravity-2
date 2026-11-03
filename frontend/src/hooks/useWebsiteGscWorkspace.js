import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'
import {
  DEFAULT_TRACKER_CONFIG,
  OAUTH_MESSAGE_TYPE,
  PERFORMANCE_MONTHS,
  mergeSettings,
  pickGa4Property,
  pickGscProperty,
} from '../components/websiteReportsShared'

export default function useWebsiteGscWorkspace(clientId, { loadPerformanceOnConnect = true } = {}) {
  const { token } = useAuth()
  const { toast } = useUI()

  const [settings, setSettings] = useState(DEFAULT_TRACKER_CONFIG)
  const [googleConnection, setGoogleConnection] = useState({ connected: false })
  const [properties, setProperties] = useState({ gsc_sites: [], ga4_properties: [] })
  const [performance, setPerformance] = useState(null)
  const [loading, setLoading] = useState(true)
  const [perfLoading, setPerfLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const loadedClientRef = useRef('')

  const refreshProperties = useCallback(
    async (baseSettings = settings) => {
      const data = await api.listWebsiteReportsProperties(token, clientId)
      setProperties(data)
      if (data.errors?.length) {
        toast(data.errors.map((item) => item.message).join(' '), 'error')
      }
      const nextGsc =
        baseSettings.gsc_property_url || pickGscProperty(baseSettings.site_url, data.gsc_sites)
      const nextGa4 =
        baseSettings.ga4_property_id || pickGa4Property(data.ga4_properties)
      let nextSite = baseSettings.site_url || ''
      if (!nextSite && nextGsc) {
        if (nextGsc.startsWith('sc-domain:')) {
          nextSite = `https://${nextGsc.slice('sc-domain:'.length)}`
        } else if (nextGsc.startsWith('http://') || nextGsc.startsWith('https://')) {
          nextSite = nextGsc.replace(/\/$/, '')
        }
      }
      if (nextGsc || nextGa4 || nextSite !== baseSettings.site_url) {
        const nextSettings = mergeSettings({
          ...baseSettings,
          site_url: nextSite || baseSettings.site_url,
          gsc_property_url: nextGsc,
          ga4_property_id: nextGa4,
        })
        setSettings(nextSettings)
        if (
          nextGsc !== baseSettings.gsc_property_url ||
          nextGa4 !== baseSettings.ga4_property_id ||
          nextSite !== (baseSettings.site_url || '')
        ) {
          await api.updateWebsiteReportsSettings(token, clientId, nextSettings)
        }
      }
      return data
    },
    [token, clientId, settings, toast],
  )

  const loadPerformance = useCallback(async () => {
    if (!token || !clientId) return
    setPerfLoading(true)
    try {
      const data = await api.getWebsiteGscPerformance(token, clientId, {
        months: PERFORMANCE_MONTHS,
        rowLimit: 25,
      })
      setPerformance(data)
    } catch (err) {
      setPerformance(null)
      toast(err.message, 'error')
    } finally {
      setPerfLoading(false)
    }
  }, [token, clientId, toast])

  const loadWorkspace = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const loaded = await api.getWebsiteReportsSettings(token, clientId)
      const nextSettings = mergeSettings(loaded.tracker_config || {})
      setSettings(nextSettings)
      setGoogleConnection(loaded.google_connection || { connected: false })
      if (loaded.google_connection?.connected) {
        await refreshProperties(nextSettings)
        if (loadPerformanceOnConnect) {
          await loadPerformance()
        }
      } else {
        setProperties({ gsc_sites: [], ga4_properties: [] })
        setPerformance(null)
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast, refreshProperties, loadPerformance, loadPerformanceOnConnect])

  useEffect(() => {
    if (!clientId || loadedClientRef.current === clientId) return
    loadedClientRef.current = clientId
    loadWorkspace()
  }, [clientId, loadWorkspace])

  useEffect(() => {
    function handleGoogleMessage(event) {
      if (event.data?.type !== OAUTH_MESSAGE_TYPE) return
      if (event.data.status === 'connected') {
        toast('Google connected', 'success')
        loadWorkspace()
      } else {
        toast(event.data.message || 'Google connection failed', 'error')
      }
    }
    window.addEventListener('message', handleGoogleMessage)
    return () => window.removeEventListener('message', handleGoogleMessage)
  }, [loadWorkspace, toast])

  async function connectGoogle() {
    setConnecting(true)
    try {
      const data = await api.startWebsiteGoogleConnect(token, clientId)
      window.open(data.auth_url, 'website_google_oauth', 'width=560,height=720')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setConnecting(false)
    }
  }

  async function disconnectGoogle() {
    try {
      await api.disconnectWebsiteGoogle(token, clientId)
      setGoogleConnection({ connected: false })
      setProperties({ gsc_sites: [], ga4_properties: [] })
      setPerformance(null)
      toast('Google disconnected', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function saveSettings(event) {
    event.preventDefault()
    setSaving(true)
    try {
      const saved = await api.updateWebsiteReportsSettings(token, clientId, settings)
      const next = mergeSettings(saved.tracker_config || {})
      setSettings(next)
      toast('Tracker settings saved', 'success')
      if (googleConnection.connected) {
        await refreshProperties(next)
        if (loadPerformanceOnConnect) {
          await loadPerformance()
        }
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  function updateSetting(field, value) {
    setSettings((current) => ({ ...current, [field]: value }))
  }

  function updateConversionEvent(field, value) {
    setSettings((current) => ({
      ...current,
      conversion_events: {
        ...current.conversion_events,
        [field]: value,
      },
    }))
  }

  return {
    settings,
    googleConnection,
    properties,
    performance,
    loading,
    perfLoading,
    saving,
    connecting,
    connected: Boolean(googleConnection.connected),
    refreshProperties,
    loadPerformance,
    connectGoogle,
    disconnectGoogle,
    saveSettings,
    updateSetting,
    updateConversionEvent,
    toast,
  }
}
