import { useEffect, useRef, useState } from 'react'

export default function DoctorReferenceFields({
  section,
  onSaveField,
  onDeleteField,
  onAddField,
}) {
  const [draft, setDraft] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const labelRef = useRef(null)
  const fields = section?.fields || []

  useEffect(() => {
    setEditingId(null)
  }, [section?.id])

  useEffect(() => {
    if (editingId) labelRef.current?.focus()
  }, [editingId])

  function startEdit(field) {
    setEditingId(field.id)
    setLabel(field.label || '')
    setValue(field.value || '')
  }

  function cancelEdit() {
    setEditingId(null)
    setLabel('')
    setValue('')
  }

  function handleSave(event) {
    event.preventDefault()
    const nextLabel = label.trim()
    if (!nextLabel || !editingId) return
    onSaveField({ id: editingId, label: nextLabel, value: value.trim() })
    cancelEdit()
  }

  function handleAdd(event) {
    event.preventDefault()
    const nextLabel = draft.trim()
    if (!nextLabel) return
    onAddField(nextLabel)
    setDraft('')
  }

  return (
    <div className="doctor-ref-fields card">
      <div className="doctor-ref-fields-header">
        <h2>{section?.title || 'Section'}</h2>
        <span className="doctor-ref-field-count">
          {fields.length} field{fields.length === 1 ? '' : 's'}
        </span>
      </div>

      {fields.map((field) => {
        const empty = !(field.value || '').trim()
        if (editingId === field.id) {
          return (
            <form key={field.id} className="doctor-ref-field-row editing" onSubmit={handleSave}>
              <input
                ref={labelRef}
                className="doctor-ref-inline-input"
                type="text"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="Field name"
              />
              <textarea
                className="doctor-ref-inline-textarea"
                rows={3}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="Add notes for this field"
                onKeyDown={(event) => {
                  if (event.key === 'Escape') cancelEdit()
                }}
              />
              <div className="doctor-ref-inline-actions">
                <button type="button" className="btn btn-danger btn-xs" onClick={() => {
                  onDeleteField(field.id)
                  cancelEdit()
                }}>
                  Delete
                </button>
                <button type="button" className="btn btn-secondary btn-xs" onClick={cancelEdit}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary btn-xs" disabled={!label.trim()}>
                  Save
                </button>
              </div>
            </form>
          )
        }

        return (
          <div key={field.id} className="doctor-ref-field-row">
            <div className="doctor-ref-field-label">{field.label}</div>
            <div className={`doctor-ref-field-value ${empty ? 'empty' : ''}`}>
              {empty ? 'Not added yet' : field.value}
            </div>
            <button
              type="button"
              className="doctor-ref-field-edit"
              title={`Edit ${field.label}`}
              onClick={() => startEdit(field)}
            >
              <i className="fa-solid fa-pen" />
            </button>
          </div>
        )
      })}

      <form className="doctor-ref-add-field" onSubmit={handleAdd}>
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="+ Add field"
          aria-label="Add field"
        />
      </form>
    </div>
  )
}
