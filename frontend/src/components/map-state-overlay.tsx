/**
 * MapStateOverlay — the shared "something isn't right, here's why" surface
 * for MapView: missing token, load error, and no-location-data are all
 * visually the same shape (icon + title + body + optional action), so this
 * is the one component all three render through instead of three near-
 * identical hand-rolled blocks (Phase 10.5 §18/19 — reuse the honest-state
 * pattern rather than scatter it). Loading is deliberately NOT this
 * component — a shimmer is a wait cue, not a message (see MapView).
 */
export default function MapStateOverlay({
  icon,
  title,
  body,
  action,
}: {
  icon: string
  title: string
  body: string
  action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-surface-muted px-6">
      <div className="text-center text-on-surface-variant">
        <span className="material-symbols-outlined text-4xl" aria-hidden="true">
          {icon}
        </span>
        <div className="font-medium text-on-surface mt-2">{title}</div>
        <div className="text-sm mt-1">{body}</div>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-4 px-4 py-2 rounded-[13px] border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] cursor-pointer hover:bg-glass-3"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  )
}
