import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import plugApi from './api'

const TOKEN_KEY = 'plug_jwt_token'

const PlugAuthContext = createContext(null)

function profileStamp(creator) {
  const parsed = Date.parse(creator?.updated_at || '')
  return Number.isFinite(parsed) ? parsed : 0
}

function keepNewerCreator(prev, next) {
  if (!next) return prev
  if (!prev) return next
  if (profileStamp(prev) > profileStamp(next)) return prev
  const prevFilled = Boolean((prev.niche || '').trim() || (prev.niche_details || '').trim())
  const nextFilled = Boolean((next.niche || '').trim() || (next.niche_details || '').trim())
  if (prevFilled && !nextFilled && profileStamp(prev) >= profileStamp(next)) return prev
  return next
}

export function PlugAuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [creator, setCreator] = useState(null)
  const [loading, setLoading] = useState(!!localStorage.getItem(TOKEN_KEY))
  const skipNextRefresh = useRef(false)

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setCreator(null)
  }, [])

  const refresh = useCallback(async () => {
    if (!token) {
      setCreator(null)
      setLoading(false)
      return null
    }
    try {
      const me = await plugApi.me(token)
      setCreator((prev) => keepNewerCreator(prev, me))
      return me
    } catch {
      logout()
      return null
    } finally {
      setLoading(false)
    }
  }, [token, logout])

  useEffect(() => {
    if (skipNextRefresh.current) {
      skipNextRefresh.current = false
      return
    }
    refresh()
  }, [refresh])

  const applyToken = useCallback(async (accessToken) => {
    localStorage.setItem(TOKEN_KEY, accessToken)
    skipNextRefresh.current = true
    setToken(accessToken)
    setLoading(true)
    try {
      const me = await plugApi.me(accessToken)
      setCreator(me)
      return me
    } catch {
      skipNextRefresh.current = false
      localStorage.removeItem(TOKEN_KEY)
      setToken(null)
      setCreator(null)
      throw new Error('Failed to load profile')
    } finally {
      setLoading(false)
    }
  }, [])

  const login = useCallback(
    async (username, password) => {
      const data = await plugApi.login(username, password)
      return applyToken(data.access_token)
    },
    [applyToken],
  )

  const register = useCallback(
    async (username, password) => {
      const data = await plugApi.register(username, password)
      return applyToken(data.access_token)
    },
    [applyToken],
  )

  const patchCreator = useCallback((patch) => {
    setCreator((prev) => (prev ? { ...prev, ...patch } : prev))
  }, [])

  const value = useMemo(
    () => ({
      token,
      creator,
      loading,
      login,
      register,
      logout,
      refresh,
      patchCreator,
    }),
    [token, creator, loading, login, register, logout, refresh, patchCreator],
  )

  return <PlugAuthContext.Provider value={value}>{children}</PlugAuthContext.Provider>
}

export function usePlugAuth() {
  const ctx = useContext(PlugAuthContext)
  if (!ctx) throw new Error('usePlugAuth must be used within PlugAuthProvider')
  return ctx
}
