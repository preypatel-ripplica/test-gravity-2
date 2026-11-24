/** YouTube vs Instagram on a shared page. Not a profession flag. */

export default function SourceSwitcher({ value, onChange, ariaLabel = 'Content source' }) {
  return (
    <div className="source-switcher" role="tablist" aria-label={ariaLabel}>
      <button
        type="button"
        role="tab"
        aria-selected={value === 'youtube'}
        className={`source-switcher-btn ${value === 'youtube' ? 'active' : ''}`}
        onClick={() => onChange('youtube')}
      >
        <i className="fa-brands fa-youtube" />
        YouTube
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={value === 'instagram'}
        className={`source-switcher-btn ${value === 'instagram' ? 'active' : ''}`}
        onClick={() => onChange('instagram')}
      >
        <i className="fa-brands fa-instagram" />
        Instagram
      </button>
    </div>
  )
}
