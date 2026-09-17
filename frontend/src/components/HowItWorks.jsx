const STEPS = [
  {
    step: '01',
    title: 'Text cleaning with NLP',
    body: 'The raw message is lowercased, URLs and non-letter characters are stripped, then spaCy tokenises it, drops stop words and lemmatises what is left, so "winning" and "wins" both become "win".',
  },
  {
    step: '02',
    title: 'CountVectorizer turns words into numbers',
    body: 'The cleaned text is mapped onto a 5,000-term vocabulary of unigrams and bigrams learned from the training set. Each message becomes a sparse count vector the model can do arithmetic on.',
  },
  {
    step: '03',
    title: 'Multinomial Naive Bayes predicts',
    body: 'The classifier multiplies the per-word probabilities it learned for each class, with Laplace smoothing so unseen words never zero out a class, and returns whichever of spam or ham scores higher.',
  },
  {
    step: '04',
    title: 'Spam is quarantined',
    body: 'Anything predicted as spam is appended to data/quarantine/quarantine.csv with a timestamp, so flagged messages stay reviewable instead of disappearing.',
  },
]

const DEFAULT_METRICS = {
  test_accuracy: 0.98,
  spam_precision: 0.96,
  spam_recall: 0.9,
}

export default function HowItWorks({ metrics }) {
  const m = metrics ?? DEFAULT_METRICS
  const cards = [
    {
      value: `${Math.round(m.test_accuracy * 100)}%`,
      label: 'Test accuracy',
      note: 'Correct calls on the held-out 20% split',
    },
    {
      value: `${Math.round(m.spam_precision * 100)}%`,
      label: 'Spam precision',
      note: 'Of messages flagged spam, how many really were',
    },
    {
      value: `${Math.round(m.spam_recall * 100)}%`,
      label: 'Spam recall',
      note: 'Of all real spam, how much got caught',
    },
  ]

  return (
    <section className="card how" id="how-it-works">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">How it works</h2>
          <p className="panel__hint">
            Four stages run every time you press Analyse Email.
          </p>
        </div>
      </div>

      <ol className="steps">
        {STEPS.map((item) => (
          <li key={item.step} className="step">
            <span className="step__number">{item.step}</span>
            <div>
              <h3 className="step__title">{item.title}</h3>
              <p className="step__body">{item.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="metrics">
        {cards.map((card) => (
          <div key={card.label} className="metric">
            <span className="metric__value">{card.value}</span>
            <span className="metric__label">{card.label}</span>
            <span className="metric__note">{card.note}</span>
          </div>
        ))}
      </div>

      <p className="how__footnote">
        Figures are approximate and come from{' '}
        <code>src/models/evaluate.py</code> on the held-out test split. Recall
        below precision is the deliberate trade-off here: it is better to let a
        little spam through than to quarantine a real message.
      </p>
    </section>
  )
}
