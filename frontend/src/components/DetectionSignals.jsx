/**
 * "Why was this flagged?"
 *
 * Shows only what the backend actually sent: the Naive Bayes explanation
 * string and its top contributing tokens. Nothing is invented, and if neither
 * field is present the whole section is hidden.
 *
 * These signals come from the SPAM model only. BERT does not expose per-token
 * attributions here, so the heading says so rather than implying otherwise.
 */
export default function DetectionSignals({ result }) {
  if (!result) return null

  const explanation = result.explanation
  const signals = Array.isArray(result.top_signals) ? result.top_signals : []

  if (!explanation && signals.length === 0) return null

  const isSpam = result.spam_detection?.prediction === 'SPAM'

  return (
    <section className="signals" aria-label="Why was this flagged">
      <h3 className="signals__title">Why was this flagged?</h3>

      {explanation ? <p className="signals__explanation">{explanation}</p> : null}

      {signals.length > 0 ? (
        <>
          <h4 className="signals__subtitle">
            Detection signals
            <span className="signals__source">from the spam model</span>
          </h4>
          <ul className="signals__list">
            {signals.map((signal) => (
              <li
                key={signal.term}
                className={`signal ${isSpam ? 'signal--threat' : 'signal--safe'}`}
              >
                <span className="signal__term">{signal.term}</span>
                {typeof signal.weight === 'number' ? (
                  <span className="signal__weight">{signal.weight.toFixed(2)}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  )
}
