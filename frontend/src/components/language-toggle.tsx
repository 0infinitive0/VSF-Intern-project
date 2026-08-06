/**
 * language-toggle.tsx — manual VI | EN switch, restyled for the sidebar rail
 * (Phase 5) as a full-width segmented control. Persists via the shared i18n
 * instance (i18n/index.ts listens to 'languageChanged' and writes
 * localStorage). Accessible: role="group", each option is a
 * <button aria-pressed={...}>.
 */
import { useTranslation } from 'react-i18next'

const OPTIONS = [
  { code: 'vi', label: 'VI' },
  { code: 'en', label: 'EN' },
] as const

export default function LanguageToggle() {
  const { i18n } = useTranslation()

  return (
    <div
      role="group"
      aria-label="Language"
      className="flex items-center gap-0.5 bg-fill rounded-xl p-[3px]"
    >
      {OPTIONS.map((option) => {
        const active = i18n.language === option.code
        return (
          <button
            key={option.code}
            type="button"
            aria-pressed={active}
            onClick={() => i18n.changeLanguage(option.code)}
            className={`flex-1 py-1.5 text-[11px] font-semibold rounded-[9px] transition-colors ${
              active
                ? 'bg-surface-background text-on-surface shadow-sm'
                : 'text-on-surface-faint hover:text-on-surface-variant'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}