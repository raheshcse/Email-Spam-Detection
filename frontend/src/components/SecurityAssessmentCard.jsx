/**
 * The rule-based risk level.
 *
 * Deliberately styled differently from the two detector cards, and labelled
 * explicitly, so nobody reads it as a third model output. The backend sends
 * is_ml_prediction: false for exactly this reason.
 */
import { InfoIcon, ShieldSmallIcon } from './icons/StatusIcons.jsx'

const TONE = {
  LOW: 'safe',
  MEDIUM: 'warn',
  HIGH: 'threat',
}

export default function SecurityAssessmentCard({ assessment }) {
  if (!assessment) return null

  const tone = TONE[assessment.risk_level] ?? 'neutral'

  return (
    <section
      className={`assess assess--${tone}`}
      aria-label={`Security assessment: ${assessment.risk_level} risk`}
    >
      <header className="assess__head">
        <span className="assess__icon" aria-hidden="true">
          <ShieldSmallIcon size={18} />
        </span>
        <div>
          <h3 className="assess__title">Security Assessment</h3>
          <p className="assess__method">
            <InfoIcon size={12} /> Rule-based, not a machine-learning prediction
          </p>
        </div>
      </header>

      <div className="assess__level">
        <span className="assess__level-label">Risk</span>
        <span className="assess__level-value">{assessment.risk_level}</span>
      </div>

      {assessment.reason ? (
        <div className="assess__block">
          <span className="assess__block-label">Reason</span>
          <p className="assess__block-text">{assessment.reason}</p>
        </div>
      ) : null}

      {assessment.recommended_action ? (
        <div className="assess__block">
          <span className="assess__block-label">Recommended action</span>
          <p className="assess__block-text">{assessment.recommended_action}</p>
        </div>
      ) : null}

      {assessment.degraded ? (
        <p className="assess__degraded">
          One detector was unavailable, so this assessment is based on partial
          information.
        </p>
      ) : null}
    </section>
  )
}
