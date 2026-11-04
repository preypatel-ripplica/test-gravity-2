import PlugMark from '../plug/components/PlugMark'

export default function BrandLockup({ subtitle = 'Internal workspace' }) {
  return (
    <div className="brand-lockup">
      <PlugMark size={36} />
      <div className="brand-lockup-copy">
        <h3>Plug</h3>
        <p>{subtitle}</p>
        <span className="brand-bar" />
      </div>
    </div>
  )
}
