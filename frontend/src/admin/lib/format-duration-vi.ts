/** `3 phút 20 giây` (plan's mandated shape for pipeline run durations/ETAs,
 * phase-14-pipelines-list.md). Zero minutes drops the "phút" clause, zero
 * remaining seconds drops the "giây" clause -- never "0 giây" tacked on. */
export function formatDurationVi(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds))
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes === 0) return `${remainingSeconds} giây`
  if (remainingSeconds === 0) return `${minutes} phút`
  return `${minutes} phút ${remainingSeconds} giây`
}
