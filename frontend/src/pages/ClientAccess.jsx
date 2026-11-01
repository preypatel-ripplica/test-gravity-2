import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

const DOMAIN_OPTIONS = [
  { value: 'videos', label: 'Videos', icon: 'fa-solid fa-video', hint: 'Content plan, scripts, YouTube' },
  { value: 'socialmedia', label: 'Social', icon: 'fa-solid fa-share-nodes', hint: 'Instagram & Facebook' },
  { value: 'website', label: 'Website', icon: 'fa-solid fa-globe', hint: 'CMS collections & media' },
  { value: 'whatsappbot', label: 'WhatsApp', icon: 'fa-brands fa-whatsapp', hint: 'WhatsApp bot' },
]

const EMPTY_INVITE = {
  email: '',
  domains: ['videos', 'socialmedia', 'website'],
}

function initialsFor(member) {
  const source = (member?.name || member?.email || '?').trim()
  const parts = source.split(/[\s@._-]+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
  return source.slice(0, 2).toUpperCase()
}

function DomainChip({ option, active, disabled, onToggle }) {
  return (
    <button
      type="button"
      className={`access-chip ${active ? 'is-on' : ''} ${disabled ? 'is-locked' : ''}`}
      disabled={disabled}
      aria-pressed={active}
      title={option.hint}
      onClick={() => onToggle(option.value)}
    >
      <i className={option.icon} aria-hidden />
      <span>{option.label}</span>
      {disabled && active ? <i className="fa-solid fa-lock access-chip-lock" aria-hidden /> : null}
    </button>
  )
}

export default function ClientAccess() {
  const { client, clientId } = useOutletContext()
  const { token, user } = useAuth()
  const { toast, confirm } = useUI()

  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [invite, setInvite] = useState(EMPTY_INVITE)
  const [inviting, setInviting] = useState(false)
  const [showInvite, setShowInvite] = useState(false)

  const isOwner = Boolean(client?.is_owner)

  const loadMembers = useCallback(async () => {
    if (!token || !clientId) return
    setLoading(true)
    try {
      const data = await api.listProjectMembers(token, clientId)
      setMembers(data?.members || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, clientId, toast])

  useEffect(() => {
    if (!isOwner) return
    loadMembers()
  }, [isOwner, loadMembers])

  const { owner, others } = useMemo(() => {
    const ownerRow = members.find((m) => m.is_owner) || null
    const rest = members.filter((m) => !m.is_owner)
    return { owner: ownerRow, others: rest }
  }, [members])

  if (client && !isOwner) {
    return <Navigate to={`/clients/${clientId}/profile/practice`} replace />
  }

  function toggleInviteDomain(domain) {
    setInvite((prev) => {
      const current = new Set(prev.domains)
      if (current.has(domain)) current.delete(domain)
      else current.add(domain)
      return { ...prev, domains: [...current] }
    })
  }

  async function persistDomains(member, nextDomains) {
    if (!nextDomains.length) {
      toast('Keep at least one domain, or remove their access', 'error')
      return false
    }
    setBusyId(member.user_id)
    const previous = members
    setMembers((list) =>
      list.map((m) => (m.user_id === member.user_id ? { ...m, domains: nextDomains } : m)),
    )
    try {
      await api.setProjectMember(token, clientId, {
        user_id: member.user_id,
        domains: nextDomains,
      })
      return true
    } catch (err) {
      setMembers(previous)
      toast(err.message, 'error')
      return false
    } finally {
      setBusyId(null)
    }
  }

  async function handleToggleMemberDomain(member, domain) {
    if (member.is_owner || busyId === member.user_id) return
    const current = new Set(member.domains || [])
    if (current.has(domain)) current.delete(domain)
    else current.add(domain)
    await persistDomains(member, [...current])
  }

  async function handleRemoveMember(member) {
    const label = member.name || member.email || 'this user'
    const ok = await confirm({
      title: 'Remove access?',
      message: `${label} will lose access to this client immediately.`,
      isDanger: true,
    })
    if (!ok) return
    setBusyId(member.user_id)
    try {
      await api.removeProjectMember(token, clientId, { user_id: member.user_id })
      setMembers((list) => list.filter((m) => m.user_id !== member.user_id))
      toast(`Removed ${label}`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function handleInvite(e) {
    e.preventDefault()
    const email = invite.email.trim().toLowerCase()
    if (!email) {
      toast('Email is required', 'error')
      return
    }
    if (!invite.domains.length) {
      toast('Pick at least one product area', 'error')
      return
    }
    if (email === (user?.email || user?.username || '').toLowerCase()) {
      toast('You already own this client', 'error')
      return
    }
    setInviting(true)
    try {
      await api.setProjectMember(token, clientId, {
        email,
        domains: invite.domains,
      })
      toast(`Access granted to ${email}`, 'success')
      setInvite(EMPTY_INVITE)
      setShowInvite(false)
      await loadMembers()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setInviting(false)
    }
  }

  function renderPerson(member, { locked = false } = {}) {
    const busy = busyId === member.user_id
    return (
      <article
        key={member.user_id}
        className={`access-person ${locked ? 'is-owner' : ''} ${busy ? 'is-busy' : ''}`}
      >
        <div className="access-person-identity">
          <div className={`access-avatar ${locked ? 'is-owner' : ''}`} aria-hidden>
            {initialsFor(member)}
          </div>
          <div className="access-person-copy">
            <div className="access-person-name-row">
              <strong>{member.name || member.email || member.user_id}</strong>
              {locked ? <span className="access-pill">Owner</span> : null}
              {member.type ? (
                <span className="access-pill access-pill-muted">{member.type}</span>
              ) : null}
            </div>
            <p className="access-person-email">{member.email}</p>
          </div>
        </div>

        <div className="access-person-domains" role="group" aria-label={`Access for ${member.email || member.name}`}>
          {DOMAIN_OPTIONS.map((opt) => (
            <DomainChip
              key={opt.value}
              option={opt}
              active={(member.domains || []).includes(opt.value)}
              disabled={locked || busy}
              onToggle={(domain) => handleToggleMemberDomain(member, domain)}
            />
          ))}
        </div>

        <div className="access-person-actions">
          {locked ? (
            <span className="access-locked-note">Full access</span>
          ) : (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={busy}
              onClick={() => handleRemoveMember(member)}
            >
              <i className="fa-solid fa-user-minus" /> Remove
            </button>
          )}
        </div>
      </article>
    )
  }

  return (
    <>
      <ProfileTabs clientId={clientId} isOwner={isOwner} />

      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Access' },
            ]}
          />
          <h1>Access</h1>
          <p>Control who can open each product area for this client. Changes save as you click.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowInvite((v) => !v)}
          >
            <i className={`fa-solid ${showInvite ? 'fa-xmark' : 'fa-user-plus'}`} />
            {showInvite ? 'Cancel' : 'Add person'}
          </button>
        </div>
      </header>

      {showInvite ? (
        <form className="access-invite card animate-fade-in" onSubmit={handleInvite}>
          <div className="access-invite-head">
            <h2>Add person</h2>
            <p>They need an existing Beacon login. Toggle the areas they should see.</p>
          </div>
          <div className="access-invite-grid">
            <label className="access-invite-email">
              Email
              <input
                type="email"
                value={invite.email}
                onChange={(e) => setInvite((prev) => ({ ...prev, email: e.target.value }))}
                placeholder="colleague@example.com"
                autoFocus
                required
              />
            </label>
            <div className="access-invite-domains">
              <span className="access-invite-label">Product access</span>
              <div className="access-chip-row">
                {DOMAIN_OPTIONS.map((opt) => (
                  <DomainChip
                    key={opt.value}
                    option={opt}
                    active={invite.domains.includes(opt.value)}
                    onToggle={toggleInviteDomain}
                  />
                ))}
              </div>
            </div>
          </div>
          <div className="access-invite-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setShowInvite(false)
                setInvite(EMPTY_INVITE)
              }}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={inviting}>
              {inviting ? 'Granting…' : 'Grant access'}
            </button>
          </div>
        </form>
      ) : null}

      <section className="access-panel card animate-fade-in">
        <div className="access-panel-head">
          <div>
            <h2>People</h2>
            <p className="text-muted">
              {loading
                ? 'Loading…'
                : `${members.length} ${members.length === 1 ? 'person' : 'people'} with access`}
            </p>
          </div>
        </div>

        {loading ? (
          <p className="text-muted access-empty">Loading access list…</p>
        ) : (
          <div className="access-people">
            {owner ? renderPerson(owner, { locked: true }) : null}
            {others.map((member) => renderPerson(member))}
            {others.length === 0 ? (
              <div className="access-empty-state">
                <i className="fa-solid fa-user-shield" />
                <h3>No teammates yet</h3>
                <p>Add someone by email and choose which product areas they can open.</p>
                {!showInvite ? (
                  <button type="button" className="btn btn-primary" onClick={() => setShowInvite(true)}>
                    <i className="fa-solid fa-user-plus" /> Add person
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </section>
    </>
  )
}
