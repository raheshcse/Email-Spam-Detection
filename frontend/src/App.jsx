import { useCallback, useEffect, useRef, useState } from 'react'

import Header from './components/Header.jsx'
import TabNav from './components/TabNav.jsx'
import Dashboard from './pages/Dashboard.jsx'
import SystemStatus from './components/SystemStatus.jsx'
import DetectionEngines from './components/DetectionEngines.jsx'
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
  const [tab, setTab] = useState('analyzer')

  // -- analyzer state --
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState('')

  // -- backend state --
  const [connection, setConnection] = useState('checking')
  const [health, setHealth] = useState(null)
  const [metrics, setMetrics] = useState(null)

  // -- mailbox state --
  const [stats, setStats] = useState(null)
  const [boxes, setBoxes] = useState(EMPTY_BOXES)
  const [boxLoading, setBoxLoading] = useState(false)
  const [movingId, setMovingId] = useState(null)
  const [notice, setNotice] = useState('')

  const abortRef = useRef(null)
  const lastSubmitted = useRef('')

  // ----------------------------------------------------------- backend --

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
        quarantine: quarantine?.messages ?? [],
        inbox: inbox?.messages ?? [],
      })
    } catch {
      // The mailbox is secondary; a failure here must not break the analyzer.
    } finally {
      setBoxLoading(false)
    }
  }, [])

  const probeBackend = useCallback(async () => {
    setConnection('checking')
    try {
      const healthPayload = await checkHealth()
      setHealth(healthPayload)
      setConnection('online')

      fetchMetrics().then(setMetrics).catch(() => {})
      loadMailboxes()
      return true
    } catch {
      setHealth(null)
      setConnection('offline')
      return false
    }
  }, [loadMailboxes])

  useEffect(() => {
    probeBackend()
    return () => abortRef.current?.abort()
  }, [probeBackend])

  // ------------------------------------------------------------ actions --

  const handleAnalyze = useCallback(
    async (text) => {
      const trimmed = (text ?? '').trim()

      if (!trimmed) {
        setAnalysisError('Enter an email before running the analysis.')
        setResult(null)
        return
      }

      // Guard against duplicate submissions while one is in flight.
      if (loading) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      lastSubmitted.current = trimmed

      setLoading(true)
      setAnalysisError('')
      setResult(null)

      try {
        const payload = await predictEmail(trimmed, controller.signal)
        setResult(payload)
        setConnection('online')
        loadMailboxes()
      } catch (error) {
        if (error.name === 'AbortError') return
        setResult(null)
        setAnalysisError(error.message)
        // Only a transport failure means the backend is down; a 4xx does not.
        if (!error.status) {
          setConnection('offline')
          setHealth(null)
        }
      } finally {
        if (abortRef.current === controller) setLoading(false)
      }
    },
    [loading, loadMailboxes]
  )

  const handleRetry = useCallback(async () => {
    const reachable = await probeBackend()
    if (reachable && lastSubmitted.current) {
      handleAnalyze(lastSubmitted.current)
    }
  }, [probeBackend, handleAnalyze])

  function handleClear() {
    abortRef.current?.abort()
    setSubject('')
    setBody('')
    setResult(null)
    setAnalysisError('')
    setLoading(false)
    lastSubmitted.current = ''
  }

  async function handleMove(id, target) {
    setMovingId(id)
    try {
      await moveMessage(id, target)
      await loadMailboxes()
      setNotice(
        target === 'inbox'
          ? 'Message restored to the Inbox and relabelled as ham.'
          : 'Message moved to Quarantine and relabelled as spam.'
      )
    } catch (error) {
      setNotice(error.message)
    } finally {
      setMovingId(null)
    }
  }

  // ------------------------------------------------------------- render --

  const counts = {
    quarantine: boxes.quarantine.length,
    inbox: boxes.inbox.length,
  }

  const enginesDown = connection === 'offline' || health?.status === 'unhealthy'

  return (
    <div className="app">
      <div className="app__glow" aria-hidden="true" />

      <div className="shell">
        <Header connection={connection} health={health} />

        <TabNav active={tab} onChange={setTab} counts={counts} />

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
          {tab === 'analyzer' ? (
            <Dashboard
              subject={subject}
              body={body}
              onSubjectChange={setSubject}
              onBodyChange={setBody}
              onAnalyze={handleAnalyze}
              onClear={handleClear}
              loading={loading}
              result={result}
              error={analysisError}
              onRetry={handleRetry}
              health={health}
              connection={connection}
              metrics={metrics}
              enginesDown={enginesDown}
            />
          ) : null}

          {tab === 'status' ? (
            <div className="stack">
              <SystemStatus
                health={health}
                connection={connection}
                onRetry={probeBackend}
              />
              <DetectionEngines metrics={metrics} />
            </div>
          ) : null}

          {tab === 'overview' ? (
            <Overview
              stats={stats}
              loading={boxLoading && !stats}
              onGoToClassifier={() => setTab('analyzer')}
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
          <span>AI Email Threat Detection</span>
          <span>Naive Bayes + BERT · FastAPI · React</span>
        </footer>
      </div>
    </div>
  )
}
