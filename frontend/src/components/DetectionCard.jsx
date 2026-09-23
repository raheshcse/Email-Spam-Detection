/**
 * One detector's verdict.
 *
 * Renders only what the API returned. If a field is missing the row is
 * omitted rather than filled with a placeholder number.
 */
import { AlertIcon, CheckIcon } from './icons/StatusIcons.jsx'

function formatPercent(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return null
  const pct = value * 100
  // The models are often extremely confident; avoid printing a bare 100%.
  if (pct >= 99.95) return '>99.9%'
  if (pct <= 0.05) return '<0.1%'
  return `${pct.toFixed(1)}%`
}

export default function DetectionCard({
  title,
  icon,
  result,
  threatLabel,
  modelName,
  emphasis = false,
}) {
  if (!result) return null

  // The detector could not run. Say so plainly instead of showing a verdict.
  if (result.available === false) {
    return (
      <section className={`dcard dcard--unavailable ${emphasis ? 'dcard--emphasis' : ''}`}>
        <header className="dcard__head">
          <span className="dcard__icon" aria-hidden="true">{icon}</span>
          <h3 className="dcard__title">{title}</h3>
        </header>
        <p className="dcard__unavailable">
          This detector is unavailable.
          {result.error ? ` ${result.error}` : ''}
        </p>
      </section>
    )
  }

  const isThreat = result.prediction === threatLabel
  const tone = isThreat ? 'threat' : 'safe'
  const confidence = formatPercent(result.confidence)
  const probability = formatPercent(result.probability)

  return (
    <section
      className={`dcard dcard--${tone} ${emphasis ? 'dcard--emphasis' : ''}`}
      aria-label={`${title}: ${result.prediction}`}
    >
      <header className="dcard__head">
        <span className="dcard__icon" aria-hidden="true">{icon}</span>
        <h3 className="dcard__title">{title}</h3>
        {emphasis ? <span className="dcard__badge">Primary</span> : null}
      </header>

      <div className="dcard__verdict">
        <span className="dcard__verdict-icon" aria-hidden="true">
          {isThreat ? <AlertIcon size={22} /> : <CheckIcon size={22} />}
        </span>
        <span className="dcard__prediction">{result.prediction}</span>
      </div>

      <dl className="dcard__rows">
        {confidence ? (
          <div className="dcard__row">
            <dt>Confidence</dt>
            <dd>{confidence}</dd>
          </div>
        ) : null}

        {probability ? (
          <div className="dcard__row">
            <dt>{threatLabel === 'PHISHING' ? 'P(phishing)' : 'P(spam)'}</dt>
            <dd>{probability}</dd>
          </div>
        ) : null}

        <div className="dcard__row">
          <dt>Model</dt>
          <dd className="dcard__model">{modelName || result.model}</dd>
        </div>
      </dl>

      {result.truncated ? (
        <p className="dcard__note">
          Email exceeded 512 tokens and was truncated before classification.
        </p>
      ) : null}
    </section>
  )
}
