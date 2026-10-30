export default function PlugPageHeader({ kicker, title, subtitle, actions }) {
  return (
    <header className="plug-chrome">
      {kicker ? <p className="plug-kicker">{kicker}</p> : null}
      <div className="plug-chrome-row">
        <div className="plug-chrome-copy">
          <h1 className="plug-title">{title}</h1>
          {subtitle ? <p className="plug-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="plug-chrome-actions">{actions}</div> : null}
      </div>
    </header>
  )
}
