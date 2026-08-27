import type { EmbeddingTableSummary } from '../../api/embedding-client'

function formatInt(value: number): string {
  return value.toLocaleString('vi-VN')
}

/** embedding-table-cards.tsx — C4's three top cards (phase-12-embedding-
 * status.md), one per embedded table. Reuses A2/C2's `bigNum` styling
 * (26px/700/tabular-nums) rather than inventing a new number treatment. */
export function EmbeddingTableCards({ tables }: { tables: EmbeddingTableSummary[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
      {tables.map((t) => {
        const hasMissing = t.missing > 0
        // Stale rows are a subset of `embedded` (they still have a vector),
        // so they never move the N/total headline -- they get their own
        // accent-blue line below the missing count, keeping the two apart:
        // one costs freshness, the other costs coverage.
        const staleCount = t.stale
        return (
          <div
            key={t.table}
            className="card"
            style={{
              padding: 16,
              borderRadius: 16,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              boxShadow: hasMissing ? 'inset 3px 0 0 var(--warn)' : undefined,
            }}
          >
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>{t.label}</div>
            <div className="tabular-nums" style={{ fontSize: 26, fontWeight: 700 }}>
              {formatInt(t.embedded)} / {formatInt(t.total)}
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: hasMissing ? 'var(--warn-ink)' : 'var(--ok-ink)' }}>
              {hasMissing ? `${formatInt(t.missing)} chưa embed` : '✓ Đủ'}
            </div>
            {staleCount > 0 && (
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>{formatInt(staleCount)} cần chạy lại</div>
            )}
          </div>
        )
      })}
    </div>
  )
}
