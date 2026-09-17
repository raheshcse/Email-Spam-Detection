import { ScanIcon, TrashIcon } from './icons/StatusIcons.jsx'

export default function EmailForm({
  value,
  onChange,
  onSubmit,
  onClear,
  loading,
}) {
  const charCount = value.length
  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0

  function handleSubmit(event) {
    event.preventDefault()
    onSubmit()
  }

  function handleKeyDown(event) {
    // Ctrl/Cmd + Enter submits, which is what people expect in a text box.
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <form className="card panel" onSubmit={handleSubmit}>
      <div className="panel__head">
        <div>
          <h2 className="panel__title">Message to analyse</h2>
          <p className="panel__hint">
            Paste an email or SMS body. Nothing leaves your machine.
          </p>
        </div>
        <span className="panel__counter">
          {wordCount} words · {charCount} chars
        </span>
      </div>

      <label className="sr-only" htmlFor="email-input">
        Email or message text
      </label>
      <textarea
        id="email-input"
        className="textarea"
        placeholder="Subject: Congratulations, you have been selected…&#10;&#10;Paste the message here and press Analyse Email."
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={10}
        spellCheck="false"
        disabled={loading}
      />

      <div className="panel__actions">
        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Analysing…
            </>
          ) : (
            <>
              <ScanIcon />
              Analyse Email
            </>
          )}
        </button>

        <button
          type="button"
          className="btn btn--ghost"
          onClick={onClear}
          disabled={loading || (!value && !charCount)}
        >
          <TrashIcon />
          Clear
        </button>

        <span className="panel__shortcut">Ctrl + Enter</span>
      </div>
    </form>
  )
}
