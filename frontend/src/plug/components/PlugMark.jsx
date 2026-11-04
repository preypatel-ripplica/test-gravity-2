export default function PlugMark({ size = 28, className = '' }) {
  return (
    <img
      className={`plug-mark ${className}`.trim()}
      src="/plug-mark.png"
      alt=""
      width={size}
      height={size}
      aria-hidden="true"
      draggable="false"
    />
  )
}
