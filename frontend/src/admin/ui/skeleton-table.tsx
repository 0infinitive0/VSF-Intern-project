interface SkeletonTableProps {
  rows?: number
  columnWidths?: number[]
}

const DEFAULT_COLUMN_WIDTHS = [90, 150, 70]

export function SkeletonTable({ rows = 6, columnWidths = DEFAULT_COLUMN_WIDTHS }: SkeletonTableProps) {
  return (
    <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          height: 44,
          flex: 'none',
          borderBottom: '1px solid var(--stroke)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 14px',
          gap: 12,
        }}
      >
        {columnWidths.map((w, i) => (
          <div key={i} className="skeleton-bar" style={{ width: w, height: 9 }} />
        ))}
        <div style={{ flex: 1 }} />
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            height: 46,
            flex: 'none',
            borderBottom: '1px solid var(--line)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 14px',
            gap: 12,
          }}
        >
          {columnWidths.map((w, j) => (
            <div key={j} className="skeleton-bar" style={{ width: w, height: 9 }} />
          ))}
          <div style={{ flex: 1 }} />
        </div>
      ))}
    </div>
  )
}
