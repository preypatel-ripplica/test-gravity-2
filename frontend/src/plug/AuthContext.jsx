import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import plugApi, { isPlugAuthExpiredError } from './api'

const TOKEN_KEY = 'plug_jwt_token'
const CREATOR_KEY = 'plug_jwt_creator'

const PlugAuthContext = createContext(null)

function readCachedCreator() {
  try {
    const raw = localStorage.getItem(CREATOR_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function claimsFromToken(token) {
  try {
    const part = String(token || '').split('.')[1]
    if (!part) return null
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json)
    if (!payload || typeof payload !== 'object') return null
    const exp = Number(payload.exp || 0)
    if (exp && exp * 1000 <= Date.now()) return null
    return payload
  } catch {
    return null
  }
}

function creatorFromToken(token) {
  const claims = claimsFromToken(token)
  const sub = String(claims?.sub || '')
  if (!sub.startsWith('plug:')) return null
  const username = sub.slice('plug:'.length)
  if (!username) return null
  return { username, name: username }
}

function persistSession(token, creator) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
  if (creator) localStorage.setItem(CREATOR_KEY, JSON.stringify(creator))
  else localStorage.removeItem(CREATOR_KEY)
}

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

function initialToken() {
  return localStorage.getItem(TOKEN_KEY)
}

function initialCreator(token) {
  if (!token) return null
  return readCachedCreator() || creatorFromToken(token)
}

export function PlugAuthProvider({ children }) {
  const [token, setToken] = useState(() => initialToken())
  const [creator, setCreator] = useState(() => initialCreator(initialToken()))
  const [loading, setLoading] = useState(() => {
    const t = initialToken()
    return Boolean(t && !initialCreator(t))
  })
  const skipNextRefresh = useRef(false)

  const logout = useCallback(() => {
    persistSession(null, null)
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
      setCreator((prev) => {
        const next = keepNewerCreator(prev, me)
        persistSession(token, next)
        return next
      })
      return me
    } catch (err) {
      // Ripplica parity: keep token unless JWT is past exp client-side / API says expired.
      const claims = claimsFromToken(token)
      if (!claims || isPlugAuthExpiredError(err)) {
        logout()
        return null
      }
      console.warn('plug auth.me failed; keeping saved session', err)
      const cached = readCachedCreator() || creatorFromToken(token)
      if (cached) {
        setCreator(cached)
        persistSession(token, cached)
      }
      return cached
    } finally {
      setLoading(false)
    }
  }, [token, logout])

  useEffect(() => {
    if (skipNextRefresh.current) {
      skipNextRefresh.current = false
      return
    }
    void refresh()
  }, [refresh])

  const applyToken = useCallback(async (accessToken) => {
    const fallback = creatorFromToken(accessToken)
    persistSession(accessToken, fallback)
    skipNextRefresh.current = true
    setToken(accessToken)
    if (fallback) setCreator(fallback)
    setLoading(!fallback)
    try {
      const me = await plugApi.me(accessToken)
      persistSession(accessToken, me)
      setCreator(me)
      return me
    } catch (err) {
      skipNextRefresh.current = false
      if (fallback && !isPlugAuthExpiredError(err)) {
        persistSession(accessToken, fallback)
        setCreator(fallback)
        return fallback
      }
      if (isPlugAuthExpiredError(err)) {
        logout()
      }
      throw new Error('Failed to load profile')
    } finally {
      setLoading(false)
    }
  }, [logout])

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
    setCreator((prev) => {
      if (!prev) return prev
      const next = { ...prev, ...patch }
      const savedToken = localStorage.getItem(TOKEN_KEY)
      if (savedToken) persistSession(savedToken, next)
      return next
    })
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
