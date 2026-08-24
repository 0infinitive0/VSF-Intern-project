interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)

  return (
    <div className="pagination">
      <span className="tabular-nums">
        {from}–{to} / {total}
      </span>
      <button
        type="button"
        className="pagination__btn"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Trang trước"
      >
        ‹
      </button>
      <span className="tabular-nums">
        {page} / {pageCount}
      </span>
      <button
        type="button"
        className="pagination__btn"
        disabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
        aria-label="Trang sau"
      >
        ›
      </button>
    </div>
  )
}
