import { useRef, useState } from 'react'
import api from '../../api'

const ACCEPT = 'image/*,audio/*,video/*,.pdf,.doc,.docx,.m4a,.mp3,.wav,.ogg'

export default function DelayProofModal({
  token,
  uploadFields,
  onCancel,
  onSubmit,
}) {
  const [reason, setReason] = useState('')
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  function addFiles(list) {
    const next = Array.from(list || [])
    if (!next.length) return
    setFiles((prev) => [...prev, ...next])
    setError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const text = reason.trim()
    if (!text) {
      setError('Enter a reason for the delay.')
      return
    }
    if (!files.length) {
      setError('Upload at least one proof (voice note, chat screenshot, or call history).')
      return
    }
    setBusy(true)
    setError('')
    try {
      const proofs = []
      for (const file of files) {
        const result = await api.uploadWeeklyTrackerFile(token, {
          ...uploadFields,
          target: 'pending',
        }, file)
        if (result?.file?.url) proofs.push(result.file)
      }
      if (!proofs.length) {
        setError('Could not upload the proof files. Try again.')
        return
      }
      await onSubmit({ reason: text, proofs })
    } catch (err) {
      setError(err.message || 'Could not save the delay proof.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay">
      <div className="modal-card delay-proof-modal">
        <form onSubmit={handleSubmit}>
          <div className="modal-header">
            <h3>Reason for delay</h3>
            <button type="button" className="modal-close-btn" onClick={onCancel} disabled={busy}>
              <i className="fa-solid fa-xmark" />
            </button>
          </div>
          <div className="modal-body">
            <p>
              This task is from an earlier week. Add a reason for the delay and upload proof
              (voice note, screenshot of chat, or calling history) before marking it completed.
            </p>
            <label className="delay-proof-label" htmlFor="delay-reason">
              Why was this late?
            </label>
            <textarea
              id="delay-reason"
              className="modal-input delay-proof-reason"
              rows={4}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="What caused the delay, and what did you do about it?"
              required
            />
            <label className="delay-proof-label">Proofs</label>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              multiple
              hidden
              onChange={(event) => {
                addFiles(event.target.files)
                event.target.value = ''
              }}
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
            >
              <i className="fa-solid fa-paperclip" /> Upload proof
            </button>
            <p className="delay-proof-hint">Voice, chat screenshots, call history, or similar.</p>
            {files.length ? (
              <ul className="delay-proof-files">
                {files.map((file, index) => (
                  <li key={`${file.name}-${index}`}>
                    <span>{file.name}</span>
                    <button
                      type="button"
                      className="tracker-icon-btn"
                      onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                      disabled={busy}
                      aria-label="Remove file"
                    >
                      <i className="fa-solid fa-xmark" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {error ? <p className="delay-proof-error">{error}</p> : null}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? 'Uploading…' : 'Mark completed'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
