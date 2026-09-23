import BarChart from './BarChart.jsx'

function percent(value) {
  return `${Math.round((value ?? 0) * 100)}%`
}

function formatWhen(iso) {
  if (!iso) return 'Nothing analysed yet'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function Overview({ stats, loading, onGoToClassifier }) {
  if (loading) {
    return (
      <section className="card">
        <div className="skeleton skeleton--banner" />
        <div className="skeleton skeleton--bar" style={{ marginTop: 16 }} />
        <div className="skeleton skeleton--line" style={{ marginTop: 16 }} />
      </section>
    )
  }

  const total = stats?.total ?? 0

  if (!total) {
    return (
      <section className="card result result--empty">
        <div className="empty">
          <span className="empty__glyph" aria-hidden="true">
            ⌁
          </span>
          <h2 className="empty__title">No detections yet</h2>
          <p className="empty__text">
            Analyse a few messages and this page will fill up with your spam and
            ham totals.
          </p>
          <button
            type="button"
            className="btn btn--primary"
            style={{ marginTop: 16 }}
            onClick={onGoToClassifier}
          >
            Go to Classifier
          </button>
        </div>
      </section>
    )
  }

  const cards = [
    { key: 'total', value: total, label: 'Messages analysed', tone: 'neutral' },
    { key: 'spam', value: stats.spam_count, label: 'Flagged as spam', tone: 'spam' },
    { key: 'ham', value: stats.ham_count, label: 'Allowed as ham', tone: 'ham' },
    {
      key: 'moved',
      value: stats.moved_count,
      label: 'Manually corrected',
      tone: 'neutral',
    },
  ]

  // Phishing is a separate detector, so it gets its own counters rather than
  // being folded into the spam row. Only rendered when the backend actually
  // reports phishing fields, so an older backend degrades cleanly.
  const hasPhishingData = typeof stats.phishing_analysed === 'number'

  const phishingCards = hasPhishingData
    ? [
        {
          key: 'phishing',
          value: stats.phishing_count,
          label: 'Flagged as phishing',
          tone: 'spam',
        },
        {
          key: 'legitimate',
          value: stats.legitimate_count,
          label: 'Non-phishing',
          tone: 'ham',
        },
        {
          key: 'high-risk',
          value: stats.high_risk_count ?? 0,
          label: 'High risk',
          tone: 'spam',
        },
        {
          key: 'unknown',
          value: stats.phishing_unknown ?? 0,
          label: 'Not analysed for phishing',
          tone: 'neutral',
        },
      ]
    : []

  return (
    <div className="stack">
      <section className="card">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">Detection summary</h2>
            <p className="panel__hint">
              Every message you have analysed, across both mailboxes.
            </p>
          </div>
          <span className="panel__counter">
            Last analysed {formatWhen(stats.last_analysed)}
          </span>
        </div>

        <div className="counters">
          {cards.map((card) => (
            <div key={card.key} className={`counter counter--${card.tone}`}>
              <span className="counter__value">{card.value}</span>
              <span className="counter__label">{card.label}</span>
            </div>
          ))}
        </div>
      </section>

      {hasPhishingData ? (
        <section className="card">
          <div className="panel__head">
            <div>
              <h2 className="panel__title">Phishing detection</h2>
              <p className="panel__hint">
                Assessed independently of spam by the BERT classifier. An email
                can be ham and phishing at the same time.
              </p>
            </div>
          </div>

          <div className="counters">
            {phishingCards.map((card) => (
              <div key={card.key} className={`counter counter--${card.tone}`}>
                <span className="counter__value">{card.value}</span>
                <span className="counter__label">{card.label}</span>
              </div>
            ))}
          </div>

          {stats.phishing_unknown > 0 ? (
            <p className="overview__note">
              {stats.phishing_unknown.toLocaleString()} message
              {stats.phishing_unknown === 1 ? ' was' : 's were'} stored before
              phishing detection was added, so they carry no phishing verdict.
              They are excluded from the phishing chart below.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="card">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">Spam vs ham</h2>
            <p className="panel__hint">
              {percent(stats.spam_rate)} of what you analysed was flagged as spam.
            </p>
          </div>
        </div>

        <BarChart
          data={[
            { label: 'Spam', value: stats.spam_count, tone: 'spam' },
            { label: 'Ham', value: stats.ham_count, tone: 'ham' },
          ]}
        />

        <div className="split">
          <div
            className="split__part split__part--spam"
            style={{ flexGrow: Math.max(stats.spam_count, 0.001) }}
            title={`Spam ${percent(stats.spam_rate)}`}
          />
          <div
            className="split__part split__part--ham"
            style={{ flexGrow: Math.max(stats.ham_count, 0.001) }}
            title={`Ham ${percent(stats.ham_rate)}`}
          />
        </div>
        <div className="split__legend">
          <span>
            <i className="dot dot--spam" aria-hidden="true" /> Spam{' '}
            {percent(stats.spam_rate)}
          </span>
          <span>
            <i className="dot dot--ham" aria-hidden="true" /> Ham{' '}
            {percent(stats.ham_rate)}
          </span>
        </div>
      </section>

      {/* Deliberately a separate chart. Spam and phishing are different
          detection dimensions, so combining them into one visualisation
          would imply a relationship that does not exist. */}
      {hasPhishingData && stats.phishing_analysed > 0 ? (
        <section className="card">
          <div className="panel__head">
            <div>
              <h2 className="panel__title">Phishing vs legitimate</h2>
              <p className="panel__hint">
                {percent(stats.phishing_rate)} of the{' '}
                {stats.phishing_analysed.toLocaleString()} messages analysed for
                phishing were flagged.
              </p>
            </div>
          </div>

          <BarChart
            data={[
              { label: 'Phishing', value: stats.phishing_count, tone: 'spam' },
              { label: 'Legitimate', value: stats.legitimate_count, tone: 'ham' },
            ]}
          />

          <div className="split">
            <div
              className="split__part split__part--spam"
              style={{ flexGrow: Math.max(stats.phishing_count, 0.001) }}
              title={`Phishing ${percent(stats.phishing_rate)}`}
            />
            <div
              className="split__part split__part--ham"
              style={{ flexGrow: Math.max(stats.legitimate_count, 0.001) }}
              title={`Legitimate ${percent(stats.legitimate_rate)}`}
            />
          </div>
          <div className="split__legend">
            <span>
              <i className="dot dot--spam" aria-hidden="true" /> Phishing{' '}
              {percent(stats.phishing_rate)}
            </span>
            <span>
              <i className="dot dot--ham" aria-hidden="true" /> Legitimate{' '}
              {percent(stats.legitimate_rate)}
            </span>
          </div>
        </section>
      ) : null}
    </div>
  )
}
