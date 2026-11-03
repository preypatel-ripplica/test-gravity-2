import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import PlugMark from '../plug/components/PlugMark'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { login, token, user, loading } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && token && user) {
    const dest = user.active_client_id ? `/clients/${user.active_client_id}` : '/clients'
    return <Navigate to={dest} replace />
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const me = await login(username, password)
      const dest = me?.active_client_id ? `/clients/${me.active_client_id}` : '/clients'
      navigate(dest, { replace: true })
    } catch (err) {
      setError(err.message || 'Invalid email or password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-body">
        <div className="logo">
          <PlugMark size={32} />
        </div>
        <h1 className="login-wordmark">Plug</h1>
        <p className="login-tagline">Grow content with consistency and discipline</p>
        <span className="brand-bar" />
        <p className="login-meta">Internal workspace</p>
        <p className="subtitle">We help content creators create content with just 2 mins of effort every week.</p>

        <div className="card login-box">
          <form onSubmit={handleSubmit}>
            <div className="input-group">
              <label htmlFor="username">Email</label>
              <input
                id="username"
                type="email"
                placeholder="Email"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                placeholder="Password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <div className="error-msg">{error}</div>}
            <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
              {submitting ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="login-footer">PLUG &nbsp;·&nbsp; BY RIPPLICA</p>
      </div>
    </div>
  )
}
