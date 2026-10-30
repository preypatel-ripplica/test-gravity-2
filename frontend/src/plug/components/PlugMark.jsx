export default function PlugMark({ size = 28, className = '' }) {
  return (
    <svg
      className={`plug-mark ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="32" height="32" fill="#FF4D00" />
      <path
        d="M8 16.8l5.2 5.2L24 10.4"
        fill="none"
        stroke="#FCFBF8"
        strokeWidth="2.6"
        strokeLinecap="square"
        strokeLinejoin="miter"
      />
    </svg>
  )
}
