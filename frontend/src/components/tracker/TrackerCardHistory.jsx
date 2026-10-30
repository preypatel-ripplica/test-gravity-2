import { useState } from 'react'
import { formatHistoryWhen } from './trackerUtils'

export default function TrackerCardHistory({ card }) {
  const [open, setOpen] = useState(false)
  const events = [...(card?.history || [])].filter((row) => row?.label).reverse()
  const countLabel = events.length ? String(events.length) : 'None'

  return (
    <section className={`tracker-section tracker-card-history${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="tracker-history-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <h3 className="tracker-kicker">History</h3>
        <em>{countLabel}</em>
        <span className="tracker-icon-btn" aria-hidden="true">
          <i className={`fa-solid fa-chevron-${open ? 'up' : 'down'}`} />
        </span>
      </button>
      {open ? (
        !events.length ? (
          <p className="tracker-hint">Changes on this card will show up here — status, links, files, and notes.</p>
        ) : (
          <ol className="tracker-history-list">
            {events.map((event) => (
              <li key={event.id || `${event.at}-${event.label}`}>
                <time dateTime={event.at}>{formatHistoryWhen(event.at)}</time>
                <strong>{event.label}</strong>
                {event.detail ? <p>{event.detail}</p> : null}
                {event.by ? <small>{event.by}</small> : null}
              </li>
            ))}
          </ol>
        )
      ) : null}
    </section>
  )
}
