/**
 * Product header: identity on the left, live API status on the right.
 *
 * The status pill reflects GET /health only. It never claims "operational"
 * unless the backend actually said both models are loaded.
 */
import ShieldIcon from './icons/ShieldIcon.jsx'

function statusFor(connection, health) {
  if (connection === 'checking') {
    return { tone: 'idle', text: 'Connecting…' }
  }
  if (connection === 'offline') {
    return { tone: 'offline', text: 'API Unreachable' }
  }

  if (health?.status === 'healthy') {
    return { tone: 'online', text: 'System Operational' }
  }
  if (health?.status === 'degraded') {
    return { tone: 'warn', text: 'Degraded' }
  }
  if (health?.status === 'unhealthy') {
    return { tone: 'offline', text: 'Engines Offline' }
  }

  return { tone: 'idle', text: 'Status Unknown' }
}

export default function Header({ connection, health }) {
  const status = statusFor(connection, health)

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__logo" aria-hidden="true">
          <ShieldIcon size={22} />
        </span>
        <div className="topbar__text">
          <h1 className="topbar__title">AI Email Threat Detection</h1>
          <p className="topbar__subtitle">AI-powered email security analysis</p>
        </div>
      </div>

      <div className="topbar__status">
        <span
          className={`status status--${status.tone}`}
          role="status"
          aria-live="polite"
        >
          <span className="status__dot" aria-hidden="true" />
          {status.text}
        </span>
      </div>
    </header>
  )
}
