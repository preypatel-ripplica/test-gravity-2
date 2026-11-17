import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api, { isAuthExpiredError } from '../api'

const AuthContext = createContext(null)
const TOKEN_KEY = 'jwt_token'
const USER_KEY = 'jwt_user'

function readCachedUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
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

/** Offline/deploy fallback so RequireAuth does not bounce to /login. */
function userFromToken(token) {
  const claims = claimsFromToken(token)
  if (!claims?.user_id && !claims?.email) return null
  return {
    id: claims.user_id || '',
    email: claims.email || '',
    name: claims.name || claims.email || 'User',
    type: claims.type || 'internal',
    editor_id: claims.editor_id || null,
    is_active: true,
  }
}

function persistSession(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
}

function initialToken() {
  return localStorage.getItem(TOKEN_KEY)
}

function initialUser(token) {
  if (!token) return null
  return readCachedUser() || userFromToken(token)
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => initialToken())
  const [user, setUser] = useState(() => initialUser(initialToken()))
  // Only block the shell when we have a token but no usable profile yet.
  const [loading, setLoading] = useState(() => {
    const t = initialToken()
    return Boolean(t && !initialUser(t))
  })

  const logout = useCallback(() => {
    persistSession(null, null)
    setToken(null)
    setUser(null)
  }, [])

  const refreshUser = useCallback(async () => {
    if (!token) {
      setUser(null)
      setLoading(false)
      return null
    }
    try {
      const me = await api.me(token)
      setUser(me)
      persistSession(token, me)
      return me
    } catch (err) {
      // Ripplica parity: keep the token unless it is actually past exp.
      // Signature/"invalid" 401s must not wipe localStorage (that was the bug).
      const claims = claimsFromToken(token)
      if (!claims || isAuthExpiredError(err)) {
        logout()
        return null
      }
      console.warn('auth.me failed; keeping saved session', err)
      const cached = readCachedUser() || userFromToken(token)
      if (cached) {
        setUser(cached)
        persistSession(token, cached)
      }
      return cached
    } finally {
      setLoading(false)
    }
  }, [token, logout])

  useEffect(() => {
    void refreshUser()
  }, [refreshUser])

  const login = useCallback(async (username, password) => {
    const data = await api.login(username, password)
    const nextToken = data.access_token
    const fallbackUser = data.user || userFromToken(nextToken)
    // Persist immediately so a reload mid-hydrate still restores the session.
    persistSession(nextToken, fallbackUser || null)
    setToken(nextToken)
    if (fallbackUser) setUser(fallbackUser)
    setLoading(!fallbackUser)
    try {
      const me = await api.me(nextToken)
      persistSession(nextToken, me)
      setUser(me)
      return me
    } catch (err) {
      // Fresh login token is valid enough to stay signed in even if me() blips.
      if (fallbackUser) {
        persistSession(nextToken, fallbackUser)
        setUser(fallbackUser)
        return fallbackUser
      }
      if (isAuthExpiredError(err)) {
        logout()
      }
      throw new Error('Failed to load user profile')
    } finally {
      setLoading(false)
    }
  }, [logout])

  const patchUser = useCallback((patch) => {
    setUser((prev) => {
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
      user,
      loading,
      login,
      logout,
      refreshUser,
      patchUser,
      activeClientId: user?.active_client_id ?? null,
      activeChannelId: user?.active_channel_id ?? null,
    }),
    [token, user, loading, login, logout, refreshUser, patchUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
