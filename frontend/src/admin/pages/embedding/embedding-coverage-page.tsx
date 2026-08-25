import { useEffect, useState } from 'react'
import { getEmbeddingMissing, getEmbeddingSummary, type EmbeddingSummaryResponse } from '../../api/embedding-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { ErrorState } from '../../ui/error-state'
import { SkeletonTable } from '../../ui/skeleton-table'
import { EmbeddingMissingTable, type MissingRow } from './embedding-missing-table'
import { EmbeddingTableCards } from './embedding-table-cards'

type SummaryState = { status: 'loading' } | { status: 'loaded'; data: EmbeddingSummaryResponse } | { status: 'error'; detail: string }
type MissingState = { status: 'loading' } | { status: 'loaded'; rows: MissingRow[] } | { status: 'error' }

interface EmbeddingCoveragePageProps {
  navigate: (to: string) => void
}

/** embedding-coverage-page.tsx — C4 (phase-12-embedding-status.md). No
 * artboard of its own: top cards reuse A2's `Pipeline embedding` card
 * shape, the banner copy is lifted from A2 verbatim for the common
 * rooms-only case and generalized (documented below) when hotels/địa điểm
 * also have gaps -- the design never shows that combination. */
export function EmbeddingCoveragePage({ navigate }: EmbeddingCoveragePageProps) {
  const [summary, setSummary] = useState<SummaryState>({ status: 'loading' })
  const [missing, setMissing] = useState<MissingState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    getEmbeddingSummary().then((result) => {
      if (cancelled) return
      if (!result.ok) return setSummary({ status: 'error', detail: result.detail })
      setSummary({ status: 'loaded', data: result.data })
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (summary.status !== 'loaded' || summary.data.total_missing === 0) {
      setMissing({ status: 'loaded', rows: [] })
      return
    }
    let cancelled = false
    const tablesWithGaps = summary.data.tables.filter((t) => t.missing > 0)
    Promise.all(tablesWithGaps.map((t) => getEmbeddingMissing(t.table, 20)))
      .then((results) => {
        if (cancelled) return
        if (results.some((r) => !r.ok)) return setMissing({ status: 'error' })
        const rows: MissingRow[] = results.flatMap((result, i) => {
          if (!result.ok) return []
          const table = tablesWithGaps[i]
          return result.data.items.map((item) => ({
            table: table.table,
            tableLabel: table.label,
            id: item.id,
            name: item.name,
            hotel_name: item.hotel_name ?? null,
            updated_at: item.updated_at ?? null,
          }))
        })
        rows.sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
        setMissing({ status: 'loaded', rows: rows.slice(0, 20) })
      })
      .catch(() => {
        if (!cancelled) setMissing({ status: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [summary])

  return (
    <>
      <PageHeader breadcrumb="Quản trị · Dữ liệu bot" title="Độ phủ embedding" />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
        {summary.status === 'loading' && <SkeletonTable rows={1} columnWidths={[200, 200, 200]} />}

        {summary.status === 'error' && <ErrorState description={summary.detail} />}

        {summary.status === 'loaded' && (
          <>
            <EmbeddingTableCards tables={summary.data.tables} />

            {summary.data.total_missing > 0 && (
              <Banner tone="warn">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <span>{missingBannerText(summary.data.tables)}</span>
                  <Button variant="secondary" size="sm" onClick={() => navigate('/admin/pipelines')}>
                    Chạy pipeline embedding
                  </Button>
                </div>
              </Banner>
            )}

            {summary.data.total_missing > 0 && missing.status === 'loaded' && missing.rows.length > 0 && (
              <div className="card" style={{ overflow: 'hidden' }}>
                <div style={{ overflowX: 'auto' }}>
                  <EmbeddingMissingTable rows={missing.rows} />
                </div>
              </div>
            )}

            {summary.data.total_missing > 0 && missing.status === 'error' && (
              <Banner tone="err">Không tải được danh sách bản ghi thiếu embedding. Số liệu tổng ở trên vẫn đúng.</Banner>
            )}
          </>
        )}
      </div>
    </>
  )
}

/** A2's exact sentence ("{n} phòng chưa có embedding — bot sẽ không gợi ý
 * được các phòng này.") only covers rooms -- the one gap the design ever
 * shows. Generalized here to list every table with a gap, since hotels and
 * attractions can be missing too; single-table case still reads identically
 * to the design when that table is rooms. */
function missingBannerText(tables: EmbeddingSummaryResponse['tables']): string {
  const gaps = tables.filter((t) => t.missing > 0)
  if (gaps.length === 1 && gaps[0].table === 'rooms') {
    return `${gaps[0].missing} phòng chưa có embedding — bot sẽ không gợi ý được các phòng này.`
  }
  const parts = gaps.map((t) => `${t.missing} ${t.label.toLowerCase()}`)
  return `${parts.join(', ')} chưa có embedding — bot sẽ không gợi ý được những mục này.`
}
