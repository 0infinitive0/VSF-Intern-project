import { useTranslation } from 'react-i18next'

/**
 * MatchScoreRing — the conic-gradient match ring from HotelCard/HotelDetail.
 *
 * `match_score` is a real 0..1 composite ranking score from the backend
 * (Phase 2). The label must say what it is — a fit/match score, not a
 * satisfaction probability — so the "MATCH"/"ĐỘ KHỚP" word stays, per
 * phase-08 §"Vòng AI Match Score".
 *
 * Colour tiers come from the design script (V-OTA Planner.dc.html:2444):
 * ≥90% --ok, ≥80% --warn, below --err. Sizes: card 62/50px, detail panel
 * 58/46px (checklist Phase 8).
 *
 * When the backend predates Phase 2 there is no score — the ring is hidden
 * ENTIRELY (no 0%, no default), so the card still renders cleanly.
 */
export default function MatchScoreRing({
  score,
  variant = 'card',
}: {
  score?: number | null
  variant?: 'card' | 'panel'
}) {
  const { t } = useTranslation()
  if (score == null || !Number.isFinite(score)) return null

  const pct = Math.round(Math.min(1, Math.max(0, score)) * 100)
  const color = pct >= 90 ? 'var(--ok)' : pct >= 80 ? 'var(--warn)' : 'var(--err)'
  const outer = variant === 'panel' ? 58 : 62
  const inner = variant === 'panel' ? 46 : 50

  return (
    <div
      className="rounded-full flex items-center justify-center flex-none"
      role="img"
      aria-label={t('matchScoreAria', { pct })}
      style={{
        width: outer,
        height: outer,
        background: `conic-gradient(${color} ${pct * 3.6}deg, var(--fill2) 0)`,
      }}
    >
      <div
        className="rounded-full bg-glass-3 flex flex-col items-center justify-center"
        style={{ width: inner, height: inner }}
      >
        <div
          className="font-[590] tracking-[-0.4px] text-on-surface"
          style={{ fontSize: variant === 'panel' ? 13.5 : 14 }}
        >
          {pct}%
        </div>
        <div className="text-[8px] tracking-[0.08em] uppercase text-on-surface-muted">
          {t('matchWord')}
        </div>
      </div>
    </div>
  )
}
