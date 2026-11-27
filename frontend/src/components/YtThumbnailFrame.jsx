import { useEffect, useRef, useState } from 'react'

export const EXPLICIT_THUMB_MESSAGE = "Thumbnail can't be generated because of explicit content."

const ACCEPT = 'image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp'

export function thumbnailAspectOk(width, height, portrait) {
  if (!width || !height) return false
  const target = portrait ? 9 / 16 : 16 / 9
  return Math.abs(width / height - target) / target <= 0.02
}

export function readImageSize(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const size = { width: img.naturalWidth, height: img.naturalHeight }
      URL.revokeObjectURL(url)
      resolve(size)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Could not read that image.'))
    }
    img.src = url
  })
}

export default function YtThumbnailFrame({
  url,
  error,
  portrait = false,
  busy = false,
  alt = 'Thumbnail',
  onSave,
  onReject,
}) {
  const inputRef = useRef(null)
  const [pendingFile, setPendingFile] = useState(null)
  const [pendingUrl, setPendingUrl] = useState('')

  useEffect(() => () => {
    if (pendingUrl) URL.revokeObjectURL(pendingUrl)
  }, [pendingUrl])

  function clearPending() {
    if (pendingUrl) URL.revokeObjectURL(pendingUrl)
    setPendingFile(null)
    setPendingUrl('')
  }

  async function onPick(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const size = await readImageSize(file)
      if (!thumbnailAspectOk(size.width, size.height, portrait)) {
        onReject?.(portrait ? 'Use a 9:16 image for a short.' : 'Use a 16:9 image for a long video.')
        return
      }
    } catch (err) {
      onReject?.(err.message || 'Could not read that image.')
      return
    }
    if (pendingUrl) URL.revokeObjectURL(pendingUrl)
    setPendingFile(file)
    setPendingUrl(URL.createObjectURL(file))
  }

  async function save() {
    if (!pendingFile || !onSave) return
    try {
      await onSave(pendingFile)
      clearPending()
    } catch {
      // The parent reports the error. Keep the picked file so Save can be tried again.
    }
  }

  const shown = pendingUrl || url
  const explicit = !shown && error === 'explicit'

  return (
    <div className={`tracker-yt-preview-thumb yt-thumb-frame${portrait ? ' is-portrait' : ''}`}>
      {shown ? (
        <img src={shown} alt={alt} />
      ) : (
        <div className="tracker-yt-thumb-empty">
          <i className="fa-regular fa-image" />
          <span>{explicit ? EXPLICIT_THUMB_MESSAGE : 'No thumbnail'}</span>
        </div>
      )}
      <button
        type="button"
        className="yt-thumb-pencil"
        aria-label="Replace thumbnail"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
      >
        <i className="fa-solid fa-pencil" />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={onPick}
      />
      {pendingFile ? (
        <div className="yt-thumb-save">
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={clearPending}>
            Cancel
          </button>
        </div>
      ) : null}
    </div>
  )
}
