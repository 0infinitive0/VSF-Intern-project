/** pipeline-run-state-vi.ts — the one Airflow run-state → Vietnamese word
 * table for C1 (phase-14-pipelines-list.md). Shared by the status chip
 * (which adds its own icon/color per state) and the sparkline tooltip
 * (plain text) so a raw state string like "upstream_failed" never reaches
 * the screen -- the plan's own "không chỗ nào trên UI hiện ... tên DAG kỹ
 * thuật" boundary extends to run states too. */
const PIPELINE_RUN_STATE_VI: Record<string, string> = {
  success: 'Thành công',
  failed: 'Lỗi',
  running: 'Đang chạy',
  queued: 'Đang chờ',
}

export function pipelineRunStateVi(state: string | null | undefined): string {
  if (!state) return 'Chưa chạy'
  return PIPELINE_RUN_STATE_VI[state] ?? 'Không rõ'
}
