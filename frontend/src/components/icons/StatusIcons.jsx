const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.9,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
}

export function AlertIcon({ size = 26 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M12 3.6 2.8 19.4h18.4L12 3.6Z" />
      <path d="M12 9.6v4.2" />
      <path d="M12 16.8h.01" />
    </svg>
  )
}

export function CheckIcon({ size = 26 }) {
  return (
    <svg width={size} height={size} {...base}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.3 12.2 2.6 2.6 4.8-5.2" />
    </svg>
  )
}

export function TrashIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M4 6.5h16" />
      <path d="M9.5 6.5V4.8h5v1.7" />
      <path d="M6.4 6.5 7.3 20h9.4l.9-13.5" />
    </svg>
  )
}

export function ChartIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M4 20V4" />
      <path d="M4 20h16" />
      <rect x="7.5" y="12" width="3.2" height="5" rx="0.8" />
      <rect x="13.3" y="7.5" width="3.2" height="9.5" rx="0.8" />
    </svg>
  )
}

export function ShieldSmallIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M12 3 5 5.8v5.1c0 4.2 2.9 8.2 7 9.6 4.1-1.4 7-5.4 7-9.6V5.8L12 3Z" />
      <path d="M12 9v3.4" />
      <path d="M12 15.4h.01" />
    </svg>
  )
}

export function InboxIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M3.5 13.2 6 5.2h12l2.5 8" />
      <path d="M3.5 13.2h4.2l1.1 2.5h6.4l1.1-2.5h4.2v4.2a1.6 1.6 0 0 1-1.6 1.6H5.1a1.6 1.6 0 0 1-1.6-1.6v-4.2Z" />
    </svg>
  )
}

export function ArrowMoveIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M4 8.5h13" />
      <path d="m13.5 5 3.5 3.5-3.5 3.5" />
      <path d="M20 15.5H7" />
      <path d="M10.5 19 7 15.5 10.5 12" />
    </svg>
  )
}

export function ChevronIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="m7.5 10 4.5 4.5L16.5 10" />
    </svg>
  )
}

export function ScanIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base}>
      <path d="M3.5 8.2V5.4a1.9 1.9 0 0 1 1.9-1.9h2.8" />
      <path d="M15.8 3.5h2.8a1.9 1.9 0 0 1 1.9 1.9v2.8" />
      <path d="M20.5 15.8v2.8a1.9 1.9 0 0 1-1.9 1.9h-2.8" />
      <path d="M8.2 20.5H5.4a1.9 1.9 0 0 1-1.9-1.9v-2.8" />
      <path d="M3.5 12h17" />
    </svg>
  )
}
