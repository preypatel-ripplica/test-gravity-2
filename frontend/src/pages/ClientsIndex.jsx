import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientsIndex() {
  const { token, user, patchUser } = useAuth()
  const { toast, prompt } = useUI()
  const navigate = useNavigate()
  const [tab, setTab] = useState('active')

  const clients = user?.clients || []
  const activeClients = useMemo(
    () => clients.filter((client) => client.is_active !== false),
    [clients],
  )
  const inactiveClients = useMemo(
    () => clients.filter((client) => client.is_active === false),
    [clients],
  )
  const visibleClients = tab === 'inactive' ? inactiveClients : activeClients

  async function handleCreateClient() {
    const name = await prompt({
      title: 'Create Client Account',
      placeholder: 'Enter client name...',
    })
    if (!name?.trim()) return

    try {
      const data = await api.createClient(token, name.trim())
      patchUser({
        clients: data.clients,
        channels: [],
        has_clients: data.clients.length > 0,
        active_client_id: data.active_client_id,
        active_channel_id: data.active_channel_id,
      })
      toast(`Client "${name.trim()}" created successfully!`, 'success')
      if (data.active_client_id) {
        navigate(`/clients/${data.active_client_id}`)
      }
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  return (
    <>
      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs items={[{ label: 'Clients' }]} />
          <h1>Clients</h1>
          <p>Select a client account or create a new one to manage YouTube channels.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn btn-primary" onClick={handleCreateClient}>
            <i className="fa-solid fa-plus" /> New Client
          </button>
        </div>
      </header>

      {clients.length === 0 ? (
        <div className="connect-prompt-container card animate-fade-in">
          <div className="prompt-illustration">
            <i className="fa-solid fa-folder-open illustration-icon" />
          </div>
          <h2>Welcome to Plug Internal!</h2>
          <p>
            To get started, create a client account. You can then link multiple YouTube channels to
            it to view aggregated or channel-level insights.
          </p>
          <button type="button" className="btn btn-primary btn-lg" onClick={handleCreateClient}>
            <i className="fa-solid fa-plus" /> Create Client Account
          </button>
        </div>
      ) : (
        <>
          <div className="clients-index-tabs" role="tablist" aria-label="Client status">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'active'}
              className={`clients-index-tab${tab === 'active' ? ' active' : ''}`}
              onClick={() => setTab('active')}
            >
              <i className="fa-solid fa-circle-check" />
              Active
              <span className="clients-index-tab-count">{activeClients.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'inactive'}
              className={`clients-index-tab${tab === 'inactive' ? ' active' : ''}`}
              onClick={() => setTab('inactive')}
            >
              <i className="fa-solid fa-circle-pause" />
              Inactive
              <span className="clients-index-tab-count">{inactiveClients.length}</span>
            </button>
          </div>

          {visibleClients.length === 0 ? (
            <div className="connect-prompt-container card animate-fade-in">
              <div className="prompt-illustration">
                <i
                  className={`fa-solid ${tab === 'inactive' ? 'fa-circle-pause' : 'fa-folder-open'} illustration-icon`}
                />
              </div>
              <h2>{tab === 'inactive' ? 'No inactive clients' : 'No active clients'}</h2>
              <p>
                {tab === 'inactive'
                  ? 'Clients marked inactive in their profile will appear here.'
                  : 'Create a client or mark an inactive client as active to see them here.'}
              </p>
              {tab === 'active' && (
                <button type="button" className="btn btn-primary btn-lg" onClick={handleCreateClient}>
                  <i className="fa-solid fa-plus" /> Create Client Account
                </button>
              )}
            </div>
          ) : (
            <div className="clients-grid">
              {visibleClients.map((client) => (
                <Link
                  key={client.id}
                  to={`/clients/${client.id}`}
                  className={`client-card card${client.is_active === false ? ' is-inactive' : ''}`}
                >
                  <div className="client-card-icon">
                    <i className="fa-solid fa-circle-user" />
                  </div>
                  <div className="client-card-body">
                    <h3>
                      {client.name}
                      {client.is_active === false && (
                        <span className="client-status-badge">Inactive</span>
                      )}
                    </h3>
                    <p>
                      {client.specialty
                        ? client.specialty
                        : client.channel_count > 0
                          ? `${client.channel_count} channel${client.channel_count === 1 ? '' : 's'}`
                          : 'No channels linked'}
                    </p>
                    {client.specialty && client.channel_count > 0 && (
                      <p className="client-card-meta">
                        {client.channel_count} channel{client.channel_count === 1 ? '' : 's'}
                      </p>
                    )}
                  </div>
                  <i className="fa-solid fa-chevron-right client-card-arrow" />
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </>
  )
}
