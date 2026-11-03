import { useEffect, useRef } from 'react'

function snapHours(raw, fallback = 1) {
  const parsed = Number(raw)
  const value = Number.isFinite(parsed) ? parsed : Number(fallback) || 1
  return Math.min(12, Math.max(0.5, Math.round(value * 2) / 2))
}

function formatHours(value) {
  const hours = snapHours(value)
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1)
}

export default function HoursStepper({
  value,
  onChange,
  tone = 'plain',
  label = 'Hours',
  min = 0.5,
  max = 12,
  step = 0.5,
}) {
  const hours = snapHours(value)
  const prev = hours <= min ? null : snapHours(hours - step)
  const next = hours >= max ? null : snapHours(hours + step)
  const trackRef = useRef(null)

  function setHours(nextValue) {
    const snapped = snapHours(nextValue, hours)
    if (snapped !== hours) onChange(snapped)
  }

  useEffect(() => {
    const node = trackRef.current
    if (!node) return undefined
    function onWheel(event) {
      event.preventDefault()
      setHours(hours + (event.deltaY < 0 ? step : -step))
    }
    node.addEventListener('wheel', onWheel, { passive: false })
    return () => node.removeEventListener('wheel', onWheel)
  }, [hours, step])

  return (
    <div className={`hours-stepper is-${tone}`} role="group" aria-label={label}>
      <button
        type="button"
        className="hours-stepper-btn"
        disabled={prev == null}
        aria-label={`Decrease ${label}`}
        onClick={() => setHours(hours - step)}
      >
        −
      </button>
      <div ref={trackRef} className="hours-stepper-track" tabIndex={0}>
        <span>{prev == null ? ' ' : formatHours(prev)}</span>
        <strong>{formatHours(hours)}h</strong>
        <span>{next == null ? ' ' : formatHours(next)}</span>
      </div>
      <button
        type="button"
        className="hours-stepper-btn"
        disabled={next == null}
        aria-label={`Increase ${label}`}
        onClick={() => setHours(hours + step)}
      >
        +
      </button>
    </div>
  )
}
