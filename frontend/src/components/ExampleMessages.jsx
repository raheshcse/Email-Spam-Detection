import { EXAMPLE_MESSAGES } from '../examples.js'

export default function ExampleMessages({ onSelect, disabled, activeId }) {
  return (
    <section className="card panel">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">Try an example</h2>
          <p className="panel__hint">
            Click any sample to load it into the box above.
          </p>
        </div>
      </div>

      <div className="examples">
        {EXAMPLE_MESSAGES.map((example) => (
          <button
            key={example.id}
            type="button"
            className={`example ${activeId === example.id ? 'example--active' : ''}`}
            onClick={() => onSelect(example)}
            disabled={disabled}
          >
            <span className={`example__tag example__tag--${example.expected}`}>
              {example.label}
            </span>
            <span className="example__preview">{example.preview}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
