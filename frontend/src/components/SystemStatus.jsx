/**
 * System status panel, driven entirely by GET /health.
 *
 * Nothing here is hardcoded. If /health has not returned yet the rows show a
 * checking state; if it failed they show unavailable.
 */
import { CpuIcon, ServerIcon, ShieldSmallIcon } from './icons/StatusIcons.jsx'

function StatusRow({ icon, label, state, detail }) {
  return (
    <div className="srow">
      <span className="srow__icon" aria-hidden="true">{icon}</span>
      <div className="srow__body">
        <span className="srow__label">{label}</span>
        {detail ? <span className="srow__detail">{detail}</span> : null}
      </div>
      <span className={`srow__state srow__state--${state.tone}`}>
        <span className="srow__dot" aria-hidden="true" />
        {state.text}
      </span>
    </div>
  )
}

export default function SystemStatus({ health, connection, onRetry, compact = false }) {
  // connection: 'checking' | 'online' | 'offline'
  const offline = connection === 'offline'
  const checking = connection === 'checking'

  const apiState = offline
    ? { tone: 'threat', text: 'Unreachable' }
    : checking
      ? { tone: 'idle', text: 'Checking…' }
      : { tone: 'safe', text: 'Operational' }

  function modelState(loadedFlag) {
    if (offline) return { tone: 'threat', text: 'Unknown' }
    if (checking || !health) return { tone: 'idle', text: 'Checking…' }
    return loadedFlag
      ? { tone: 'safe', text: 'Loaded' }
      : { tone: 'threat', text: 'Not loaded' }
  }

  const spamLoaded = health?.spam_model === 'loaded'
  const phishingLoaded = health?.phishing_model === 'loaded'
  const degraded = health?.status === 'degraded'
  const unhealthy = health?.status === 'unhealthy'

  const phishingDevice = health?.detectors?.phishing?.device

  return (
    <section className={`sysstatus ${compact ? 'sysstatus--compact' : ''}`}>
      <header className="sysstatus__head">
        <h3 className="sysstatus__title">System Status</h3>
        {onRetry ? (
          <button type="button" className="btn btn--tiny" onClick={onRetry}>
            Refresh
          </button>
        ) : null}
      </header>

      {offline ? (
        <p className="sysstatus__alert sysstatus__alert--threat" role="status">
          Cannot reach the backend. Start it with{' '}
          <code>python -m uvicorn src.main:app --reload</code>
        </p>
      ) : null}

      {!offline && degraded ? (
        <p className="sysstatus__alert sysstatus__alert--warn" role="status">
          Service is degraded — one detection engine failed to load. Analysis
          will continue with the remaining engine.
        </p>
      ) : null}

      {!offline && unhealthy ? (
        <p className="sysstatus__alert sysstatus__alert--threat" role="status">
          No detection engines are loaded. Analysis is unavailable.
        </p>
      ) : null}

      <div className="sysstatus__rows">
        <StatusRow
          icon={<ServerIcon size={16} />}
          label="API"
          detail="FastAPI"
          state={apiState}
        />
        <StatusRow
          icon={<ShieldSmallIcon size={16} />}
          label="Spam Detection Model"
          detail="Naive Bayes"
          state={modelState(spamLoaded)}
        />
        <StatusRow
          icon={<CpuIcon size={16} />}
          label="Phishing BERT Model"
          detail={phishingDevice ? `BERT · ${phishingDevice}` : 'BERT'}
          state={modelState(phishingLoaded)}
        />
      </div>
    </section>
  )
}
