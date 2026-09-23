/**
 * Right-hand results column: empty, loading, error or results.
 *
 * Only one of these four states renders at a time.
 */
import DetectionCard from './DetectionCard.jsx'
import DetectionSignals from './DetectionSignals.jsx'
import SecurityAssessmentCard from './SecurityAssessmentCard.jsx'
import ThreatSummary from './ThreatSummary.jsx'
import { CpuIcon, ShieldSmallIcon, ThreatIcon } from './icons/StatusIcons.jsx'

function EmptyState() {
  return (
    <section className="rstate">
      <span className="rstate__glyph" aria-hidden="true">
        <ShieldSmallIcon size={30} />
      </span>
      <h2 className="rstate__title">Ready to Analyze</h2>
      <p className="rstate__text">
        Paste an email above and run the security analysis.
      </p>
    </section>
  )
}

function LoadingState() {
  return (
    <section className="rstate" aria-live="polite" aria-busy="true">
      <span className="spinner spinner--large" aria-hidden="true" />
      <h2 className="rstate__title">Analyzing email…</h2>
      <p className="rstate__text">
        Detection engines are evaluating the message.
      </p>
      <div className="rstate__bar" aria-hidden="true">
        <span className="rstate__bar-fill" />
      </div>
    </section>
  )
}

function ErrorState({ message, onRetry }) {
  return (
    <section className="rstate rstate--error" role="alert">
      <span className="rstate__glyph rstate__glyph--error" aria-hidden="true">
        <ThreatIcon size={30} />
      </span>
      <h2 className="rstate__title">Unable to analyze email</h2>
      <p className="rstate__text">{message}</p>
      {onRetry ? (
        <button type="button" className="btn btn--ghost" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </section>
  )
}

export default function AnalysisResults({ result, loading, error, onRetry }) {
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (!result) return <EmptyState />

  return (
    <div className="results">
      <h2 className="results__title">Security Analysis Results</h2>

      <DetectionCard
        title="Phishing Detection"
        icon={<CpuIcon size={16} />}
        result={result.phishing_detection}
        threatLabel="PHISHING"
        modelName="BERT"
        emphasis
      />

      <DetectionCard
        title="Spam Detection"
        icon={<ShieldSmallIcon size={16} />}
        result={result.spam_detection}
        threatLabel="SPAM"
        modelName="Naive Bayes"
      />

      <SecurityAssessmentCard assessment={result.security_assessment} />

      <ThreatSummary result={result} />

      <DetectionSignals result={result} />
    </div>
  )
}
