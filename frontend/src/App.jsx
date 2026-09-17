import { useCallback, useEffect, useRef, useState } from 'react'

import Header from './components/Header.jsx'
import TabNav from './components/TabNav.jsx'
import EmailForm from './components/EmailForm.jsx'
import ExampleMessages from './components/ExampleMessages.jsx'
import ResultCard from './components/ResultCard.jsx'
import ResultPlaceholder from './components/ResultPlaceholder.jsx'
import ErrorBanner from './components/ErrorBanner.jsx'
import HowItWorks from './components/HowItWorks.jsx'
import Overview from './components/Overview.jsx'
import MessageList from './components/MessageList.jsx'

import {
  checkHealth,
  fetchMessages,
  fetchMetrics,
  fetchStats,
  moveMessage,
  predictEmail,
} from './api.js'

const EMPTY_BOXES = { quarantine: [], inbox: [] }

export default function App() {
  const [tab, setTab] = useState('classifier')

  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [status, setStatus] = useState('checking')
  const [health, setHealth] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [activeExample, setActiveExample] = useState(null)

  const [stats, setStats] = useState(null)
  const [boxes, setBoxes] = useState(EMPTY_BOXES)
  const [boxLoading, setBoxLoading] = useState(false)
  const [movingId, setMovingId] = useState(null)

  const abortRef = useRef(null)

  // ---------------------------------------------------------------- data --

  const loadMailboxes = useCallback(async () => {
    setBoxLoading(true)
    try {
      const [statsPayload, quarantine, inbox] = await Promise.all([
        fetchStats(),
        fetchMessages('quarantine'),
        fetchMessages('inbox'),
      ])
      setStats(statsPayload)
      setBoxes({
        quarantine: quarantine.messages ?? [],
        inbox: inbox.messages ?? [],
      })
      setStatus('online')
    } catch (err) {
      setError(err.message)
      if (err.message.includes('reach the prediction service')) setStatus('offline')
    } finally {
      setBoxLoading(false)
    }
  }, [])

  const probeBackend = useCallback(async () => {
    setStatus('checking')
    try {
      const [healthPayload, metricsPayload] = await Promise.all([
        checkHealth(),
        fetchMetrics().catch(() => null),
      ])
      setHealth(healthPayload)
      if (metricsPayload) setMetrics(metricsPayload)
      setStatus('online')
      await loadMailboxes()
      return true
    } catch {
      setStatus('offline')
      return false
    }
  }, [loadMailboxes])

  useEffect(() => {
    probeBackend()
    return () => abortRef.current?.abort()
  }, [probeBackend])

  // ------------------------------------------------------------- actions --

  async function handleAnalyse() {
    const trimmed = text.trim()

    if (!trimmed) {
      setError('Please paste or type a message before analysing.')
      setResult(null)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    setNotice('')

    try {
      const payload = await predictEmail(trimmed, controller.signal)
      setResult(payload)
      setStatus('online')
      loadMailboxes()
    } catch (err) {
      if (err.name === 'AbortError') return
      setResult(null)
      setError(err.message)
      if (err.message.includes('reach the prediction service')) setStatus('offline')
    } finally {
      if (abortRef.current === controller) setLoading(false)
    }
  }

  function handleClear() {
    abortRef.current?.abort()
    setText('')
    setResult(null)
    setError('')
    setNotice('')
    setActiveExample(null)
    setLoading(false)
  }

  function handleSelectExample(example) {
    setText(example.text)
    setActiveExample(example.id)
    setResult(null)
    setError('')
  }

  async function handleMove(id, target) {
    setMovingId(id)
    setError('')
    try {
      await moveMessage(id, target)
      await loadMailboxes()
      setNotice(
        target === 'inbox'
          ? 'Message restored to the Inbox and relabelled as ham.'
          : 'Message moved to Quarantine and relabelled as spam.'
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setMovingId(null)
    }
  }

  // -------------------------------------------------------------- render --

  const counts = {
    quarantine: boxes.quarantine.length,
    inbox: boxes.inbox.length,
  }

  return (
    <div className="app">
      <div className="app__glow" aria-hidden="true" />

      <div className="shell">
        <Header status={status} health={health} />

        <TabNav active={tab} onChange={setTab} counts={counts} />

        <ErrorBanner
          message={error}
          onDismiss={() => setError('')}
          onRetry={status === 'offline' ? probeBackend : undefined}
        />

        {notice ? (
          <div className="notice" role="status">
            <span>{notice}</span>
            <button
              type="button"
              className="btn btn--tiny btn--quiet"
              onClick={() => setNotice('')}
            >
              Dismiss
            </button>
          </div>
        ) : null}

        <main
          id={`panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab}`}
          className="panel-area"
        >
          {tab === 'classifier' ? (
            <div className="stack">
              <div className="layout">
                <div className="layout__col">
                  <EmailForm
                    value={text}
                    onChange={(next) => {
                      setText(next)
                      setActiveExample(null)
                    }}
                    onSubmit={handleAnalyse}
                    onClear={handleClear}
                    loading={loading}
                  />
                  <ExampleMessages
                    onSelect={handleSelectExample}
                    disabled={loading}
                    activeId={activeExample}
                  />
                </div>

                <div className="layout__col">
                  {result && !loading ? (
                    <ResultCard result={result} />
                  ) : (
                    <ResultPlaceholder loading={loading} />
                  )}
                </div>
              </div>

              <HowItWorks metrics={metrics} />
            </div>
          ) : null}

          {tab === 'overview' ? (
            <Overview
              stats={stats}
              loading={boxLoading && !stats}
              onGoToClassifier={() => setTab('classifier')}
            />
          ) : null}

          {tab === 'quarantine' ? (
            <MessageList
              box="quarantine"
              messages={boxes.quarantine}
              loading={boxLoading && boxes.quarantine.length === 0}
              movingId={movingId}
              onMove={handleMove}
              onRefresh={loadMailboxes}
            />
          ) : null}

          {tab === 'inbox' ? (
            <MessageList
              box="inbox"
              messages={boxes.inbox}
              loading={boxLoading && boxes.inbox.length === 0}
              movingId={movingId}
              onMove={handleMove}
              onRefresh={loadMailboxes}
            />
          ) : null}
        </main>

        <footer className="footer">
          <span>Email Spam Detection Agent</span>
          <span>CountVectorizer + Multinomial Naive Bayes · FastAPI · React</span>
        </footer>
      </div>
    </div>
  )
}
