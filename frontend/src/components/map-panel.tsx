import { S } from '../strings'

/**
 * MapPanel — right-side column, static placeholder.
 * No map data source is wired up yet, so this stays a plain
 * illustrative panel rather than fake interactive controls.
 * Every control here is decorative chrome: disabled, no click handler,
 * no map library, no tiles, no pins.
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

      {/* Top overlay: search + filter pills */}
      <div className="absolute top-4 left-4 right-4 flex flex-col gap-2 z-10">
        <input
          type="text"
          className="w-full max-w-xs bg-surface-background border border-outline-variant px-3 py-2 rounded-lg text-sm opacity-60 cursor-not-allowed"
          placeholder={S.mapSearchPlaceholder}
          disabled
          title={S.mapControlDisabledHint}
          aria-label={S.mapSearchPlaceholder}
        />
        <div className="flex gap-2 flex-wrap">
          {[
            { icon: 'attractions', label: S.mapFilterAttractions },
            { icon: 'hotel', label: S.mapFilterProperties },
            { icon: 'restaurant', label: S.mapFilterFood },
            { icon: 'shopping_bag', label: S.mapFilterShopping },
          ].map((filter) => (
            <button
              key={filter.label}
              type="button"
              disabled
              className="bg-surface-background border border-outline-variant px-3 py-2 rounded-lg flex items-center gap-2 text-sm opacity-60 cursor-not-allowed"
              title={S.mapControlDisabledHint}
            >
              <span className="material-symbols-outlined text-sm" aria-hidden="true">
                {filter.icon}
              </span>
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      {/* Floating tools */}
      <div className="absolute bottom-8 right-6 flex flex-col gap-2 z-10">
        <button
          type="button"
          disabled
          className="w-10 h-10 bg-surface-background rounded-lg border border-outline-variant flex items-center justify-center opacity-60 cursor-not-allowed"
          title={S.mapControlDisabledHint}
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">
            layers
          </span>
        </button>
        <button
          type="button"
          disabled
          className="w-10 h-10 bg-surface-background rounded-lg border border-outline-variant flex items-center justify-center opacity-60 cursor-not-allowed"
          title={S.mapControlDisabledHint}
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">
            my_location
          </span>
        </button>
        <div className="flex flex-col bg-surface-background rounded-lg border border-outline-variant overflow-hidden">
          <button
            type="button"
            disabled
            className="w-10 h-10 flex items-center justify-center opacity-60 cursor-not-allowed"
            title={S.mapControlDisabledHint}
          >
            +
          </button>
          <button
            type="button"
            disabled
            className="w-10 h-10 flex items-center justify-center opacity-60 cursor-not-allowed"
            title={S.mapControlDisabledHint}
          >
            −
          </button>
        </div>
      </div>

      <div className="relative text-center text-on-surface-variant px-6 z-10">
        <span className="material-symbols-outlined text-4xl" aria-hidden="true">
          map
        </span>
        <div className="font-medium text-on-surface mt-2">{S.mapPlaceholderTitle}</div>
        <div className="text-sm mt-1">{S.mapPlaceholderBody}</div>
      </div>
    </section>
  )
}
