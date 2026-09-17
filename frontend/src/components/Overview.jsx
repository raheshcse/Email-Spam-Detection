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
    </div>
  )
}
