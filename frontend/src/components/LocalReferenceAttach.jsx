import { useEffect, useRef, useState } from 'react'
import api from '../api'

const ACCEPT = 'image/png,image/jpeg,image/webp'
const MAX_LOCAL_REFS = 3

function LocalThumb({ file, onRemove }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const next = URL.createObjectURL(file)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [file])
  return (
    <div className="local-ref-tile">
      {url ? <img src={url} alt="" /> : null}
      <button type="button" className="local-ref-remove" aria-label="Remove reference" onClick={onRemove}>
        <i className="fa-solid fa-xmark" />
      </button>
    </div>
  )
}

export default function LocalReferenceAttach({ files, onChange, disabled = false }) {
  const inputRef = useRef(null)

  function addFiles(list) {
    const next = [...files]
    for (const file of list) {
      if (next.length >= MAX_LOCAL_REFS) break
      const type = (file.type || '').toLowerCase()
      if (!ACCEPT.split(',').includes(type)) continue
      next.push(file)
    }
    onChange(next)
  }

  return (
    <div className="local-ref-attach">
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        disabled={disabled || files.length >= MAX_LOCAL_REFS}
        onClick={() => inputRef.current?.click()}
      >
        <i className="fa-solid fa-paperclip" /> Attach local ({files.length}/{MAX_LOCAL_REFS})
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={`${ACCEPT},.png,.jpg,.jpeg,.webp`}
        multiple
        hidden
        onChange={(event) => {
          addFiles(event.target.files || [])
          event.target.value = ''
        }}
      />
      {files.length > 0 ? (
        <div className="local-ref-row">
          {files.map((file, index) => (
            <LocalThumb
              key={`${file.name}-${file.size}-${index}`}
              file={file}
              onRemove={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}
            />
          ))}
        </div>
      ) : (
        <p className="tracker-hint">Local images are mixed with the YouTube thumbnails you pick. With none picked, only these are used.</p>
      )}
    </div>
  )
}

export async function uploadLocalReferences(token, clientId, files) {
  const ids = []
  for (const file of (files || []).slice(0, MAX_LOCAL_REFS)) {
    const data = await api.uploadThumbnailReference(token, clientId, file)
    if (data?.id) ids.push(data.id)
  }
  return ids
}
