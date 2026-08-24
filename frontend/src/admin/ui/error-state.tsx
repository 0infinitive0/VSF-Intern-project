interface ErrorStateProps {
  title?: string
  description: string
  requestId?: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Không tải được dữ liệu', description, requestId, onRetry }: ErrorStateProps) {
  return (
    <div className="state-block">
      <div className="state-block__icon state-block__icon--error">!</div>
      <div className="state-block__title">{title}</div>
      <div className="state-block__desc">{description}</div>
      {requestId && <div className="state-block__meta">req_id: {requestId}</div>}
      {onRetry && (
        <button type="button" className="btn btn--primary btn--sm" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  )
}
