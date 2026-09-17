export default function ErrorBanner({ message, onDismiss, onRetry }) {
  if (!message) return null

  return (
    <div className="alert" role="alert">
      <span className="alert__icon" aria-hidden="true">
        !
      </span>
      <p className="alert__text">{message}</p>
      <div className="alert__actions">
        {onRetry ? (
          <button type="button" className="btn btn--tiny" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn--tiny btn--quiet"
          onClick={onDismiss}
          aria-label="Dismiss error"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}
