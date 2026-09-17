// Hand-rolled SVG bar chart. Deliberately dependency-free: the Overview only
// needs two bars, so pulling in a charting library would be overkill.

const WIDTH = 520
const HEIGHT = 240
const PAD_LEFT = 44
const PAD_BOTTOM = 34
const PAD_TOP = 18

function niceCeiling(value) {
  if (value <= 5) return 5
  const magnitude = 10 ** Math.floor(Math.log10(value))
  return Math.ceil(value / magnitude) * magnitude
}

export default function BarChart({ data }) {
  const max = niceCeiling(Math.max(...data.map((d) => d.value), 1))
  const plotWidth = WIDTH - PAD_LEFT - 16
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM
  const slot = plotWidth / data.length
  const barWidth = Math.min(96, slot * 0.5)

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    value: Math.round(max * fraction),
    y: PAD_TOP + plotHeight - plotHeight * fraction,
  }))

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={data.map((d) => `${d.label}: ${d.value}`).join(', ')}
        className="chart__svg"
      >
        {ticks.map((tick) => (
          <g key={tick.value + '-' + tick.y}>
            <line
              x1={PAD_LEFT}
              x2={WIDTH - 16}
              y1={tick.y}
              y2={tick.y}
              className="chart__grid"
            />
            <text x={PAD_LEFT - 10} y={tick.y + 4} className="chart__tick">
              {tick.value}
            </text>
          </g>
        ))}

        {data.map((item, index) => {
          const height = max ? (item.value / max) * plotHeight : 0
          const x = PAD_LEFT + slot * index + (slot - barWidth) / 2
          const y = PAD_TOP + plotHeight - height

          return (
            <g key={item.label}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(height, item.value > 0 ? 3 : 0)}
                rx="6"
                className={`chart__bar chart__bar--${item.tone}`}
                style={{ animationDelay: `${index * 120}ms` }}
              />
              <text
                x={x + barWidth / 2}
                y={y - 9}
                textAnchor="middle"
                className={`chart__value chart__value--${item.tone}`}
              >
                {item.value}
              </text>
              <text
                x={x + barWidth / 2}
                y={HEIGHT - 11}
                textAnchor="middle"
                className="chart__label"
              >
                {item.label}
              </text>
            </g>
          )
        })}

        <line
          x1={PAD_LEFT}
          x2={WIDTH - 16}
          y1={PAD_TOP + plotHeight}
          y2={PAD_TOP + plotHeight}
          className="chart__axis"
        />
      </svg>
    </div>
  )
}
