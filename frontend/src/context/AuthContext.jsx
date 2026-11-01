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

function persistSession(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(() => (localStorage.getItem(TOKEN_KEY) ? readCachedUser() : null))
  const [loading, setLoading] = useState(!!localStorage.getItem(TOKEN_KEY))

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
      // Keep the session on network/backend blips — only clear on real auth expiry.
      if (isAuthExpiredError(err)) {
        logout()
        return null
      }
      console.warn('auth.me failed; keeping saved session', err)
      setLoading(false)
      return readCachedUser()
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
    localStorage.setItem(TOKEN_KEY, nextToken)
    setToken(nextToken)
    setLoading(true)
    try {
      const me = await api.me(nextToken)
      persistSession(nextToken, me)
      setUser(me)
      return me
    } catch (err) {
      // Login succeeded — keep the token even if profile hydrate is flaky.
      if (data.user && !isAuthExpiredError(err)) {
        persistSession(nextToken, data.user)
        setUser(data.user)
        return data.user
      }
      if (isAuthExpiredError(err)) {
        persistSession(null, null)
        setToken(null)
        setUser(null)
      }
      throw new Error('Failed to load user profile')
    } finally {
      setLoading(false)
    }
  }, [])

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
