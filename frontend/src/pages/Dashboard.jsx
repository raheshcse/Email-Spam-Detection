/**
 * Analyzer view: input on the left, results on the right.
 *
 * Collapses to a single column under 1000px so cards stay readable on mobile
 * with no horizontal scrolling.
 */
import AnalysisResults from '../components/AnalysisResults.jsx'
import DetectionEngines from '../components/DetectionEngines.jsx'
import EmailAnalyzer from '../components/EmailAnalyzer.jsx'
import SystemStatus from '../components/SystemStatus.jsx'

export default function Dashboard({
  subject,
  body,
  onSubjectChange,
  onBodyChange,
  onAnalyze,
  onClear,
  loading,
  result,
  error,
  onRetry,
  health,
  connection,
  metrics,
  enginesDown,
}) {
  return (
    <div className="dash">
      <div className="dash__col dash__col--input">
        <EmailAnalyzer
          subject={subject}
          body={body}
          onSubjectChange={onSubjectChange}
          onBodyChange={onBodyChange}
          onSubmit={onAnalyze}
          onClear={onClear}
          loading={loading}
          disabled={enginesDown}
        />

        <SystemStatus
          health={health}
          connection={connection}
          onRetry={onRetry}
          compact
        />

        <DetectionEngines metrics={metrics} />
      </div>

      <div className="dash__col dash__col--results">
        <AnalysisResults
          result={result}
          loading={loading}
          error={error}
          onRetry={onRetry}
        />
      </div>
    </div>
  )
}
