/**
 * Primary navigation.
 *
 * Analyzer and System Status are the two views this phase specified. The
 * mailbox views (Quarantine, Inbox, Overview) are retained because they are
 * backed by live endpoints (/messages, /stats) and still work; removing them
 * would delete working functionality that was not asked to be removed.
 */
import {
  ChartIcon,
  InboxIcon,
  ScanIcon,
  ServerIcon,
  ShieldSmallIcon,
} from './icons/StatusIcons.jsx'

export const TABS = [
  { id: 'analyzer', label: 'Analyzer', Icon: ScanIcon },
  { id: 'quarantine', label: 'Quarantine', Icon: ShieldSmallIcon },
  { id: 'inbox', label: 'Inbox', Icon: InboxIcon },
  { id: 'overview', label: 'Overview', Icon: ChartIcon },
  { id: 'status', label: 'System Status', Icon: ServerIcon },
]

export default function TabNav({ active, onChange, counts }) {
  return (
    <nav className="tabs" role="tablist" aria-label="Dashboard sections">
      {TABS.map(({ id, label, Icon }) => {
        const count = counts?.[id]
        const isActive = active === id

        return (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={isActive}
            aria-controls={`panel-${id}`}
            className={`tab ${isActive ? 'tab--active' : ''}`}
            onClick={() => onChange(id)}
          >
            <span className="tab__icon" aria-hidden="true">
              <Icon />
            </span>
            <span className="tab__label">{label}</span>
            {typeof count === 'number' ? (
              <span className={`tab__count tab__count--${id}`}>{count}</span>
            ) : null}
          </button>
        )
      })}
    </nav>
  )
}
