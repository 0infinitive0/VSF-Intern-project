import { useState } from 'react'
import { Spinner } from './spinner'

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  /** Background refetch in flight (e.g. jumping pages) -- keeps the current
   * rows on screen instead of remounting into a full skeleton, so this is
   * the only feedback the user gets that a new page is loading. */
  loading?: boolean
}

type PageToken = number | 'ellipsis'

/** First, last, and a window around the current page, with '…' filling gaps. */
function pageTokens(page: number, pageCount: number): PageToken[] {
  const shown = new Set<number>([1, pageCount])
  for (let p = page - 1; p <= page + 1; p++) {
    if (p >= 1 && p <= pageCount) shown.add(p)
  }
  const sorted = [...shown].sort((a, b) => a - b)
  const tokens: PageToken[] = []
  let prev = 0
  for (const p of sorted) {
    if (prev && p - prev > 1) tokens.push('ellipsis')
    tokens.push(p)
    prev = p
  }
  return tokens
}

export function Pagination({ page, pageSize, total, onPageChange, loading }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  const [goTo, setGoTo] = useState('')

  function submitGoTo() {
    const n = Math.trunc(Number(goTo))
    if (Number.isFinite(n) && n >= 1 && n <= pageCount) onPageChange(n)
    setGoTo('')
  }

  return (
    <div className="pagination">
      <span className="tabular-nums" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {loading && <Spinner />}
        {from}–{to} / {total}
      </span>
      <button
        type="button"
        className="pagination__btn"
        disabled={loading || page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Trang trước"
      >
        ‹
      </button>
      {pageTokens(page, pageCount).map((token, i) =>
        token === 'ellipsis' ? (
          <span key={`e${i}`} className="pagination__ellipsis">
            …
          </span>
        ) : (
          <button
            key={token}
            type="button"
            className="pagination__btn pagination__btn--page"
            data-active={token === page || undefined}
            aria-current={token === page ? 'page' : undefined}
            aria-label={`Trang ${token}`}
            disabled={loading}
            onClick={() => onPageChange(token)}
          >
            {token}
          </button>
        ),
      )}
      <button
        type="button"
        className="pagination__btn"
        disabled={loading || page >= pageCount}
        onClick={() => onPageChange(page + 1)}
        aria-label="Trang sau"
      >
        ›
      </button>
      <form
        className="pagination__goto"
        onSubmit={(e) => {
          e.preventDefault()
          submitGoTo()
        }}
      >
        <span>Đến trang</span>
        <input
          className="input pagination__goto-input"
          type="number"
          min={1}
          max={pageCount}
          value={goTo}
          onChange={(e) => setGoTo(e.target.value)}
          placeholder={String(page)}
          aria-label="Đến trang số"
          disabled={loading}
        />
      </form>
    </div>
  )
}
