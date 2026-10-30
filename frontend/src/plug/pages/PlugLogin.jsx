import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { usePlugAuth } from '../AuthContext'
import PlugMark from '../components/PlugMark'

export default function PlugLogin() {
  const { login, token, creator, loading } = usePlugAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && token && creator) {
    return <Navigate to="/plug/profile" replace />
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(username, password)
      navigate('/plug/profile', { replace: true })
    } catch (err) {
      setError(err.message || 'Invalid username or password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="plug-app plug-auth">
      <div className="plug-rail" aria-hidden="true" />
      <div className="plug-auth-body">
        <div className="plug-auth-brand">
          <PlugMark size={32} />
        </div>
        <h1 className="plug-wordmark">Plug</h1>
        <p className="plug-tagline">Grow content with consistency and discipline</p>
        <span className="plug-brand-bar" />
        <p className="plug-auth-meta">AI Consultation &nbsp;·&nbsp; Creator workspace</p>
        <p className="plug-auth-sub">
          We help content creators create content with just 2 mins of effort every week.
        </p>

        <div className="plug-auth-card">
          <form onSubmit={handleSubmit}>
            <div className="input-group">
              <label htmlFor="plug-username">Username</label>
              <input
                id="plug-username"
                type="text"
                placeholder="Username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="plug-password">Password</label>
              <input
                id="plug-password"
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
          <p className="plug-auth-switch">
            New here? <Link to="/plug/register">Create an account</Link>
          </p>
        </div>

        <p className="plug-auth-footer">PLUG &nbsp;·&nbsp; BY RIPPLICA</p>
      </div>
    </div>
  )
}
