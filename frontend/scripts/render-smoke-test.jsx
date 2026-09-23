// Offline render check for the threat detection dashboard.
//
// Server-renders every component with representative props and asserts the
// important strings and state classes appear. It needs no browser, no backend
// and no network.
//
// Run with:  npm run smoke

import { renderToStaticMarkup } from 'react-dom/server'

import App from '../src/App.jsx'
import Header from '../src/components/Header.jsx'
import TabNav from '../src/components/TabNav.jsx'
import EmailAnalyzer from '../src/components/EmailAnalyzer.jsx'
import DetectionCard from '../src/components/DetectionCard.jsx'
import SecurityAssessmentCard from '../src/components/SecurityAssessmentCard.jsx'
import ThreatSummary from '../src/components/ThreatSummary.jsx'
import DetectionSignals from '../src/components/DetectionSignals.jsx'
import DetectionEngines from '../src/components/DetectionEngines.jsx'
import SystemStatus from '../src/components/SystemStatus.jsx'
import AnalysisResults from '../src/components/AnalysisResults.jsx'
import Overview from '../src/components/Overview.jsx'
import MessageList from '../src/components/MessageList.jsx'
import DetectionBadges, { DetectionDetail } from '../src/components/DetectionBadges.jsx'

const noop = () => {}

// A response shaped exactly like POST /predict returns.
const phishingResponse = {
  spam_detection: {
    available: true, prediction: 'HAM', probability: 0.0412,
    confidence: 0.9588, model: 'Multinomial Naive Bayes + CountVectorizer',
  },
  phishing_detection: {
    available: true, prediction: 'PHISHING', probability: 0.9982,
    confidence: 0.9982, model: 'Fine-tuned BERT (bert-base-uncased)',
    truncated: false,
  },
  security_assessment: {
    risk_level: 'HIGH',
    reason: 'Flagged as phishing.',
    recommended_action: 'Quarantine and do not click any links.',
    method: 'rule-based', is_ml_prediction: false,
    triggered_by: { spam_detected: false, phishing_detected: true },
  },
  label: 'ham', prediction: 'ham', is_spam: false, confidence: 0.9588,
  explanation: 'This message looks legitimate (95.9% confidence).',
  top_signals: [{ term: 'verify', weight: 3.21, count: 1 }],
  stats: { characters: 120, words: 20, cleaned_words: 12, recognised_features: 9 },
}

const safeResponse = {
  ...phishingResponse,
  phishing_detection: { ...phishingResponse.phishing_detection, prediction: 'LEGITIMATE', probability: 0.0031 },
  security_assessment: {
    ...phishingResponse.security_assessment,
    risk_level: 'LOW', reason: 'Neither detector flagged this email.',
    recommended_action: 'Deliver normally.',
    triggered_by: { spam_detected: false, phishing_detected: false },
  },
}

const healthy = {
  status: 'healthy', spam_model: 'loaded', phishing_model: 'loaded',
  detectors: { spam: { loaded: true }, phishing: { loaded: true, device: 'cpu' } },
}
const degraded = {
  status: 'degraded', spam_model: 'loaded', phishing_model: 'not loaded',
  detectors: { spam: { loaded: true }, phishing: { loaded: false } },
}

const out = {}
const render = (name, element) => { out[name] = renderToStaticMarkup(element) }

render('App', <App />)
render('HeaderOnline', <Header connection="online" health={healthy} />)
render('HeaderOffline', <Header connection="offline" health={null} />)
render('HeaderDegraded', <Header connection="online" health={degraded} />)
render('TabNav', <TabNav active="analyzer" onChange={noop} counts={{ quarantine: 4, inbox: 7 }} />)
render('Analyzer', <EmailAnalyzer subject="" body="" onSubjectChange={noop} onBodyChange={noop} onSubmit={noop} onClear={noop} loading={false} />)
render('AnalyzerLoading', <EmailAnalyzer subject="" body="hello there" onSubjectChange={noop} onBodyChange={noop} onSubmit={noop} onClear={noop} loading />)
render('CardPhishing', <DetectionCard title="Phishing Detection" icon={null} result={phishingResponse.phishing_detection} threatLabel="PHISHING" modelName="BERT" emphasis />)
render('CardSpamSafe', <DetectionCard title="Spam Detection" icon={null} result={phishingResponse.spam_detection} threatLabel="SPAM" modelName="Naive Bayes" />)
render('CardUnavailable', <DetectionCard title="Phishing Detection" icon={null} result={{ available: false, error: 'model not loaded', model: 'BERT' }} threatLabel="PHISHING" />)
render('AssessHigh', <SecurityAssessmentCard assessment={phishingResponse.security_assessment} />)
render('AssessLow', <SecurityAssessmentCard assessment={safeResponse.security_assessment} />)
render('Summary', <ThreatSummary result={phishingResponse} />)
render('Signals', <DetectionSignals result={phishingResponse} />)
render('SignalsEmpty', <DetectionSignals result={{ spam_detection: {} }} />)
render('Engines', <DetectionEngines metrics={{ test_accuracy: 0.98, phishing: { phishing_recall: 0.9875, phishing_precision: 0.9959 } }} />)
render('StatusOk', <SystemStatus health={healthy} connection="online" onRetry={noop} />)
render('StatusOffline', <SystemStatus health={null} connection="offline" onRetry={noop} />)
render('StatusDegraded', <SystemStatus health={degraded} connection="online" onRetry={noop} />)
render('ResultsEmpty', <AnalysisResults result={null} loading={false} error="" />)
render('ResultsLoading', <AnalysisResults result={null} loading error="" />)
render('ResultsError', <AnalysisResults result={null} loading={false} error="The detection service is currently unavailable." onRetry={noop} />)
render('Results', <AnalysisResults result={phishingResponse} loading={false} error="" />)

// -- Overview + Quarantine phishing integration --------------------------

const statsWithPhishing = {
  total: 10, spam_count: 4, ham_count: 6, spam_rate: 0.4, ham_rate: 0.6,
  moved_count: 1, last_analysed: '2026-09-21T10:00:00',
  phishing_count: 3, legitimate_count: 5, phishing_analysed: 8,
  phishing_unknown: 2, phishing_rate: 0.375, legitimate_rate: 0.625,
  high_risk_count: 3, risk_counts: { HIGH: 3, MEDIUM: 2, LOW: 3 },
}

// An older backend that does not report phishing stats at all.
const statsLegacy = {
  total: 5, spam_count: 2, ham_count: 3, spam_rate: 0.4, ham_rate: 0.6,
  moved_count: 0, last_analysed: '2026-08-01T10:00:00',
}

// Four messages covering every spam x phishing combination, plus a legacy row.
const quarantineMessages = [
  { id: 'm1', timestamp: '2026-09-21T09:00:00', label: 'spam', confidence: 0.99,
    moved: false, text: 'Exclusive offer just for you!',
    phishing_available: true, phishing_label: 'PHISHING',
    phishing_confidence: 0.999, risk_level: 'HIGH' },
  { id: 'm2', timestamp: '2026-09-21T09:05:00', label: 'spam', confidence: 0.95,
    moved: false, text: '50% off winter sale',
    phishing_available: true, phishing_label: 'LEGITIMATE',
    phishing_confidence: 0.02, risk_level: 'MEDIUM' },
  { id: 'm3', timestamp: '2026-09-21T09:10:00', label: 'ham', confidence: 0.88,
    moved: false, text: 'Please confirm your password',
    phishing_available: true, phishing_label: 'PHISHING',
    phishing_confidence: 0.97, risk_level: 'HIGH' },
  { id: 'm4', timestamp: '2026-08-01T09:00:00', label: 'spam', confidence: 0.9,
    moved: false, text: 'Old message with no phishing metadata',
    phishing_available: false, phishing_label: null,
    phishing_confidence: null, risk_level: null },
]

render('OverviewPhishing', <Overview stats={statsWithPhishing} loading={false} onGoToClassifier={noop} />)
render('OverviewLegacy', <Overview stats={statsLegacy} loading={false} onGoToClassifier={noop} />)
render('OverviewEmpty', <Overview stats={{ total: 0 }} loading={false} onGoToClassifier={noop} />)
render('Quarantine', <MessageList box="quarantine" messages={quarantineMessages} loading={false} movingId={null} onMove={noop} onRefresh={noop} />)
render('QuarantineOpen', <MessageList box="quarantine" messages={quarantineMessages} loading={false} movingId={null} onMove={noop} onRefresh={noop} initialExpandedId="m3" />)
render('QuarantineLegacyOpen', <MessageList box="quarantine" messages={quarantineMessages} loading={false} movingId={null} onMove={noop} onRefresh={noop} initialExpandedId="m4" />)
render('Inbox', <MessageList box="inbox" messages={[quarantineMessages[1]]} loading={false} movingId={null} onMove={noop} onRefresh={noop} />)
render('BadgesHamPhishing', <DetectionBadges message={quarantineMessages[2]} />)
render('BadgesLegacy', <DetectionBadges message={quarantineMessages[3]} />)
render('DetailLegacy', <DetectionDetail message={quarantineMessages[3]} />)

let failures = 0
function check(name, condition, detail) {
  if (condition) {
    console.log(`ok    ${name}`)
  } else {
    failures += 1
    console.log(`FAIL  ${name}: ${detail}`)
  }
}

// -- branding & shell --
check('app title', out.App.includes('AI Email Threat Detection'), 'title missing')
check('app subtitle', out.App.includes('AI-powered email security analysis'), 'subtitle missing')
check('analyzer heading', out.App.includes('Analyze an Email'), 'heading missing')
check('empty state', out.App.includes('Ready to Analyze'), 'empty state missing')
check('nav has Analyzer', out.TabNav.includes('Analyzer'), 'tab missing')
check('nav has System Status', out.TabNav.includes('System Status'), 'tab missing')

// -- header status is driven by /health --
check('header operational', out.HeaderOnline.includes('System Operational'), 'missing')
check('header unreachable', out.HeaderOffline.includes('API Unreachable'), 'missing')
check('header degraded', out.HeaderDegraded.includes('Degraded'), 'missing')

// -- analyzer --
check('subject field', out.Analyzer.includes('email-subject'), 'missing')
check('body field', out.Analyzer.includes('email-body'), 'missing')
check('char counter', out.Analyzer.includes('characters'), 'missing')
check('clear button', out.Analyzer.includes('Clear'), 'missing')
check('cta', out.Analyzer.includes('Analyze Email'), 'missing')
check('loading label', out.AnalyzerLoading.includes('Analyzing'), 'missing')
check('submit disabled when empty', out.Analyzer.includes('disabled'), 'button should be disabled')

// -- detection cards --
check('phishing verdict', out.CardPhishing.includes('PHISHING'), 'missing')
check('phishing threat styling', out.CardPhishing.includes('dcard--threat'), 'missing')
check('phishing emphasis', out.CardPhishing.includes('dcard--emphasis'), 'missing')
check('phishing confidence', out.CardPhishing.includes('99.8%'), 'missing')
check('phishing model name', out.CardPhishing.includes('BERT'), 'missing')
check('spam safe styling', out.CardSpamSafe.includes('dcard--safe'), 'missing')
check('spam verdict', out.CardSpamSafe.includes('HAM'), 'missing')
check('unavailable detector', out.CardUnavailable.includes('unavailable'), 'missing')

// -- assessment must never look like an ML output --
check('risk HIGH', out.AssessHigh.includes('HIGH'), 'missing')
check('risk LOW', out.AssessLow.includes('LOW'), 'missing')
check('labelled rule-based', out.AssessHigh.includes('Rule-based'), 'missing')
check('states not ML', out.AssessHigh.includes('not a machine-learning prediction'), 'missing')
check('reason shown', out.AssessHigh.includes('Flagged as phishing'), 'missing')
check('action shown', out.AssessHigh.includes('Quarantine'), 'missing')

// -- summary --
check('summary title', out.Summary.includes('Email Analysis Summary'), 'missing')
check('summary spam row', out.Summary.includes('Spam Status'), 'missing')
check('summary phishing row', out.Summary.includes('Phishing Status'), 'missing')
check('summary risk row', out.Summary.includes('Risk Level'), 'missing')

// -- signals: shown when present, hidden when not --
check('signals heading', out.Signals.includes('Why was this flagged?'), 'missing')
check('signal term', out.Signals.includes('verify'), 'missing')
check('signals hidden when empty', out.SignalsEmpty === '', 'should render nothing')

// -- engines --
check('engines heading', out.Engines.includes('Detection Engines'), 'missing')
check('engines spam tech', out.Engines.includes('Naive Bayes + CountVectorizer'), 'missing')
check('engines bert tech', out.Engines.includes('BERT fine-tuned classifier'), 'missing')

// -- system status --
check('status api row', out.StatusOk.includes('API'), 'missing')
check('status operational', out.StatusOk.includes('Operational'), 'missing')
check('status both loaded', (out.StatusOk.match(/Loaded/g) || []).length >= 2, 'expected 2 loaded rows')
check('status offline warning', out.StatusOffline.includes('Cannot reach the backend'), 'missing')
check('status degraded warning', out.StatusDegraded.includes('degraded'), 'missing')

// -- result states --
check('results empty', out.ResultsEmpty.includes('Ready to Analyze'), 'missing')
check('results loading', out.ResultsLoading.includes('Analyzing email'), 'missing')
check('results loading copy', out.ResultsLoading.includes('Detection engines are evaluating'), 'missing')
check('results error', out.ResultsError.includes('Unable to analyze email'), 'missing')
check('results full', out.Results.includes('Security Analysis Results'), 'missing')
check('no fake percentage', !out.ResultsLoading.includes('%'), 'loading must not fake progress')

// -- Overview: phishing as an independent dimension --
check('overview keeps spam chart', out.OverviewPhishing.includes('Spam vs ham'), 'missing')
check('overview adds phishing chart', out.OverviewPhishing.includes('Phishing vs legitimate'), 'missing')
check('overview phishing section', out.OverviewPhishing.includes('Phishing detection'), 'missing')
check('overview phishing count', out.OverviewPhishing.includes('>3<'), 'phishing_count missing')
check('overview legitimate count', out.OverviewPhishing.includes('>5<'), 'legitimate_count missing')
check('overview flags unanalysed', out.OverviewPhishing.includes('stored before'), 'legacy note missing')
check('overview explains independence', out.OverviewPhishing.includes('independently of spam'), 'missing')
check('overview degrades on old backend',
  !out.OverviewLegacy.includes('Phishing vs legitimate'), 'should hide phishing chart')
check('overview old backend keeps spam', out.OverviewLegacy.includes('Spam vs ham'), 'missing')
check('overview empty state', out.OverviewEmpty.includes('No detections yet'), 'missing')

// -- Quarantine: reframed, filtered, badged --
check('quarantine reframed', out.Quarantine.includes('requiring security review'), 'copy not updated')
check('quarantine filter All', out.Quarantine.includes('>All<'), 'missing')
check('quarantine filter Spam', out.Quarantine.includes('>Spam<'), 'missing')
check('quarantine filter Phishing', out.Quarantine.includes('>Phishing<'), 'missing')
check('quarantine filter High Risk', out.Quarantine.includes('High Risk'), 'missing')
check('inbox has no filters', !out.Inbox.includes('filters'), 'filters should be quarantine-only')

// -- Badges: separate detectors, never inferred --
check('spam badge', out.Quarantine.includes('>SPAM<'), 'missing')
check('phishing badge', out.Quarantine.includes('>PHISHING<'), 'missing')
check('legitimate badge', out.Quarantine.includes('>LEGITIMATE<'), 'missing')
check('high risk badge', out.Quarantine.includes('HIGH RISK'), 'missing')
check('ham+phishing shows both', out.BadgesHamPhishing.includes('>HAM<') && out.BadgesHamPhishing.includes('>PHISHING<'),
  'HAM and PHISHING must both appear on one message')
check('legacy shows N/A badge', out.BadgesLegacy.includes('PHISHING N/A'), 'missing')
check('legacy invents no verdict',
  !out.BadgesLegacy.includes('>PHISHING<') && !out.BadgesLegacy.includes('>LEGITIMATE<'),
  'must not fabricate a phishing verdict')

// -- Expanded detail --
check('detail names Naive Bayes', out.QuarantineOpen.includes('Naive Bayes'), 'missing')
check('detail names BERT', out.QuarantineOpen.includes('BERT'), 'missing')
check('detail labels rule-based', out.QuarantineOpen.includes('Rule-based assessment'), 'missing')
check('detail says model confidence', out.QuarantineOpen.includes('model confidence'), 'missing')
check('detail avoids malicious wording',
  !out.QuarantineOpen.toLowerCase().includes('probability the email is malicious'), 'bad wording')
check('legacy detail message', out.DetailLegacy.includes('Phishing analysis unavailable for this message'), 'missing')

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`)
process.exit(failures === 0 ? 0 : 1)
