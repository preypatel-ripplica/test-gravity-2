import { useState } from 'react'
import {
  LANG_LABELS,
  PLATFORM_LABELS,
  destPlatforms,
  destRows,
  destsFor,
  filledDestCount,
  newId,
} from './trackerUtils'

const PLATFORM_ICONS = {
  youtube: 'fa-brands fa-youtube',
  facebook: 'fa-brands fa-facebook',
  instagram: 'fa-brands fa-instagram',
  website: 'fa-solid fa-globe',
}

function linkLabel(url) {
  const raw = (url || '').trim()
  if (!raw) return ''
  try {
    const u = new URL(raw)
    if (u.hostname.includes('youtube.com') || u.hostname.includes('youtu.be')) {
      const id = u.searchParams.get('v') || u.pathname.split('/').filter(Boolean).pop()
      return id ? `youtu.be/${id}` : u.hostname
    }
    if (u.hostname.includes('instagram.com')) {
      const parts = u.pathname.split('/').filter(Boolean)
      return parts.length ? `instagram.com/…/${parts[parts.length - 1]}` : 'Instagram'
    }
    if (u.hostname.includes('facebook.com')) {
      return `facebook.com${u.pathname.length > 24 ? `${u.pathname.slice(0, 22)}…` : u.pathname}`
    }
    const path = u.pathname === '/' ? '' : u.pathname
    const host = u.hostname.replace(/^www\./, '')
    const text = `${host}${path}`
    return text.length > 36 ? `${text.slice(0, 34)}…` : text
  } catch {
    return raw.length > 40 ? `${raw.slice(0, 38)}…` : raw
  }
}

function DestinationCell({ dest, editingStructure, onSave, onRemove }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(dest.url || '')
  const url = (dest.url || '').trim()

  if (editing) {
    return (
      <div className="tracker-dest-edit">
        <input
          className="form-control"
          autoFocus
          value={draft}
          placeholder="Paste URL"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="button" className="btn btn-primary btn-sm" onClick={() => { onSave(draft.trim()); setEditing(false) }}>
          Save
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => { setDraft(url); setEditing(false) }}
        >
          Cancel
        </button>
        {editingStructure && (
          <button type="button" className="tracker-slot-btn is-remove" onClick={onRemove} title="Remove">−</button>
        )}
      </div>
    )
  }

  if (url) {
    return (
      <div className="tracker-dest-link-row">
        <a
          className="tracker-dest-link"
          href={url}
          target="_blank"
          rel="noreferrer"
          title={url}
        >
          <i className="fa-solid fa-arrow-up-right-from-square" aria-hidden />
          <span>{linkLabel(url)}</span>
        </a>
        <div className="tracker-dest-link-actions">
          <button type="button" className="tracker-dest-icon-btn" onClick={() => setEditing(true)} title="Edit URL">
            <i className="fa-solid fa-pen" aria-hidden />
          </button>
          {editingStructure && (
            <button type="button" className="tracker-dest-icon-btn is-danger" onClick={onRemove} title="Remove">
              <i className="fa-solid fa-trash" aria-hidden />
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="tracker-dest-link-row is-empty">
      <button type="button" className="tracker-add-link" onClick={() => setEditing(true)}>
        <i className="fa-solid fa-plus" aria-hidden /> Add link
      </button>
      {editingStructure && (
        <button type="button" className="tracker-dest-icon-btn is-danger" onClick={onRemove} title="Remove slot">
          <i className="fa-solid fa-trash" aria-hidden />
        </button>
      )}
    </div>
  )
}

function EmptySlot({ onCreate }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  if (editing) {
    return (
      <div className="tracker-dest-edit">
        <input
          className="form-control"
          autoFocus
          value={draft}
          placeholder="Paste URL"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => {
            onCreate(draft.trim())
            setDraft('')
            setEditing(false)
          }}
        >
          Save
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => { setDraft(''); setEditing(false) }}
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <div className="tracker-dest-link-row is-empty">
      <button type="button" className="tracker-add-link" onClick={() => setEditing(true)}>
        <i className="fa-solid fa-plus" aria-hidden /> Add link
      </button>
    </div>
  )
}

export default function TrackerDestinations({ card, languages, onChange }) {
  const { filled, total } = filledDestCount(card, languages)
  const [editingStructure, setEditingStructure] = useState(false)
  const platforms = destPlatforms(card)
  const rows = destRows(card, languages)

  function setDestinations(destinations) {
    onChange({ ...card, destinations })
  }

  function saveUrl(destId, url) {
    setDestinations((card.destinations || []).map((d) => (d.id === destId ? { ...d, url } : d)))
  }

  function removeDest(destId) {
    setDestinations((card.destinations || []).filter((d) => d.id !== destId))
  }

  function addDest(language, platform, url = '') {
    setDestinations([
      ...(card.destinations || []),
      { id: newId('dest'), language: language || undefined, platform, url },
    ])
  }

  return (
    <section className="tracker-section">
      <div className="tracker-section-head">
        <h3 className="tracker-kicker">Where it went out</h3>
        <div className="tracker-section-head-actions">
          <span className={`tracker-live-count${filled ? '' : ' is-zero'}`}>{filled} of {total} live</span>
          <button type="button" className="tracker-text-btn" onClick={() => setEditingStructure((v) => !v)}>
            {editingStructure ? 'Done' : 'Edit structure'}
          </button>
        </div>
      </div>

      <div className="tracker-dest-table-wrap">
        <table className="tracker-dest-table">
          <thead>
            <tr>
              <th className="tracker-dest-th-lang" scope="col">Language</th>
              {platforms.map((platform) => (
                <th key={platform} scope="col" className="tracker-dest-th-platform">
                  <span className="tracker-dest-platform-head">
                    {PLATFORM_ICONS[platform] && (
                      <i className={PLATFORM_ICONS[platform]} aria-hidden />
                    )}
                    {PLATFORM_LABELS[platform] || platform}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((language) => (
              <tr key={language || 'row'}>
                <th scope="row" className="tracker-dest-lang">
                  {language ? (LANG_LABELS[language] || language) : '—'}
                </th>
                {platforms.map((platform) => {
                  const slots = destsFor(card, language, platform)
                  const filledCount = slots.filter((d) => (d.url || '').trim()).length
                  return (
                    <td key={platform} className="tracker-dest-td">
                      <div className="tracker-dest-cell">
                        {slots.length === 0 ? (
                          <EmptySlot onCreate={(url) => addDest(language, platform, url)} />
                        ) : (
                          slots.map((dest) => (
                            <DestinationCell
                              key={dest.id}
                              dest={dest}
                              editingStructure={editingStructure}
                              onSave={(url) => saveUrl(dest.id, url)}
                              onRemove={() => removeDest(dest.id)}
                            />
                          ))
                        )}
                        {editingStructure && (
                          <button
                            type="button"
                            className="tracker-dest-add-slot"
                            onClick={() => addDest(language, platform)}
                            title="Add another link"
                          >
                            <i className="fa-solid fa-plus" aria-hidden /> Add slot
                          </button>
                        )}
                      </div>
                      {filledCount > 1 && (
                        <span className="tracker-dest-cell-meta">{filledCount} links</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
