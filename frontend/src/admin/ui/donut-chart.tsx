import type { ReactNode } from 'react'

export interface DonutSegment {
  label: string
  value: number
  /** Any CSS color -- pass a `var(--…)` token to stay theme-aligned. */
  color: string
}

interface DonutChartProps {
  segments: DonutSegment[]
  /** Outer diameter in px (default 132). */
  size?: number
  /** Ring thickness in px (default 18). */
  thickness?: number
  /** Big number / text stacked in the hole. */
  centerLabel?: ReactNode
  /** Small caption under `centerLabel`. */
  centerSub?: ReactNode
  /** Show the label · value legend beside the ring (default true). */
  legend?: boolean
  /** Format each legend value (default: `toLocaleString('vi-VN')`). */
  formatValue?: (value: number) => string
}

/** donut-chart.tsx — dependency-free hollow pie chart (the admin bundle
 * carries no charting lib). One `<circle>` per segment, offset around the
 * track with `stroke-dasharray` + `stroke-dashoffset`, rotated -90° so the
 * first segment starts at 12 o'clock. Zero-total renders just the empty
 * track so a still-loading or genuinely-empty card doesn't throw. */
export function DonutChart({
  segments,
  size = 132,
  thickness = 18,
  centerLabel,
  centerSub,
  legend = true,
  formatValue = (value) => value.toLocaleString('vi-VN'),
}: DonutChartProps) {
  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0)

  let offset = 0
  const arcs = segments.map((seg) => {
    const fraction = total > 0 ? Math.max(0, seg.value) / total : 0
    const dash = fraction * circumference
    const arc = { ...seg, dash, gap: circumference - dash, rotation: offset }
    offset += dash
    return arc
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--stroke)"
            strokeWidth={thickness}
          />
          {arcs.map((arc, i) => (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={thickness}
              strokeLinecap="butt"
              strokeDasharray={`${arc.dash} ${arc.gap}`}
              strokeDashoffset={-arc.rotation}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          ))}
        </svg>
        {(centerLabel != null || centerSub != null) && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 2,
            }}
          >
            {centerLabel != null && (
              <div className="tabular-nums" style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-.02em' }}>
                {centerLabel}
              </div>
            )}
            {centerSub != null && <div style={{ fontSize: 11, color: 'var(--t4)' }}>{centerSub}</div>}
          </div>
        )}
      </div>

      {legend && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          {segments.map((seg) => (
            <div key={seg.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: seg.color, flexShrink: 0 }} />
              <span style={{ color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {seg.label}
              </span>
              <span className="tabular-nums" style={{ marginLeft: 'auto', fontWeight: 600 }}>
                {formatValue(seg.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
