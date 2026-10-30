import { usePublishProgressStages } from '../hooks/usePublishProgressStages'

export default function PublishProgressBusy({ active, stage }) {
  const { elapsedLabel, hint } = usePublishProgressStages(active)

  if (!active) return null

  return (
    <span className="publish-progress-busy" style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4, textAlign: 'left' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <i className="fa-solid fa-spinner fa-spin" aria-hidden />
        <span>{stage || 'Starting publish…'}</span>
        <span style={{ opacity: 0.75, fontVariantNumeric: 'tabular-nums' }}>({elapsedLabel})</span>
      </span>
      <span style={{ fontSize: '0.85em', opacity: 0.8, fontWeight: 400 }}>{hint}</span>
    </span>
  )
}
