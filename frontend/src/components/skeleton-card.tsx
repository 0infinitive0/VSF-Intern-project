import type { ReactNode } from 'react'

/**
 * SkeletonCard — reusable shimmer placeholder (phase-07 "skeleton-card"). A
 * skeleton only promises that content is loading; it never claims anything
 * about backend progress, so it is honest by construction.
 *
 * Variants:
 *  - 'lines' (default): staggered shimmer bars, matching the design's
 *    generating-state skeletons (VP-OTA Planner.dc.html:150 — bar radius 14,
 *    gradient --fill → --g3 → --fill moving via vShimmer 1.5s).
 *  - 'hotel': mirrors the upcoming HotelCard shape (phase-08: 112×112 media
 *    thumb + name/area/price rows) so the hotels stage and its generating
 *    placeholder share one geometry — no layout jump when real cards land.
 */
export default function SkeletonCard({
  variant = 'lines',
}: {
  variant?: 'lines' | 'hotel'
}): ReactNode {
  if (variant === 'hotel') {
    return (
      <div className="flex gap-3.5" aria-hidden="true">
        <div className="shimmer-block w-[112px] h-[112px] rounded-[20px] flex-none" />
        <div className="flex-1 flex flex-col justify-center gap-2.5">
          <div className="shimmer-block h-[14px] w-[62%] rounded-[14px]" />
          <div className="shimmer-block h-[11px] w-[38%] rounded-[14px]" />
          <div className="shimmer-block h-[15px] w-[46%] rounded-[14px]" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2.5" aria-hidden="true">
      <div className="shimmer-block h-[14px] w-full rounded-[14px]" />
      <div className="shimmer-block h-[14px] w-[72%] rounded-[14px]" />
      <div className="shimmer-block h-[14px] w-[44%] rounded-[14px]" />
    </div>
  )
}
