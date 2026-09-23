/**
 * Per-message detection badges for the Quarantine and Inbox lists.
 *
 * Spam and phishing are rendered as SEPARATE badges from SEPARATE detectors.
 * Nothing is inferred: a phishing badge only appears when the backend stored
 * a phishing verdict for that message. Legacy messages say so explicitly.
 *
 * Confidence is labelled "model confidence" rather than anything implying a
 * probability of real-world maliciousness.
 */

function formatConfidence(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return null
  const pct = value * 100
  if (pct >= 99.95) return '>99.9%'
  if (pct <= 0.05) return '<0.1%'
  return `${pct.toFixed(1)}%`
}

const RISK_TONE = { HIGH: 'threat', MEDIUM: 'warn', LOW: 'safe' }

export function Badge({ tone, label, detail, title }) {
  return (
    <span className={`dbadge dbadge--${tone}`} title={title}>
      <span className="dbadge__label">{label}</span>
      {detail ? <span className="dbadge__detail">{detail}</span> : null}
    </span>
  )
}

export default function DetectionBadges({ message, showDetail = false }) {
  if (!message) return null

  const spamIsThreat = message.label === 'spam'
  const spamConfidence = formatConfidence(message.confidence)

  const phishingAvailable = message.phishing_available === true
  const phishingIsThreat = message.phishing_label === 'PHISHING'
  const phishingConfidence = formatConfidence(message.phishing_confidence)

  const risk = message.risk_level
  const riskTone = RISK_TONE[risk] ?? 'neutral'

  return (
    <div className="dbadges">
      {/* Naive Bayes */}
      <Badge
        tone={spamIsThreat ? 'threat' : 'safe'}
        label={spamIsThreat ? 'SPAM' : 'HAM'}
        detail={showDetail && spamConfidence ? spamConfidence : null}
        title={`Spam detection (Naive Bayes)${
          spamConfidence ? ` — ${spamConfidence} model confidence` : ''
        }`}
      />

      {/* BERT - only when a verdict was actually stored */}
      {phishingAvailable ? (
        <Badge
          tone={phishingIsThreat ? 'threat' : 'safe'}
          label={phishingIsThreat ? 'PHISHING' : 'LEGITIMATE'}
          detail={showDetail && phishingConfidence ? phishingConfidence : null}
          title={`Phishing detection (BERT)${
            phishingConfidence ? ` — ${phishingConfidence} model confidence` : ''
          }`}
        />
      ) : (
        <Badge
          tone="unknown"
          label="PHISHING N/A"
          title="Phishing analysis unavailable for this message"
        />
      )}

      {/* Rule-based assessment */}
      {risk ? (
        <Badge
          tone={riskTone}
          label={`${risk} RISK`}
          title={`Rule-based security assessment: ${risk}`}
        />
      ) : null}
    </div>
  )
}

/** Expanded per-detector breakdown, shown when a message row is open. */
export function DetectionDetail({ message }) {
  if (!message) return null

  const spamIsThreat = message.label === 'spam'
  const spamConfidence = formatConfidence(message.confidence)
  const phishingAvailable = message.phishing_available === true
  const phishingIsThreat = message.phishing_label === 'PHISHING'
  const phishingConfidence = formatConfidence(message.phishing_confidence)
  const risk = message.risk_level

  return (
    <div className="ddetail">
      <div className={`ddetail__item ddetail__item--${spamIsThreat ? 'threat' : 'safe'}`}>
        <span className="ddetail__verdict">{spamIsThreat ? 'SPAM' : 'HAM'}</span>
        <span className="ddetail__conf">
          {spamConfidence ? `${spamConfidence} model confidence` : 'confidence not recorded'}
        </span>
        <span className="ddetail__engine">Naive Bayes</span>
      </div>

      {phishingAvailable ? (
        <div
          className={`ddetail__item ddetail__item--${phishingIsThreat ? 'threat' : 'safe'}`}
        >
          <span className="ddetail__verdict">
            {phishingIsThreat ? 'PHISHING' : 'LEGITIMATE'}
          </span>
          <span className="ddetail__conf">
            {phishingConfidence
              ? `${phishingConfidence} model confidence`
              : 'confidence not recorded'}
          </span>
          <span className="ddetail__engine">BERT</span>
        </div>
      ) : (
        <div className="ddetail__item ddetail__item--unknown">
          <span className="ddetail__verdict">Not analysed</span>
          <span className="ddetail__conf">
            Phishing analysis unavailable for this message
          </span>
          <span className="ddetail__engine">BERT</span>
        </div>
      )}

      {risk ? (
        <div className={`ddetail__item ddetail__item--${RISK_TONE[risk] ?? 'neutral'}`}>
          <span className="ddetail__verdict">{risk}</span>
          <span className="ddetail__conf">Security risk</span>
          <span className="ddetail__engine">Rule-based assessment</span>
        </div>
      ) : null}
    </div>
  )
}
