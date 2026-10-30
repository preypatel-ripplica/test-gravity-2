import { useEffect, useMemo, useState } from 'react'

/** Elapsed time while a publish request is open. Stage text comes from the server. */
export function usePublishProgressStages(active) {
  const [elapsedSec, setElapsedSec] = useState(0)

  useEffect(() => {
    if (!active) {
      setElapsedSec(0)
      return undefined
    }
    const started = Date.now()
    const tick = () => setElapsedSec(Math.floor((Date.now() - started) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [active])

  const elapsedLabel = useMemo(() => {
    const m = Math.floor(elapsedSec / 60)
    const s = elapsedSec % 60
    return `${m}:${String(s).padStart(2, '0')}`
  }, [elapsedSec])

  return { elapsedLabel, hint: 'Keep this tab open. Do not refresh.' }
}
