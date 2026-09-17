export default function ResultPlaceholder({ loading }) {
  if (loading) {
    return (
      <section className="card result result--loading" aria-live="polite">
        <div className="skeleton skeleton--banner" />
        <div className="skeleton skeleton--bar" />
        <div className="skeleton skeleton--line" />
        <div className="skeleton skeleton--line skeleton--short" />
        <p className="result__loading-text">
          Cleaning text, vectorising and scoring against the model…
        </p>
      </section>
    )
  }

  return (
    <section className="card result result--empty">
      <div className="empty">
        <span className="empty__glyph" aria-hidden="true">
          ⌁
        </span>
        <h2 className="empty__title">No analysis yet</h2>
        <p className="empty__text">
          Paste a message and press <strong>Analyse Email</strong>, or pick one
          of the examples to see how the classifier responds.
        </p>
      </div>
    </section>
  )
}
