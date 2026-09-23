import { useMemo, useState } from 'react'
import { ArrowMoveIcon, ChevronIcon } from './icons/StatusIcons.jsx'
import DetectionBadges, { DetectionDetail } from './DetectionBadges.jsx'

/**
 * Filters for the quarantine view.
 *
 * A message can match several filters at once (SPAM + PHISHING + HIGH RISK is
 * common). Each filter is an independent predicate over the stored verdicts,
 * so nothing is inferred from anything else.
 */
const FILTERS = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'spam', label: 'Spam', test: (m) => m.label === 'spam' },
  {
    id: 'phishing',
    label: 'Phishing',
    test: (m) => m.phishing_available === true && m.phishing_label === 'PHISHING',
  },
  { id: 'high', label: 'High Risk', test: (m) => m.risk_level === 'HIGH' },
]

const EMPTY_FILTER_TEXT = {
  spam: 'No messages were flagged by the spam detector.',
  phishing: 'No messages were flagged by the phishing detector.',
  high: 'No messages were assessed as high risk.',
}

const COPY = {
  quarantine: {
    title: 'Quarantine',
    hint: 'Messages requiring security review. Nothing is deleted.',
    tone: 'spam',
    emptyTitle: 'Quarantine is empty',
    emptyText:
      'Nothing has been flagged for review yet. Analyse a message to fill this up.',
    moveLabel: 'Not spam, move to Inbox',
    moveShort: 'Not spam',
    target: 'inbox',
  },
  inbox: {
    title: 'Inbox',
    hint: 'Messages the model let through as legitimate.',
    tone: 'ham',
    emptyTitle: 'Inbox is empty',
    emptyText: 'Nothing has been allowed through yet. Analyse a message to start.',
    moveLabel: 'Mark as spam, move to Quarantine',
    moveShort: 'Mark as spam',
    target: 'quarantine',
  },
}

function formatWhen(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function preview(text, limit = 110) {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat
}

export default function MessageList({
  box,
  messages,
  loading,
  movingId,
  onMove,
  onRefresh,
  initialExpandedId = null,
}) {
  const [expandedId, setExpandedId] = useState(initialExpandedId)
  const [filter, setFilter] = useState('all')
  const copy = COPY[box]

  // Filters only make sense for the review queue, not the delivered inbox.
  const showFilters = box === 'quarantine'

  const counts = useMemo(() => {
    const result = {}
    for (const entry of FILTERS) {
      result[entry.id] = messages.filter(entry.test).length
    }
    return result
  }, [messages])

  const visible = useMemo(() => {
    if (!showFilters) return messages
    const entry = FILTERS.find((f) => f.id === filter) ?? FILTERS[0]
    return messages.filter(entry.test)
  }, [messages, filter, showFilters])

  if (loading) {
    return (
      <section className="card">
        <div className="skeleton skeleton--bar" />
        <div className="skeleton skeleton--line" style={{ marginTop: 14 }} />
        <div className="skeleton skeleton--line" style={{ marginTop: 10 }} />
        <div className="skeleton skeleton--line skeleton--short" style={{ marginTop: 10 }} />
      </section>
    )
  }

  return (
    <section className="card">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">{copy.title}</h2>
          <p className="panel__hint">{copy.hint}</p>
        </div>
        <div className="panel__head-actions">
          <span className={`pill pill--${copy.tone}`}>
            {messages.length} {messages.length === 1 ? 'message' : 'messages'}
          </span>
          <button type="button" className="btn btn--tiny" onClick={onRefresh}>
            Refresh
          </button>
        </div>
      </div>

      {showFilters && messages.length > 0 ? (
        <div className="filters" role="tablist" aria-label="Filter quarantined messages">
          {FILTERS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              aria-selected={filter === entry.id}
              className={`filter ${filter === entry.id ? 'filter--active' : ''}`}
              onClick={() => setFilter(entry.id)}
            >
              {entry.label}
              <span className="filter__count">{counts[entry.id]}</span>
            </button>
          ))}
        </div>
      ) : null}

      {messages.length === 0 ? (
        <div className="empty empty--inline">
          <h3 className="empty__title">{copy.emptyTitle}</h3>
          <p className="empty__text">{copy.emptyText}</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="empty empty--inline">
          <h3 className="empty__title">Nothing matches this filter</h3>
          <p className="empty__text">
            {EMPTY_FILTER_TEXT[filter] ?? 'No messages match this filter.'}
          </p>
          <button
            type="button"
            className="btn btn--tiny"
            style={{ marginTop: 14 }}
            onClick={() => setFilter('all')}
          >
            Show all
          </button>
        </div>
      ) : (
        <ul className="messages">
          {visible.map((message) => {
            const isOpen = expandedId === message.id
            const isMoving = movingId === message.id

            return (
              <li
                key={message.id}
                className={`message message--${copy.tone} ${isOpen ? 'message--open' : ''}`}
              >
                <button
                  type="button"
                  className="message__summary"
                  onClick={() => setExpandedId(isOpen ? null : message.id)}
                  aria-expanded={isOpen}
                >
                  <span className={`message__chevron ${isOpen ? 'message__chevron--open' : ''}`} aria-hidden="true">
                    <ChevronIcon />
                  </span>

                  <span className="message__body">
                    <span className="message__text">{preview(message.text)}</span>

                    <DetectionBadges message={message} />

                    <span className="message__meta">
                      <span>{formatWhen(message.timestamp)}</span>
                      {message.moved ? (
                        <span className="badge badge--moved">Manually moved</span>
                      ) : null}
                    </span>
                  </span>
                </button>

                {isOpen ? (
                  <div className="message__detail">
                    <DetectionDetail message={message} />

                    <p className="message__full">{message.text}</p>
                    <div className="message__actions">
                      <button
                        type="button"
                        className={`btn btn--tiny btn--move btn--move-${copy.target}`}
                        onClick={() => onMove(message.id, copy.target)}
                        disabled={isMoving}
                        title={copy.moveLabel}
                      >
                        {isMoving ? (
                          <>
                            <span className="spinner spinner--dark" aria-hidden="true" />
                            Moving…
                          </>
                        ) : (
                          <>
                            <ArrowMoveIcon />
                            {copy.moveShort}
                          </>
                        )}
                      </button>
                      <span className="message__id">id {message.id}</span>
                    </div>
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
