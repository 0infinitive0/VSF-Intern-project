import type { HTMLAttributes, ReactNode } from 'react'

type GlassVariant = 'panel' | 'card' | 'chip'

const VARIANT_CLASS: Record<GlassVariant, string> = {
  panel: 'glass-panel',
  card: 'glass-card',
  chip: 'glass-chip',
}

/**
 * GlassPanel — thin wrapper over the glass-panel/glass-card/glass-chip
 * utilities from styles.css (Phase 1), so later phases never re-hand-roll
 * the blur/border/shadow formula.
 */
export default function GlassPanel({
  variant = 'panel',
  className = '',
  children,
  ...rest
}: {
  variant?: GlassVariant
  className?: string
  children?: ReactNode
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`${VARIANT_CLASS[variant]} ${className}`} {...rest}>
      {children}
    </div>
  )
}
