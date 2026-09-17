import { ChartIcon, InboxIcon, ScanIcon, ShieldSmallIcon } from './icons/StatusIcons.jsx'

export const TABS = [
  { id: 'classifier', label: 'Classifier', Icon: ScanIcon },
  { id: 'overview', label: 'Overview', Icon: ChartIcon },
  { id: 'quarantine', label: 'Quarantine', Icon: ShieldSmallIcon },
  { id: 'inbox', label: 'Inbox', Icon: InboxIcon },
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
