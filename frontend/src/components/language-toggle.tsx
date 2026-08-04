/**
 * language-toggle.tsx — manual EN | VI switch in the nav.
 * Persists via the shared i18n instance (i18n/index.ts listens to
 * 'languageChanged' and writes localStorage). Accessible: role="group",
 * each option is a <button aria-pressed={...}>.
 */
import { useTranslation } from 'react-i18next'

const OPTIONS = [
  { code: 'en', label: 'EN' },
  { code: 'vi', label: 'VI' },
] as const

export default function LanguageToggle() {
  const { i18n } = useTranslation()

  return (
    <div
      role="group"
      aria-label="Language"
      className="flex items-center gap-0.5 bg-surface-container-high rounded-full p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = i18n.language === option.code
        return (
          <button
            key={option.code}
            type="button"
            aria-pressed={active}
            onClick={() => i18n.changeLanguage(option.code)}
            className={`px-2.5 py-1 text-[11px] font-semibold rounded-full transition-colors ${
              active
                ? 'bg-primary text-on-primary'
                : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}