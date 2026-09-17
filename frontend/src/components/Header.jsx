import ShieldIcon from './icons/ShieldIcon.jsx'

const STATUS_COPY = {
  checking: { text: 'Connecting to model…', tone: 'idle' },
  online: { text: 'Model online', tone: 'online' },
  offline: { text: 'Backend offline', tone: 'offline' },
}

export default function Header({ status, health }) {
  const badge = STATUS_COPY[status] ?? STATUS_COPY.checking
  const warning = health?.cleaner?.warning

  return (
    <header className="header">
      <div className="header__brand">
        <span className="header__logo" aria-hidden="true">
          <ShieldIcon />
        </span>
        <div>
          <h1 className="header__title">Email Spam Detection Agent</h1>
          <p className="header__subtitle">
            Naive Bayes classifier for inbound email and SMS triage
          </p>
        </div>
      </div>

      <div className="header__meta">
        <span className={`status status--${badge.tone}`}>
          <span className="status__dot" aria-hidden="true" />
          {badge.text}
        </span>
        {health?.vocabulary_size ? (
          <span className="header__vocab">
            {health.vocabulary_size.toLocaleString()} term vocabulary
          </span>
        ) : null}
      </div>

      {warning ? (
        <p className="header__warning" role="status">
          {warning}
        </p>
      ) : null}
    </header>
  )
}
