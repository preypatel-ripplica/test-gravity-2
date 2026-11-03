import { useEffect, useRef, useState } from 'react'
import { isDefaultPreferenceSection } from './profileUtils'

export default function DoctorReferenceSections({
  sections,
  activeId,
  onSelect,
  onAddSection,
  onDeleteSection,
}) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const [confirmId, setConfirmId] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (adding) inputRef.current?.focus()
  }, [adding])

  function handleSubmit(event) {
    event.preventDefault()
    const title = draft.trim()
    if (!title) return
    onAddSection(title)
    setDraft('')
    setAdding(false)
  }

  return (
    <aside className="doctor-ref-sections">
      {sections.map((section) => {
        const active = section.id === activeId
        const confirming = confirmId === section.id
        return (
          <div key={section.id} className={`doctor-ref-section-item ${active ? 'active' : ''}`}>
            {confirming ? (
              <div className="doctor-ref-section-confirm">
                <span>Delete?</span>
                <button type="button" className="btn btn-danger btn-xs" onClick={() => {
                  onDeleteSection(section.id)
                  setConfirmId(null)
                }}>
                  Yes
                </button>
                <button type="button" className="btn btn-secondary btn-xs" onClick={() => setConfirmId(null)}>
                  No
                </button>
              </div>
            ) : (
              <>
                <button type="button" onClick={() => onSelect(section.id)}>
                  {section.title}
                </button>
                {!isDefaultPreferenceSection(section) && (
                  <button
                    type="button"
                    className="doctor-ref-section-delete"
                    title="Delete section"
                    onClick={() => setConfirmId(section.id)}
                  >
                    <i className="fa-solid fa-trash" />
                  </button>
                )}
              </>
            )}
          </div>
        )
      })}
      {adding ? (
        <form className="doctor-ref-add-section-form" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Section name"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setAdding(false)
                setDraft('')
              }
            }}
          />
          <div className="doctor-ref-inline-actions">
            <button type="submit" className="btn btn-primary btn-xs" disabled={!draft.trim()}>
              Add
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-xs"
              onClick={() => {
                setAdding(false)
                setDraft('')
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="doctor-ref-add-section" onClick={() => setAdding(true)}>
          + Add section
        </button>
      )}
    </aside>
  )
}
