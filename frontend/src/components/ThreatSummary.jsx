/** Compact three-row recap of the analysis. */
import { AlertIcon, CheckIcon, ShieldSmallIcon } from './icons/StatusIcons.jsx'

const RISK_TONE = { LOW: 'safe', MEDIUM: 'warn', HIGH: 'threat' }

function Row({ label, value, tone, icon }) {
  if (!value) return null

  return (
    <div className="summary__row">
      <span className="summary__label">{label}</span>
      <span className={`summary__value summary__value--${tone}`}>
        <span className="summary__icon" aria-hidden="true">{icon}</span>
        {value}
      </span>
    </div>
  )
}

export default function ThreatSummary({ result }) {
  if (!result) return null

  const spam = result.spam_detection
  const phishing = result.phishing_detection
  const assessment = result.security_assessment

  const spamIsThreat = spam?.prediction === 'SPAM'
  const phishingIsThreat = phishing?.prediction === 'PHISHING'
  const riskTone = RISK_TONE[assessment?.risk_level] ?? 'neutral'

  return (
    <section className="summary" aria-label="Email analysis summary">
      <h3 className="summary__title">Email Analysis Summary</h3>

      <div className="summary__rows">
        <Row
          label="Spam Status"
          value={spam?.available === false ? 'Unavailable' : spam?.prediction}
          tone={spamIsThreat ? 'threat' : 'safe'}
          icon={spamIsThreat ? <AlertIcon size={15} /> : <CheckIcon size={15} />}
        />
        <Row
          label="Phishing Status"
          value={phishing?.available === false ? 'Unavailable' : phishing?.prediction}
          tone={phishingIsThreat ? 'threat' : 'safe'}
          icon={phishingIsThreat ? <AlertIcon size={15} /> : <CheckIcon size={15} />}
        />
        <Row
          label="Risk Level"
          value={assessment?.risk_level}
          tone={riskTone}
          icon={<ShieldSmallIcon size={15} />}
        />
      </div>
    </section>
  )
}
