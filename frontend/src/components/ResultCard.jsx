import { AlertIcon, CheckIcon } from './icons/StatusIcons.jsx'

function formatPercent(value) {
  if (typeof value !== 'number') return '—'
  const pct = value * 100
  // Naive Bayes is famously confident; avoid printing a bare "100%".
  if (pct >= 99.95) return '>99.9%'
  if (pct <= 0.05) return '<0.1%'
  return `${pct.toFixed(1)}%`
}

export default function ResultCard({ result }) {
  const isSpam = result.is_spam ?? result.label === 'spam'
  const tone = isSpam ? 'spam' : 'ham'
  const confidence = result.confidence ?? 0
  const spamProbability = result.probabilities?.spam ?? (isSpam ? confidence : 1 - confidence)

  return (
    <section className={`card result result--${tone}`} aria-live="polite">
      <div className="result__banner">
        <span className="result__icon" aria-hidden="true">
          {isSpam ? <AlertIcon /> : <CheckIcon />}
        </span>
        <div className="result__headline">
          <span className="result__verdict">{isSpam ? 'Spam' : 'Ham'}</span>
          <span className="result__caption">
            {isSpam
              ? 'Flagged as unwanted or malicious'
              : 'Looks like a legitimate message'}
          </span>
        </div>
        <span className="result__confidence">
          <strong>{formatPercent(confidence)}</strong>
          <span>confidence</span>
        </span>
      </div>

      <div className="meter" role="img" aria-label={`Spam likelihood ${formatPercent(spamProbability)}`}>
        <div className="meter__track">
          <div
            className="meter__fill"
            style={{ width: `${Math.max(2, Math.min(100, spamProbability * 100))}%` }}
          />
        </div>
        <div className="meter__labels">
          <span>Ham {formatPercent(result.probabilities?.ham)}</span>
          <span>Spam {formatPercent(result.probabilities?.spam)}</span>
        </div>
      </div>

      <p className="result__explanation">{result.explanation}</p>

      {result.top_signals?.length ? (
        <div className="result__section">
          <h3 className="result__section-title">Key signals</h3>
          <ul className="chips">
            {result.top_signals.map((signal) => (
              <li key={signal.term} className={`chip chip--${tone}`}>
                <span className="chip__term">{signal.term}</span>
                <span className="chip__weight">{signal.weight.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <dl className="stats">
        <div className="stats__item">
          <dt>Words</dt>
          <dd>{result.stats?.words ?? '—'}</dd>
        </div>
        <div className="stats__item">
          <dt>After cleaning</dt>
          <dd>{result.stats?.cleaned_words ?? '—'}</dd>
        </div>
        <div className="stats__item">
          <dt>Known features</dt>
          <dd>{result.stats?.recognised_features ?? '—'}</dd>
        </div>
        <div className="stats__item">
          <dt>Quarantined</dt>
          <dd>{result.quarantined ? 'Yes' : 'No'}</dd>
        </div>
      </dl>
    </section>
  )
}
