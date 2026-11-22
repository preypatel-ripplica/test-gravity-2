const BAND = {
  strong: '#15803d',
  close: '#b45309',
  buried: '#c2410c',
  missing: '#b91c1c',
  failed: '#64748b',
}

const DIRECTION = { north: -90, east: 0, south: 90, west: 180 }

function bandOf(point) {
  if (point?.error) return 'failed'
  if (!point?.found || !point?.rank) return 'missing'
  if (point.rank <= 3) return 'strong'
  if (point.rank <= 10) return 'close'
  if (point.rank <= 20) return 'buried'
  return 'missing'
}

function position(point) {
  if (!point || point.km === 0) return [180, 180]
  const radius = (Number(point.km) / 18) * 132
  const degrees = DIRECTION[point.direction] ?? 0
  const radians = (degrees * Math.PI) / 180
  return [180 + radius * Math.cos(radians), 180 + radius * Math.sin(radians)]
}

export default function GbpRingMap({ points = [], activeId, onSelect }) {
  const clinic = points.find((point) => point.km === 0) || points[0]
  if (!clinic) return null
  return (
    <div className="gbp-ring">
      <svg className="gbp-ring-map" viewBox="0 0 360 360" role="img" aria-label="Ranks around the clinic">
        {[2, 6, 12, 18].map((km) => (
          <circle key={km} className="gbp-ring-line" cx="180" cy="180" r={(km / 18) * 132} />
        ))}
        {points.map((point) => {
          const [x, y] = position(point)
          const active = point.id === activeId
          return (
            <g key={point.id || `${point.km}-${point.direction}`} onClick={() => onSelect?.(point)} style={{ cursor: 'pointer' }}>
              <circle cx={x} cy={y} r={active ? 11 : 8} fill={BAND[bandOf(point)]} stroke="#fff" strokeWidth="2" />
            </g>
          )
        })}
      </svg>
      <p className="text-muted">The centre is the clinic. Rings are 2, 6, 12, and 18 km. Green is a strong rank, red means you were not in the top 20.</p>
    </div>
  )
}
