/**
 * pipeline-field-badge.tsx — B3 (phase-09-hotel-edit.md), L35. Decision #7
 * (R1, phương án iii): a pipeline-managed field is NOT disabled, only
 * warned about -- the icon is a signal that the next ETL run overwrites
 * whatever gets typed here, not a lock. Native `title` for the tooltip, same
 * choice as hotel-embedding-dot.tsx (Phase 7): one badge per field doesn't
 * justify a tooltip primitive that doesn't exist yet in ui/.
 */
export function PipelineFieldBadge() {
  return (
    <span
      title="Ô này do pipeline cập nhật, sửa tay sẽ bị ghi đè ở lần chạy kế tiếp."
      style={{ fontSize: 12, color: 'var(--warn)', cursor: 'help' }}
    >
      🔒
    </span>
  )
}
