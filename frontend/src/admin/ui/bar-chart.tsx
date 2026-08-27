import type { ReactNode } from 'react'

export interface Bar {
  label: string
  value: number
  /** Overrides `accent` for this one bar. */
  color?: string
  /** Small caption under the label (vertical) / not shown (horizontal). */
  sublabel?: ReactNode
}

interface BarChartProps {
  bars: Bar[]
  orientation?: 'vertical' | 'horizontal'
  /** Formats the per-bar value caption (default: `toLocaleString('vi-VN')`). */
  formatValue?: (value: number) => string
  /** Plot area in px — bar track height (vertical) / row count is free (horizontal). */
  height?: number
  /** Default bar fill; pass a `var(--…)` token. */
  accent?: string
}

/** bar-chart.tsx — dependency-free bar chart (no charting lib in the admin
 * bundle), CSS box model rather than SVG so bars reflow with the card. All
 * bars scale to the largest value; a zero-valued bar still shows a 2px stub
 * so the axis reads as "nothing here", not "missing". */
export function BarChart({
  bars,
  orientation = 'vertical',
  formatValue = (value) => value.toLocaleString('vi-VN'),
  height = 132,
  accent = 'var(--ok)',
}: BarChartProps) {
  const max = bars.reduce((m, b) => Math.max(m, b.value), 0)
  const pct = (v: number) => (max > 0 ? Math.max(v > 0 ? 2 : 0, (v / max) * 100) : 0)

  if (orientation === 'horizontal') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {bars.map((b, i) => (
          <div key={`${b.label}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
            <div
              title={b.label}
              style={{ width: 128, flexShrink: 0, color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {b.label}
            </div>
            <div style={{ flex: 1, minWidth: 0, height: 10, background: 'var(--stroke)', borderRadius: 999, overflow: 'hidden' }}>
              <div style={{ width: `${pct(b.value)}%`, height: '100%', background: b.color ?? accent, borderRadius: 999 }} />
            </div>
            <div className="tabular-nums" style={{ width: 92, flexShrink: 0, textAlign: 'right', fontWeight: 600 }}>
              {formatValue(b.value)}
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
      {bars.map((b, i) => (
        <div key={`${b.label}-${i}`} style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div className="tabular-nums" style={{ fontSize: 10.5, color: 'var(--t4)', whiteSpace: 'nowrap' }}>
            {formatValue(b.value)}
          </div>
          <div style={{ width: '100%', height, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
            <div style={{ width: '68%', height: `${pct(b.value)}%`, background: b.color ?? accent, borderRadius: '5px 5px 0 0' }} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>
            {b.label}
          </div>
          {b.sublabel != null && <div style={{ fontSize: 10, color: 'var(--t4)' }}>{b.sublabel}</div>}
        </div>
      ))}
    </div>
  )
}
