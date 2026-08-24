import type { ReactNode } from 'react'

interface EmptyStateProps {
  title?: string
  description?: string
  action?: ReactNode
}

export function EmptyState({
  title = 'Chưa có dữ liệu',
  description = 'Không có bản ghi nào khớp bộ lọc hiện tại. Thử mở rộng khoảng ngày hoặc bỏ bớt điều kiện lọc.',
  action,
}: EmptyStateProps) {
  return (
    <div className="state-block">
      <div className="state-block__icon state-block__icon--empty">▢</div>
      <div className="state-block__title">{title}</div>
      <div className="state-block__desc">{description}</div>
      {action}
    </div>
  )
}
