import { S } from '../strings.js'

/**
 * MapPanel — right-side column, static placeholder.
 * No map data source is wired up yet, so this stays a plain
 * illustrative panel rather than fake interactive controls.
 */
export default function MapPanel() {
  return (
    <section className="flex-1 relative bg-surface-muted overflow-hidden flex items-center justify-center">
      <div
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage: 'radial-gradient(#c3c5d8 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }}
        aria-hidden="true"
      />
      <div className="relative text-center text-text-secondary px-6">
        <span className="material-symbols-outlined text-4xl" aria-hidden="true">
          map
        </span>
        <div className="font-medium text-text-primary mt-2">{S.mapPlaceholderTitle}</div>
        <div className="text-sm mt-1">{S.mapPlaceholderBody}</div>
      </div>
    </section>
  )
}
