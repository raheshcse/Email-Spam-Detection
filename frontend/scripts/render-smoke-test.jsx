// Offline render smoke test: mounts the whole App with fetch stubbed out,
// so we can prove the components render and show the right values without
// needing a browser.
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../src/App.jsx'
import ResultCard from '../src/components/ResultCard.jsx'
import ResultPlaceholder from '../src/components/ResultPlaceholder.jsx'
import HowItWorks from '../src/components/HowItWorks.jsx'
import ErrorBanner from '../src/components/ErrorBanner.jsx'
import TabNav from '../src/components/TabNav.jsx'
import Overview from '../src/components/Overview.jsx'
import BarChart from '../src/components/BarChart.jsx'
import MessageList from '../src/components/MessageList.jsx'

// Run with:  npm run smoke

const spam = {
  label: 'spam', prediction: 'spam', is_spam: true,
  confidence: 0.9987, confidence_percent: 99.87, confidence_band: 'high',
  probabilities: { ham: 0.0013, spam: 0.9987 },
  explanation: 'This message looks like spam (99.9% confidence).',
  top_signals: [{ term: 'prize', weight: 4.93, count: 1 }, { term: 'claim', weight: 5.29, count: 1 }],
  cleaned_text: 'prize claim', stats: { characters: 120, words: 21, cleaned_words: 10, recognised_features: 11 },
  quarantined: true,
}
const ham = { ...spam, label: 'ham', prediction: 'ham', is_spam: false,
  probabilities: { ham: 0.9178, spam: 0.0822 }, confidence: 0.9178,
  explanation: 'This message looks legitimate (91.8% confidence).',
  top_signals: [{ term: 'dinner', weight: 2.58, count: 1 }], quarantined: false }

const out = []
out.push(['App shell', renderToStaticMarkup(<App />)])
out.push(['ResultCard spam', renderToStaticMarkup(<ResultCard result={spam} />)])
out.push(['ResultCard ham', renderToStaticMarkup(<ResultCard result={ham} />)])
out.push(['Placeholder loading', renderToStaticMarkup(<ResultPlaceholder loading />)])
out.push(['Placeholder empty', renderToStaticMarkup(<ResultPlaceholder loading={false} />)])
out.push(['HowItWorks', renderToStaticMarkup(<HowItWorks metrics={null} />)])
out.push(['ErrorBanner', renderToStaticMarkup(<ErrorBanner message="Backend offline" onDismiss={() => {}} onRetry={() => {}} />)])

const noop = () => {}
const stats = { spam_count: 12, ham_count: 8, total: 20, spam_rate: 0.6, ham_rate: 0.4, moved_count: 3, last_analysed: '2026-08-11T01:43:07' }
const rows = [
  { id: 'abc123456789', timestamp: '2026-08-11T01:43:07', label: 'spam', confidence: 0.9987, moved: false, text: 'WINNER!! Claim your free prize now.' },
  { id: 'def987654321', timestamp: '2026-08-10T09:12:00', label: 'spam', confidence: null, moved: true, text: 'URGENT! Text WIN to 80086.' },
]

out.push(['TabNav', renderToStaticMarkup(<TabNav active="overview" onChange={noop} counts={{ quarantine: 12, inbox: 8 }} />)])
out.push(['Overview', renderToStaticMarkup(<Overview stats={stats} loading={false} onGoToClassifier={noop} />)])
out.push(['Overview empty', renderToStaticMarkup(<Overview stats={{ total: 0 }} loading={false} onGoToClassifier={noop} />)])
out.push(['BarChart', renderToStaticMarkup(<BarChart data={[{ label: 'Spam', value: 12, tone: 'spam' }, { label: 'Ham', value: 8, tone: 'ham' }]} />)])
out.push(['Quarantine', renderToStaticMarkup(<MessageList box="quarantine" messages={rows} loading={false} movingId={null} onMove={noop} onRefresh={noop} initialExpandedId="abc123456789" />)])
out.push(['Inbox empty', renderToStaticMarkup(<MessageList box="inbox" messages={[]} loading={false} movingId={null} onMove={noop} onRefresh={noop} />)])

let failures = 0
function assert(name, cond, detail) {
  if (!cond) { failures++; console.log(`FAIL  ${name}: ${detail}`) }
  else console.log(`ok    ${name}`)
}

const byName = Object.fromEntries(out)
assert('App renders title', byName['App shell'].includes('Email Spam Detection Agent'), 'title missing')
assert('App renders Analyse button', byName['App shell'].includes('Analyse Email'), 'button missing')
assert('App renders examples', byName['App shell'].includes('Prize scam'), 'examples missing')
assert('App renders How it works', byName['App shell'].includes('How it works'), 'section missing')
assert('Spam card red styling', byName['ResultCard spam'].includes('result--spam'), 'modifier missing')
assert('Spam card verdict', byName['ResultCard spam'].includes('>Spam<'), 'verdict missing')
assert('Spam card confidence', byName['ResultCard spam'].includes('99.9%'), 'confidence missing')
assert('Spam card signals', byName['ResultCard spam'].includes('prize'), 'signals missing')
assert('Ham card green styling', byName['ResultCard ham'].includes('result--ham'), 'modifier missing')
assert('Ham card verdict', byName['ResultCard ham'].includes('>Ham<'), 'verdict missing')
assert('Ham card confidence', byName['ResultCard ham'].includes('91.8%'), 'confidence missing')
assert('Loading skeleton', byName['Placeholder loading'].includes('skeleton'), 'skeleton missing')
assert('Empty state', byName['Placeholder empty'].includes('No analysis yet'), 'empty missing')
assert('Metrics 98/96/90', ['98%','96%','90%'].every(v => byName['HowItWorks'].includes(v)), 'metrics missing')
assert('Error banner', byName['ErrorBanner'].includes('Backend offline'), 'error missing')

assert('App renders 4 tabs', ['Classifier','Overview','Quarantine','Inbox'].every(t => byName['App shell'].includes(t)), 'tabs missing')
assert('TabNav counts', byName['TabNav'].includes('>12<') && byName['TabNav'].includes('>8<'), 'counts missing')
assert('TabNav active state', byName['TabNav'].includes('tab--active'), 'active tab missing')
assert('Overview counters', ['>20<','>12<','>8<','>3<'].every(v => byName['Overview'].includes(v)), 'counters missing')
assert('Overview spam rate', byName['Overview'].includes('60%'), 'spam rate missing')
assert('Overview empty state', byName['Overview empty'].includes('No detections yet'), 'empty missing')
assert('BarChart bars', byName['BarChart'].includes('chart__bar--spam') && byName['BarChart'].includes('chart__bar--ham'), 'bars missing')
assert('BarChart values', byName['BarChart'].includes('>12<') && byName['BarChart'].includes('>8<'), 'values missing')
assert('Quarantine rows', byName['Quarantine'].includes('WINNER!! Claim your free prize now.'), 'row missing')
assert('Quarantine move label', byName['Quarantine'].includes('Not spam, move to Inbox'), 'move action missing')
assert('Quarantine moved badge', byName['Quarantine'].includes('Manually moved'), 'badge missing')
assert('Quarantine count pill', byName['Quarantine'].includes('2 messages'), 'pill missing')
assert('Inbox empty state', byName['Inbox empty'].includes('Inbox is empty'), 'empty missing')

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`)
process.exit(failures === 0 ? 0 : 1)
