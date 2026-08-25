import { pipelineRunStateVi } from '../../lib/pipeline-run-state-vi'

/** pipeline-status-chip.tsx — C1's last-run-state chip (phase-14-pipelines-
 * list.md checklist), copied verbatim from the design: `✓ Thành công` /
 * `✕ Lỗi` / `◐ Đang chạy`. `queued` and `null` (no run yet) fall back to a
 * neutral chip -- the design's three states don't cover them, but hiding
 * the chip entirely would look broken on a pipeline that's never run.
 * Icon+color stay local to the chip; the Vietnamese word itself comes from
 * `pipeline-run-state-vi.ts`, shared with the sparkline's tooltip. */
const ICON: Record<string, string> = { success: '✓', failed: '✕', running: '◐', queued: '…' }
const TONE: Record<string, { bg: string; fg: string }> = {
  success: { bg: 'var(--ok-soft)', fg: 'var(--ok-ink)' },
  failed: { bg: 'var(--err-soft)', fg: 'var(--err)' },
  running: { bg: 'var(--acc-soft)', fg: 'var(--acc)' },
  queued: { bg: 'var(--fill)', fg: 'var(--t4)' },
}

export function PipelineStatusChip({ state }: { state: string | null | undefined }) {
  const tone = (state && TONE[state]) || { bg: 'var(--fill)', fg: 'var(--t4)' }
  const label = state && ICON[state] ? `${ICON[state]} ${pipelineRunStateVi(state)}` : 'Chưa chạy lần nào'
  const chip = { label, ...tone }
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 24,
        padding: '0 10px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: chip.bg,
        color: chip.fg,
      }}
    >
      {chip.label}
    </span>
  )
}
