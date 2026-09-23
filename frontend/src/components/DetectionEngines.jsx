/**
 * Architecture summary.
 *
 * The model names are fixed facts about the system. Any accuracy figures come
 * from GET /metrics and are only rendered when actually present.
 */
import { CpuIcon, ShieldSmallIcon } from './icons/StatusIcons.jsx'

function percent(value) {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : null
}

export default function DetectionEngines({ metrics }) {
  const spamAccuracy = percent(metrics?.test_accuracy)
  const phishingMetrics = metrics?.phishing
  const phishingRecall = percent(phishingMetrics?.phishing_recall)
  const phishingPrecision = percent(phishingMetrics?.phishing_precision)

  return (
    <section className="engines">
      <h3 className="engines__title">Detection Engines</h3>

      <div className="engines__grid">
        <article className="engine">
          <span className="engine__icon" aria-hidden="true">
            <ShieldSmallIcon size={16} />
          </span>
          <h4 className="engine__name">Spam Detection</h4>
          <p className="engine__tech">Naive Bayes + CountVectorizer</p>
          {spamAccuracy ? (
            <p className="engine__metric">{spamAccuracy} test accuracy</p>
          ) : null}
        </article>

        <article className="engine engine--primary">
          <span className="engine__icon" aria-hidden="true">
            <CpuIcon size={16} />
          </span>
          <h4 className="engine__name">Phishing Detection</h4>
          <p className="engine__tech">BERT fine-tuned classifier</p>
          {phishingRecall && phishingPrecision ? (
            <p className="engine__metric">
              {phishingRecall} recall · {phishingPrecision} precision
            </p>
          ) : null}
        </article>
      </div>
    </section>
  )
}
