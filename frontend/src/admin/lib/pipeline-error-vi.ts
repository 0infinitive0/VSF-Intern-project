/**
 * pipeline-error-vi.ts — translates `POST /pipelines/{dag_id}/runs`'s
 * error `detail` codes into Vietnamese for C1 (phase-14-pipelines-list.md).
 * Same idiom as booking-error-vi.ts: an unrecognized code passes through
 * unchanged rather than burying the real detail behind a generic message.
 */
const PIPELINE_ERROR_VI: Record<string, string> = {
  dag_already_running: 'Pipeline này đang chạy rồi. Đợi lần chạy hiện tại xong rồi thử lại.',
  dag_not_allowed: 'Không thể chạy pipeline này.',
  airflow_unavailable: 'Không kết nối được Airflow — pipeline không chạy được lúc này.',
}

export function pipelineErrorVi(code: string | null | undefined): string {
  if (!code) return 'Không chạy được pipeline. Thử lại hoặc kiểm tra log máy chủ.'
  return PIPELINE_ERROR_VI[code] ?? code
}
