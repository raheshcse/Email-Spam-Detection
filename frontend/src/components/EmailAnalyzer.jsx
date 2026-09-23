/**
 * The email input workspace.
 *
 * The backend accepts a single `text` field, so subject and body are joined
 * with a blank line before submission — the same shape the model was trained
 * on (subject + "\n\n" + body).
 */
import { MailIcon, ScanIcon, TrashIcon } from './icons/StatusIcons.jsx'

const MAX_CHARS = 20000

export function composeEmail(subject, body) {
  const s = subject.trim()
  const b = body.trim()
  if (s && b) return `${s}\n\n${b}`
  return s || b
}

export default function EmailAnalyzer({
  subject,
  body,
  onSubjectChange,
  onBodyChange,
  onSubmit,
  onClear,
  loading,
  disabled,
}) {
  const combined = composeEmail(subject, body)
  const charCount = combined.length
  const wordCount = combined ? combined.split(/\s+/).length : 0
  const overLimit = charCount > MAX_CHARS
  const canSubmit = combined.length > 0 && !overLimit && !loading && !disabled

  function handleSubmit(event) {
    event.preventDefault()
    if (canSubmit) onSubmit(combined)
  }

  function handleKeyDown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && canSubmit) {
      event.preventDefault()
      onSubmit(combined)
    }
  }

  return (
    <form className="analyzer" onSubmit={handleSubmit} noValidate>
      <header className="analyzer__head">
        <span className="analyzer__icon" aria-hidden="true">
          <MailIcon size={18} />
        </span>
        <div>
          <h2 className="analyzer__title">Analyze an Email</h2>
          <p className="analyzer__subtitle">
            Submit an email to detect spam and phishing threats using machine
            learning.
          </p>
        </div>
      </header>

      <div className="field">
        <label className="field__label" htmlFor="email-subject">
          Subject <span className="field__optional">optional</span>
        </label>
        <input
          id="email-subject"
          type="text"
          className="field__input"
          placeholder="Account verification required"
          value={subject}
          onChange={(event) => onSubjectChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          autoComplete="off"
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="email-body">
          Email body
        </label>
        <textarea
          id="email-body"
          className="field__textarea"
          placeholder="Paste the full email content here…"
          value={body}
          onChange={(event) => onBodyChange(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={12}
          spellCheck="false"
          disabled={loading}
          aria-describedby="email-counter"
        />
      </div>

      <div className="analyzer__meta">
        <span
          id="email-counter"
          className={`counter ${overLimit ? 'counter--over' : ''}`}
        >
          {wordCount.toLocaleString()} words · {charCount.toLocaleString()} /{' '}
          {MAX_CHARS.toLocaleString()} characters
        </span>
        {overLimit ? (
          <span className="counter__warning" role="alert">
            Too long — the backend limit is {MAX_CHARS.toLocaleString()} characters.
          </span>
        ) : null}
      </div>

      <div className="analyzer__actions">
        <button type="submit" className="btn btn--primary" disabled={!canSubmit}>
          {loading ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Analyzing…
            </>
          ) : (
            <>
              <ScanIcon size={16} />
              Analyze Email
            </>
          )}
        </button>

        <button
          type="button"
          className="btn btn--ghost"
          onClick={onClear}
          disabled={loading || (!subject && !body)}
        >
          <TrashIcon size={15} />
          Clear
        </button>

        <span className="analyzer__hint" aria-hidden="true">Ctrl + Enter</span>
      </div>
    </form>
  )
}
