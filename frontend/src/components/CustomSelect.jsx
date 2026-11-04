import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export default function CustomSelect({
  options = [],
  value,
  onChange,
  placeholder = 'Select',
  searchable = false,
  icon = null,
  className = '',
  disabled = false,
  compact = false,
  id,
  ariaLabel,
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [menuStyle, setMenuStyle] = useState(null)
  const containerRef = useRef(null)
  const triggerRef = useRef(null)
  const menuRef = useRef(null)

  const selectedOption = options.find((opt) => String(opt.value) === String(value))

  const placeMenu = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    const width = Math.max(rect.width, compact ? 140 : 180)
    const openUp = window.innerHeight - rect.bottom < 260 && rect.top > 260
    const alignRight = rect.left + width > window.innerWidth - 12
    setMenuStyle({
      top: openUp ? undefined : rect.bottom + 4,
      bottom: openUp ? window.innerHeight - rect.top + 4 : undefined,
      left: alignRight ? undefined : Math.max(8, rect.left),
      right: alignRight ? Math.max(8, window.innerWidth - rect.right) : undefined,
      width,
    })
  }, [compact])

  useLayoutEffect(() => {
    if (!isOpen) return undefined
    placeMenu()
    window.addEventListener('resize', placeMenu)
    window.addEventListener('scroll', placeMenu, true)
    return () => {
      window.removeEventListener('resize', placeMenu)
      window.removeEventListener('scroll', placeMenu, true)
    }
  }, [isOpen, placeMenu, searchTerm])

  useEffect(() => {
    if (!isOpen) {
      setSearchTerm('')
      return undefined
    }
    function onDoc(event) {
      if (containerRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return
      setIsOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [isOpen])

  const filteredOptions = searchable
    ? options.filter((opt) =>
        String(opt.label).toLowerCase().includes(searchTerm.toLowerCase())
        || String(opt.detail || '').toLowerCase().includes(searchTerm.toLowerCase())
      )
    : options

  return (
    <div
      className={`custom-select-container${compact ? ' is-compact' : ''}${disabled ? ' is-disabled' : ''}${isOpen ? ' is-open' : ''}${className ? ` ${className}` : ''}`}
      ref={containerRef}
    >
      <button
        ref={triggerRef}
        type="button"
        id={id}
        disabled={disabled}
        className={`custom-select-trigger${isOpen ? ' active' : ''}`}
        onClick={() => { if (!disabled) setIsOpen((open) => !open) }}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={ariaLabel}
      >
        <span className="custom-select-trigger-content">
          {icon ? <span className="custom-select-trigger-icon">{icon}</span> : null}
          <span className="custom-select-trigger-label">
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          {selectedOption?.badge ? (
            <span className="custom-select-badge">{selectedOption.badge}</span>
          ) : null}
        </span>
        <i className={`fa-solid fa-chevron-down select-arrow-icon${isOpen ? ' open' : ''}`} />
      </button>

      {isOpen
        ? createPortal(
            <div
              ref={menuRef}
              className="custom-select-dropdown"
              style={menuStyle || { visibility: 'hidden' }}
            >
              {searchable ? (
                <div className="custom-select-search-wrapper">
                  <i className="fa-solid fa-magnifying-glass search-icon" />
                  <input
                    type="text"
                    className="custom-select-search-input"
                    placeholder="Search…"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                  />
                </div>
              ) : null}
              <div className="custom-select-options-list" role="listbox">
                {filteredOptions.length === 0 ? (
                  <div className="custom-select-no-results">No options found</div>
                ) : filteredOptions.map((opt, index) => {
                  const isSelected = String(opt.value) === String(value)
                  return (
                    <button
                      key={`${String(opt.value)}-${index}`}
                      type="button"
                      className={`custom-select-option${isSelected ? ' selected' : ''}`}
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => {
                        onChange(opt.value)
                        setIsOpen(false)
                      }}
                    >
                      <span className="custom-select-option-left">
                        {opt.icon ? <span className="custom-select-option-icon">{opt.icon}</span> : null}
                        <span className="custom-select-option-text">
                          <span className="custom-select-option-label">{opt.label}</span>
                          {opt.detail ? (
                            <span className="custom-select-option-detail">{opt.detail}</span>
                          ) : null}
                        </span>
                      </span>
                      <span className="custom-select-option-right">
                        {opt.badge ? <span className="custom-select-badge">{opt.badge}</span> : null}
                        {isSelected ? <i className="fa-solid fa-check option-check-icon" /> : null}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
